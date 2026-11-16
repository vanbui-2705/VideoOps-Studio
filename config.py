"""Centralized application configuration and directory management."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    """System runtime configuration."""

    BASE_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent)
    TEMP_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "temp")
    OUTPUT_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "outputs")
    CHANNELS_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "channels")
    ASSETS_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "assets")
    BGM_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "assets" / "bgm")
    FONTS_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent / "assets" / "fonts")

    # Hardware & Performance Constraints
    MAX_FFMPEG_THREADS: int = 2
    MAX_DISK_USAGE_GB: float = 40.0

    # API Keys & Credentials
    PEXELS_API_KEY: str | None = None
    GEMINI_API_KEY: str | None = None
    YOUTUBE_CLIENT_ID: str | None = None
    YOUTUBE_CLIENT_SECRET: str | None = None
    YOUTUBE_REFRESH_TOKEN: str | None = None

    def ensure_directories(self) -> None:
        """Create runtime directories if they do not exist."""
        for path in [
            self.TEMP_DIR,
            self.OUTPUT_DIR,
            self.CHANNELS_DIR,
            self.ASSETS_DIR,
            self.BGM_DIR,
            self.FONTS_DIR,
        ]:
            path.mkdir(parents=True, exist_ok=True)


def load_config() -> AppConfig:
    """Load configuration from environment variables."""
    cfg = AppConfig(
        PEXELS_API_KEY=os.getenv("PEXELS_API_KEY"),
        GEMINI_API_KEY=os.getenv("GEMINI_API_KEY"),
        YOUTUBE_CLIENT_ID=os.getenv("YOUTUBE_CLIENT_ID"),
        YOUTUBE_CLIENT_SECRET=os.getenv("YOUTUBE_CLIENT_SECRET"),
        YOUTUBE_REFRESH_TOKEN=os.getenv("YOUTUBE_REFRESH_TOKEN"),
    )
    cfg.ensure_directories()
    return cfg
