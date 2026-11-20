"""Centralized application configuration and directory management."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AppConfig:
    """System runtime configuration."""

    BASE_DIR: Path = field(default_factory=lambda: Path(__file__).resolve().parent)
    TEMP_DIR: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "temp"
    )
    OUTPUT_DIR: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "outputs"
    )
    CHANNELS_DIR: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "channels"
    )
    ASSETS_DIR: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "assets"
    )
    BGM_DIR: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "assets" / "bgm"
    )
    FONTS_DIR: Path = field(
        default_factory=lambda: Path(__file__).resolve().parent / "assets" / "fonts"
    )

    # Hardware & Performance Constraints
    MAX_FFMPEG_THREADS: int = 2
    MAX_DISK_USAGE_GB: float = 40.0

    # API Keys & Credentials
    PEXELS_API_KEY: str | None = field(default=None, repr=False)
    PIXABAY_API_KEY: str | None = field(default=None, repr=False)
    GEMINI_API_KEY: str | None = field(default=None, repr=False)
    YOUTUBE_CLIENT_ID: str | None = field(default=None, repr=False)
    YOUTUBE_CLIENT_SECRET: str | None = field(default=None, repr=False)
    YOUTUBE_REFRESH_TOKEN: str | None = field(default=None, repr=False)

    # Durable workflow persistence and worker runtime
    DATABASE_URL: str | None = field(default=None, repr=False)
    TEST_DATABASE_URL: str | None = field(default=None, repr=False)
    DB_POOL_SIZE: int = 3
    DB_MAX_OVERFLOW: int = 2
    WORKER_ID: str = "videoops-worker"
    WORK_LEASE_SECONDS: int = 300
    WORK_POLL_INTERVAL_SECONDS: float = 2.0
    WORK_MAX_ATTEMPTS: int = 3

    # Channel administration is opt-in for trusted/private deployments.
    CHANNEL_ADMIN_ENABLED: bool = False

    # AI Story generation. Model IDs are deployment configuration, not defaults.
    LLM_PROVIDER: str = "disabled"
    LLM_MODEL: str = ""
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_MAX_OUTPUT_TOKENS: int = 4096
    LLM_TEMPERATURE: float = 0.7
    LLM_MAX_ATTEMPTS: int = 3
    LLM_PROMPT_VERSION: str = "story-v1"
    OPENAI_API_KEY: str | None = field(default=None, repr=False)
    STORY_MIN_CHARACTERS: int = 100
    STORY_MAX_CHARACTERS: int = 20000
    STORY_MAX_SCENES: int = 100
    STORY_MAX_KEYWORDS_PER_SCENE: int = 10

    # Story preview media preparation
    FFMPEG_BINARY: str = "ffmpeg"
    FFPROBE_BINARY: str = "ffprobe"
    TTS_CONNECT_TIMEOUT_SECONDS: int = 10
    TTS_RECEIVE_TIMEOUT_SECONDS: int = 60
    STOCK_REQUEST_TIMEOUT_SECONDS: float = 20.0
    STOCK_MAX_DOWNLOAD_BYTES: int = 100 * 1024 * 1024
    PREVIEW_RENDER_TIMEOUT_SECONDS: float = 300.0
    PREVIEW_DURATION_TOLERANCE_MS: int = 250
    MEDIA_MIN_FREE_DISK_GB: float = 0.25
    MEDIA_MAX_ATTEMPTS: int = 3
    MEDIA_RENDER_CONCURRENCY: int = 1

    # Remix source ingestion and preview preparation
    YTDLP_BINARY: str = "yt-dlp"
    REMIX_DOWNLOAD_TIMEOUT_SECONDS: float = 300.0
    REMIX_MAX_DOWNLOAD_BYTES: int = 1024 * 1024 * 1024
    REMIX_MAX_SOURCES: int = 10
    REMIX_MAX_SOURCE_DURATION_SECONDS: float = 7200.0
    REMIX_DURATION_TOLERANCE_MS: int = 750

    # Approved 1080p master rendering
    MASTER_RENDER_TIMEOUT_SECONDS: float = 900.0
    MASTER_PRESET: str = "superfast"
    MASTER_CRF: int = 23
    MASTER_DURATION_TOLERANCE_MS: int = 1000

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
        PIXABAY_API_KEY=os.getenv("PIXABAY_API_KEY"),
        GEMINI_API_KEY=os.getenv("GEMINI_API_KEY"),
        YOUTUBE_CLIENT_ID=os.getenv("YOUTUBE_CLIENT_ID"),
        YOUTUBE_CLIENT_SECRET=os.getenv("YOUTUBE_CLIENT_SECRET"),
        YOUTUBE_REFRESH_TOKEN=os.getenv("YOUTUBE_REFRESH_TOKEN"),
        DATABASE_URL=os.getenv("DATABASE_URL"),
        TEST_DATABASE_URL=os.getenv("TEST_DATABASE_URL"),
        DB_POOL_SIZE=int(os.getenv("DB_POOL_SIZE", "3")),
        DB_MAX_OVERFLOW=int(os.getenv("DB_MAX_OVERFLOW", "2")),
        WORKER_ID=os.getenv("WORKER_ID", "videoops-worker"),
        WORK_LEASE_SECONDS=int(os.getenv("WORK_LEASE_SECONDS", "300")),
        WORK_POLL_INTERVAL_SECONDS=float(
            os.getenv("WORK_POLL_INTERVAL_SECONDS", "2.0")
        ),
        WORK_MAX_ATTEMPTS=int(os.getenv("WORK_MAX_ATTEMPTS", "3")),
        CHANNEL_ADMIN_ENABLED=os.getenv("CHANNEL_ADMIN_ENABLED", "false").lower()
        in {"1", "true", "yes", "on"},
        LLM_PROVIDER=os.getenv("LLM_PROVIDER", "disabled").lower(),
        LLM_MODEL=os.getenv("LLM_MODEL", ""),
        LLM_TIMEOUT_SECONDS=float(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
        LLM_MAX_OUTPUT_TOKENS=int(os.getenv("LLM_MAX_OUTPUT_TOKENS", "4096")),
        LLM_TEMPERATURE=float(os.getenv("LLM_TEMPERATURE", "0.7")),
        LLM_MAX_ATTEMPTS=int(os.getenv("LLM_MAX_ATTEMPTS", "3")),
        LLM_PROMPT_VERSION=os.getenv("LLM_PROMPT_VERSION", "story-v1"),
        OPENAI_API_KEY=os.getenv("OPENAI_API_KEY"),
        STORY_MIN_CHARACTERS=int(os.getenv("STORY_MIN_CHARACTERS", "100")),
        STORY_MAX_CHARACTERS=int(os.getenv("STORY_MAX_CHARACTERS", "20000")),
        STORY_MAX_SCENES=int(os.getenv("STORY_MAX_SCENES", "100")),
        STORY_MAX_KEYWORDS_PER_SCENE=int(
            os.getenv("STORY_MAX_KEYWORDS_PER_SCENE", "10")
        ),
        FFMPEG_BINARY=os.getenv("FFMPEG_BINARY", "ffmpeg"),
        FFPROBE_BINARY=os.getenv("FFPROBE_BINARY", "ffprobe"),
        TTS_CONNECT_TIMEOUT_SECONDS=int(os.getenv("TTS_CONNECT_TIMEOUT_SECONDS", "10")),
        TTS_RECEIVE_TIMEOUT_SECONDS=int(os.getenv("TTS_RECEIVE_TIMEOUT_SECONDS", "60")),
        STOCK_REQUEST_TIMEOUT_SECONDS=float(
            os.getenv("STOCK_REQUEST_TIMEOUT_SECONDS", "20")
        ),
        STOCK_MAX_DOWNLOAD_BYTES=int(
            os.getenv("STOCK_MAX_DOWNLOAD_BYTES", str(100 * 1024 * 1024))
        ),
        PREVIEW_RENDER_TIMEOUT_SECONDS=float(
            os.getenv("PREVIEW_RENDER_TIMEOUT_SECONDS", "300")
        ),
        PREVIEW_DURATION_TOLERANCE_MS=int(
            os.getenv("PREVIEW_DURATION_TOLERANCE_MS", "250")
        ),
        MEDIA_MIN_FREE_DISK_GB=float(os.getenv("MEDIA_MIN_FREE_DISK_GB", "0.25")),
        MEDIA_MAX_ATTEMPTS=int(os.getenv("MEDIA_MAX_ATTEMPTS", "3")),
        MEDIA_RENDER_CONCURRENCY=int(os.getenv("MEDIA_RENDER_CONCURRENCY", "1")),
        YTDLP_BINARY=os.getenv("YTDLP_BINARY", "yt-dlp"),
        REMIX_DOWNLOAD_TIMEOUT_SECONDS=float(
            os.getenv("REMIX_DOWNLOAD_TIMEOUT_SECONDS", "300")
        ),
        REMIX_MAX_DOWNLOAD_BYTES=int(
            os.getenv("REMIX_MAX_DOWNLOAD_BYTES", str(1024 * 1024 * 1024))
        ),
        REMIX_MAX_SOURCES=int(os.getenv("REMIX_MAX_SOURCES", "10")),
        REMIX_MAX_SOURCE_DURATION_SECONDS=float(
            os.getenv("REMIX_MAX_SOURCE_DURATION_SECONDS", "7200")
        ),
        REMIX_DURATION_TOLERANCE_MS=int(
            os.getenv("REMIX_DURATION_TOLERANCE_MS", "750")
        ),
        MASTER_RENDER_TIMEOUT_SECONDS=float(
            os.getenv("MASTER_RENDER_TIMEOUT_SECONDS", "900")
        ),
        MASTER_PRESET=os.getenv("MASTER_PRESET", "superfast"),
        MASTER_CRF=int(os.getenv("MASTER_CRF", "23")),
        MASTER_DURATION_TOLERANCE_MS=int(
            os.getenv("MASTER_DURATION_TOLERANCE_MS", "1000")
        ),
    )
    cfg.ensure_directories()
    return cfg
