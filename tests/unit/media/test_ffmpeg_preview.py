from __future__ import annotations

import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from core.adapters.media.ffmpeg_preview import FfmpegPreviewRenderer, FfprobeMediaProbe
from core.domain.channel_models import SubtitleStyle
from core.domain.media_models import PreparedScene, VisualAsset, VisualAssetKind


def _scene(duration_ms: int = 1000) -> PreparedScene:
    return PreparedScene(
        1,
        0,
        duration_ms,
        VisualAsset(1, VisualAssetKind.GENERATED_BACKGROUND),
    )


def test_renderer_uses_argument_list_and_cpu_bounded_preview_profile(
    tmp_path: Path,
) -> None:
    calls = []

    def runner(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, b"", b"")

    voice = tmp_path / "voice.wav"
    subtitle = tmp_path / "subtitle.srt"
    voice.write_bytes(b"voice")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")

    FfmpegPreviewRenderer(runner=runner).render(
        voice_path=voice,
        subtitle_path=subtitle,
        scenes=(_scene(),),
        output_path=tmp_path / "preview.mp4.part",
        aspect_ratio="16:9",
        subtitle_style=SubtitleStyle(),
        bgm_path=None,
    )

    args, kwargs = calls[0]
    assert isinstance(args, list)
    assert kwargs.get("shell") is None
    assert args[args.index("-threads") + 1] == "2"
    assert args[args.index("-s") + 1] == "854x480"
    assert args[args.index("-pix_fmt") + 1] == "yuv420p"
    assert "+faststart" in args
    assert args[-1].endswith("preview.mp4.part")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is unavailable")
def test_real_ffmpeg_preview_is_browser_playable_and_covers_voice(
    tmp_path: Path,
) -> None:
    voice = tmp_path / "voice.wav"
    with wave.open(str(voice), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(b"\x00\x00" * 16_000)
    subtitle = tmp_path / "subtitle.srt"
    subtitle.write_text(
        "1\n00:00:00,000 --> 00:00:00,900\nXin chào Việt Nam\n",
        encoding="utf-8",
    )
    preview = tmp_path / "preview.mp4"

    FfmpegPreviewRenderer(timeout_seconds=30).render(
        voice_path=voice,
        subtitle_path=subtitle,
        scenes=(_scene(),),
        output_path=preview,
        aspect_ratio="16:9",
        subtitle_style=SubtitleStyle(),
        bgm_path=None,
    )
    info = FfprobeMediaProbe(timeout_seconds=10).probe(preview)

    assert info.codec == "h264"
    assert (info.width, info.height) == (854, 480)
    assert 900 <= info.duration_ms <= 1200
