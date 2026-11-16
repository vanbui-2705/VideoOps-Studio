"""Core data models and type definitions for NewVideo_Push."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class JobStatus(str, Enum):
    """Lifecycle status of a video production job."""

    IDLE = "IDLE"
    INGESTING = "INGESTING"
    RENDERING_PREVIEW = "RENDERING_PREVIEW"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    RENDERING_MASTER = "RENDERING_MASTER"
    PUBLISHING = "PUBLISHING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass
class VideoMetadata:
    """Publishing metadata for social platforms."""

    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    privacy: str = "public"  # "public", "unlisted", "private"
    category_id: str = "28"  # 28: Science & Technology


@dataclass
class VideoJob:
    """Represents a discrete video generation and publishing task."""

    job_id: str
    channel_id: str
    status: JobStatus = JobStatus.IDLE
    aspect_ratio: str = "16:9"  # "16:9" or "9:16"
    metadata: VideoMetadata = field(default_factory=VideoMetadata)
    preview_path: str | None = None
    master_path: str | None = None
    temp_files: list[str] = field(default_factory=list)
    published_urls: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
