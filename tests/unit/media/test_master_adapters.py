from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from core.adapters.media.ffmpeg_master import FfmpegMasterRenderer
from core.adapters.media.ffmpeg_preview import FfprobeMediaProbe
from core.domain.channel_models import SubtitleStyle
from core.domain.media_models import PreparedScene, VisualAsset, VisualAssetKind
from core.domain.models import RemixClipSnapshot


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        output = Path(args[-1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"master")
        return SimpleNamespace(stdout=b"", stderr=b"")


def test_story_master_command_uses_1080p_publish_profile(tmp_path: Path) -> None:
    runner = RecordingRunner()
    renderer = FfmpegMasterRenderer(runner=runner)
    visual = tmp_path / "visuals" / "source.mp4"
    visual.parent.mkdir(parents=True)
    visual.write_bytes(b"visual")
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"voice")
    subtitle = tmp_path / "subtitle.srt"
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nText\n", encoding="utf-8")
    output = tmp_path / "master.mp4.part"

    renderer.render_story(
        voice_path=voice,
        subtitle_path=subtitle,
        scenes=(
            PreparedScene(
                1,
                0,
                4_000,
                VisualAsset(1, VisualAssetKind.VIDEO, "visuals/source.mp4"),
            ),
        ),
        source_paths=(visual,),
        output_path=output,
        aspect_ratio="16:9",
        subtitle_style=SubtitleStyle(),
        bgm_path=None,
        workspace_root=tmp_path,
        preset="superfast",
        crf=23,
    )

    args = runner.calls[0]
    assert args[0] == "ffmpeg"
    assert args[args.index("-s") + 1] == "1920x1080"
    assert args[args.index("-preset") + 1] == "superfast"
    assert args[args.index("-crf") + 1] == "23"
    assert args[args.index("-threads") + 1] == "2"
    assert args[args.index("-r") + 1] == "30"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert args[args.index("-c:a") + 1] == "aac"
    assert "+faststart" in args
    assert str(visual) in args
    assert all("preview" not in value for value in args)


def test_remix_master_command_reapplies_transforms_to_downloads(
    tmp_path: Path,
) -> None:
    runner = RecordingRunner()
    renderer = FfmpegMasterRenderer(runner=runner)
    first = tmp_path / "source-1.mp4"
    second = tmp_path / "source-2.mp4"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    output = tmp_path / "master.mp4.part"

    renderer.render_remix(
        sources=(
            (
                first,
                RemixClipSnapshot(
                    "https://media.example/one", 1, 5, 1, 1.25, "fill", True
                ),
                True,
            ),
            (
                second,
                RemixClipSnapshot(
                    "https://media.example/two", 0, 3, 2, 1, "fit", False
                ),
                False,
            ),
        ),
        output_path=output,
        aspect_ratio="9:16",
        bgm_path=None,
        preset="superfast",
        crf=23,
    )

    args = runner.calls[0]
    graph = args[args.index("-filter_complex") + 1]
    assert str(first) in args and str(second) in args
    assert "trim=start=1.000:end=5.000" in graph
    assert "hflip" in graph
    assert "crop=1080:1920" in graph
    assert "pad=1080:1920" in graph
    assert "atempo=1.25" in graph
    assert "concat=n=2:v=1:a=1" in graph
    assert args[args.index("-s") + 1] == "1080x1920"
    assert args[args.index("-threads") + 1] == "2"


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg is unavailable",
)
def test_story_master_smoke_produces_valid_1080p_media(tmp_path: Path) -> None:
    visual = tmp_path / "visual.mp4"
    voice = tmp_path / "voice.wav"
    subtitle = tmp_path / "subtitle.srt"
    output = tmp_path / "master.mp4.part"
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
            "color=c=blue:s=320x180:r=30:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(visual),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
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
            "sine=frequency=440:sample_rate=48000:duration=1",
            str(voice),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:00,900\nMaster smoke\n",
        encoding="utf-8",
    )

    FfmpegMasterRenderer(timeout_seconds=60).render_story(
        voice_path=voice,
        subtitle_path=subtitle,
        scenes=(
            PreparedScene(
                1,
                0,
                1_000,
                VisualAsset(1, VisualAssetKind.VIDEO, "visual.mp4"),
            ),
        ),
        source_paths=(visual,),
        output_path=output,
        aspect_ratio="16:9",
        subtitle_style=SubtitleStyle(font_size=24),
        bgm_path=None,
        workspace_root=tmp_path,
        preset="superfast",
        crf=23,
    )

    info = FfprobeMediaProbe().probe(output)
    assert info.codec == "h264"
    assert (info.width, info.height) == (1920, 1080)
    assert info.has_audio is True
    assert info.audio_codec == "aac"
    assert 900 <= info.duration_ms <= 1_100


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg is unavailable",
)
def test_remix_master_smoke_produces_valid_portrait_media(tmp_path: Path) -> None:
    source = tmp_path / "source.mp4"
    output = tmp_path / "master.mp4.part"
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
            "color=c=green:s=320x180:r=30:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )

    FfmpegMasterRenderer(timeout_seconds=60).render_remix(
        sources=(
            (
                source,
                RemixClipSnapshot(
                    "https://media.example/source", 0, 0.5, 1, 1, "fit", True
                ),
                False,
            ),
        ),
        output_path=output,
        aspect_ratio="9:16",
        bgm_path=None,
        preset="superfast",
        crf=23,
    )

    info = FfprobeMediaProbe().probe(output)
    assert info.codec == "h264"
    assert (info.width, info.height) == (1080, 1920)
    assert info.has_audio is True
    assert info.audio_codec == "aac"
    assert 400 <= info.duration_ms <= 600
