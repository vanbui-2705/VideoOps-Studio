from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.adapters.media.ffmpeg_preview import FfprobeMediaProbe
from core.adapters.media.remix import (
    FfmpegRemixPreviewRenderer,
    FfmpegRemixProcessor,
    YtDlpSourceDownloader,
)
from core.adapters.media.workspace import JobWorkspace
from core.domain.errors import MediaConfigurationError
from core.domain.models import RemixClipSnapshot


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        output = (
            Path(args[args.index("--output") + 1])
            if "--output" in args
            else Path(args[-1])
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"media")
        return SimpleNamespace(stdout=b"", stderr=b"")


def _clip(**changes) -> RemixClipSnapshot:
    values = {
        "url": "https://media.example.com/watch/123",
        "start_seconds": 1.0,
        "end_seconds": 5.0,
        "order": 1,
        "speed": 1.25,
        "crop_mode": "fill",
        "mirror": True,
    }
    values.update(changes)
    return RemixClipSnapshot(**values)


def test_ytdlp_uses_bounded_argument_list_and_workspace_output(tmp_path: Path) -> None:
    runner = RecordingRunner()
    downloader = YtDlpSourceDownloader(
        binary="yt-dlp",
        timeout_seconds=20,
        max_bytes=1024,
        runner=runner,
        resolver=lambda host: ("93.184.216.34",),
    )
    workspace = JobWorkspace(tmp_path, "job-1", 1)

    output = downloader.download(
        "https://media.example.com/watch/123",
        workspace,
        "sources/source-1.mp4",
    )

    args = runner.calls[0]
    assert args[0] == "yt-dlp"
    assert "--no-playlist" in args
    assert "--max-filesize" in args
    assert "1080" in " ".join(args)
    assert output == workspace.final_path("sources/source-1.mp4")
    assert output.is_file()


def test_ytdlp_rejects_private_resolution_before_process(tmp_path: Path) -> None:
    runner = RecordingRunner()
    downloader = YtDlpSourceDownloader(
        runner=runner,
        resolver=lambda host: ("10.0.0.5",),
    )

    with pytest.raises(MediaConfigurationError):
        downloader.download(
            "https://media.example.com/watch/123",
            JobWorkspace(tmp_path, "job-1", 1),
            "sources/source-1.mp4",
        )

    assert runner.calls == []


def test_ytdlp_removes_oversized_partial_download(tmp_path: Path) -> None:
    runner = RecordingRunner()
    downloader = YtDlpSourceDownloader(
        max_bytes=4,
        runner=runner,
        resolver=lambda host: ("93.184.216.34",),
    )
    workspace = JobWorkspace(tmp_path, "job-1", 1)
    relative_path = "sources/source-1.mp4"

    with pytest.raises(MediaConfigurationError, match="size limit"):
        downloader.download(
            "https://media.example.com/watch/123",
            workspace,
            relative_path,
        )

    assert not workspace.part_path(relative_path).exists()
    assert not workspace.final_path(relative_path).exists()


def test_ffmpeg_normalizer_builds_safe_transform_command(tmp_path: Path) -> None:
    runner = RecordingRunner()
    processor = FfmpegRemixProcessor(runner=runner)
    source = tmp_path / "source.mp4"
    source.write_bytes(b"source")
    output = tmp_path / "clip.mp4.part"

    processor.normalize(
        source_path=source,
        output_path=output,
        clip=_clip(),
        aspect_ratio="9:16",
        has_audio=True,
    )

    args = runner.calls[0]
    assert isinstance(args, list)
    assert "-filter_complex" in args
    graph = args[args.index("-filter_complex") + 1]
    assert "trim=start=1.000:end=5.000" in graph
    assert "hflip" in graph
    assert "crop=270:480" in graph
    assert "atempo=1.25" in graph
    assert args[args.index("-threads") + 1] == "2"


def test_remix_preview_concatenates_in_order_with_browser_profile(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    renderer = FfmpegRemixPreviewRenderer(runner=runner)
    clips = (tmp_path / "one.mp4", tmp_path / "two.mp4")
    for clip in clips:
        clip.write_bytes(b"clip")

    renderer.render(
        clips=clips,
        output_path=tmp_path / "preview.mp4.part",
        aspect_ratio="16:9",
    )

    args = runner.calls[0]
    graph = args[args.index("-filter_complex") + 1]
    assert "[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1" in graph
    assert args[args.index("-s") + 1] == "854x480"
    assert "+faststart" in args
    assert args[args.index("-threads") + 1] == "2"


def test_ytdlp_timeout_is_sanitized(tmp_path: Path) -> None:
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 1)

    downloader = YtDlpSourceDownloader(
        runner=timeout,
        resolver=lambda host: ("93.184.216.34",),
    )
    with pytest.raises(Exception) as failure:
        downloader.download(
            "https://media.example.com/watch/secret?token=value",
            JobWorkspace(tmp_path, "job-1", 1),
            "sources/source-1.mp4",
        )
    assert "token" not in str(failure.value)


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg is unavailable",
)
def test_ffmpeg_remix_smoke_produces_browser_preview(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=640x360:r=30:d=2",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    normalized_partial = tmp_path / "normalized.mp4.part"
    FfmpegRemixProcessor(timeout_seconds=30).normalize(
        source_path=source,
        output_path=normalized_partial,
        clip=_clip(start_seconds=0, end_seconds=1, speed=1, mirror=False),
        aspect_ratio="16:9",
        has_audio=True,
    )
    normalized = tmp_path / "normalized.mp4"
    normalized_partial.replace(normalized)
    preview_partial = tmp_path / "preview.mp4.part"
    FfmpegRemixPreviewRenderer(timeout_seconds=30).render(
        clips=(normalized,),
        output_path=preview_partial,
        aspect_ratio="16:9",
    )
    preview = tmp_path / "preview.mp4"
    preview_partial.replace(preview)

    info = FfprobeMediaProbe(timeout_seconds=10).probe(preview)

    assert info.codec == "h264"
    assert (info.width, info.height) == (854, 480)
    assert info.has_audio is True
    assert 900 <= info.duration_ms <= 1100
