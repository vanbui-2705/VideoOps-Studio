from pathlib import Path

import pytest

from config import AppConfig
from core.composition import validate_media_runtime, validate_remix_runtime


def test_media_startup_rejects_missing_binary(tmp_path: Path) -> None:
    config = AppConfig(
        TEMP_DIR=tmp_path,
        FFMPEG_BINARY="definitely-missing-videoops-ffmpeg",
        FFPROBE_BINARY="ffprobe",
        MEDIA_MIN_FREE_DISK_GB=0,
    )

    with pytest.raises(ValueError, match="binary"):
        validate_media_runtime(config)


def test_media_startup_accepts_installed_ffmpeg(tmp_path: Path) -> None:
    config = AppConfig(
        TEMP_DIR=tmp_path,
        FFMPEG_BINARY="ffmpeg",
        FFPROBE_BINARY="ffprobe",
        MEDIA_MIN_FREE_DISK_GB=0,
    )

    validate_media_runtime(config)


def test_remix_startup_rejects_missing_ytdlp(tmp_path: Path) -> None:
    config = AppConfig(
        TEMP_DIR=tmp_path,
        FFMPEG_BINARY="ffmpeg",
        FFPROBE_BINARY="ffprobe",
        YTDLP_BINARY="definitely-missing-videoops-ytdlp",
        MEDIA_MIN_FREE_DISK_GB=0,
    )

    with pytest.raises(ValueError, match="remix binary"):
        validate_remix_runtime(config)
