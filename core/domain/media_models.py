"""Provider-neutral media values produced while building a story preview."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath
from typing import Any

from core.domain.errors import DomainValidationError

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def validate_relative_path(value: str) -> str:
    if not value or "\\" in value:
        raise DomainValidationError("Artifact path must be relative")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise DomainValidationError("Artifact path must be relative")
    return path.as_posix()


@dataclass(frozen=True, slots=True)
class SubtitleCue:
    index: int
    start_ms: int
    end_ms: int
    text: str

    def __post_init__(self) -> None:
        if self.index < 1 or self.start_ms < 0 or self.end_ms <= self.start_ms:
            raise DomainValidationError("Subtitle timing is invalid")
        clean = self.text.strip()
        if not clean:
            raise DomainValidationError("Subtitle text is required")
        object.__setattr__(self, "text", clean)


def subtitles_to_srt(cues: tuple[SubtitleCue, ...]) -> str:
    previous_end = 0
    blocks: list[str] = []
    for expected, cue in enumerate(cues, start=1):
        if cue.index != expected:
            raise DomainValidationError("Subtitle indices must be contiguous")
        if cue.start_ms < previous_end:
            raise DomainValidationError("Subtitle cues overlap")
        blocks.append(
            f"{cue.index}\n{_srt_time(cue.start_ms)} --> {_srt_time(cue.end_ms)}\n"
            f"{cue.text}"
        )
        previous_end = cue.end_ms
    if not blocks:
        raise DomainValidationError("At least one subtitle cue is required")
    return "\n\n".join(blocks) + "\n"


def _srt_time(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration_ms: int
    codec: str
    width: int | None = None
    height: int | None = None
    format_name: str | None = None
    has_audio: bool = False
    audio_codec: str | None = None

    def __post_init__(self) -> None:
        if self.duration_ms <= 0 or not self.codec.strip():
            raise DomainValidationError("Media information is invalid")
        if (self.width is None) != (self.height is None):
            raise DomainValidationError("Media dimensions are incomplete")
        if self.width is not None:
            assert self.height is not None
            if self.width <= 0 or self.height <= 0:
                raise DomainValidationError("Media dimensions are invalid")
        if self.audio_codec is not None and not self.audio_codec.strip():
            raise DomainValidationError("Audio codec is invalid")


@dataclass(frozen=True, slots=True)
class ArtifactManifest:
    artifact_id: str
    job_id: str
    artifact_type: str
    relative_path: str
    checksum: str
    byte_size: int
    content_revision: int
    created_at: datetime
    media_info: MediaInfo | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.artifact_id or not self.job_id or not self.artifact_type:
            raise DomainValidationError("Artifact identity is invalid")
        object.__setattr__(
            self, "relative_path", validate_relative_path(self.relative_path)
        )
        if not _SHA256.fullmatch(self.checksum):
            raise DomainValidationError("Artifact checksum is invalid")
        if self.byte_size <= 0 or self.content_revision < 1:
            raise DomainValidationError("Artifact size or revision is invalid")
        if self.created_at.tzinfo is None:
            raise DomainValidationError("Artifact creation time must be timezone-aware")


class VisualAssetKind(str, Enum):
    VIDEO = "VIDEO"
    IMAGE = "IMAGE"
    GENERATED_BACKGROUND = "GENERATED_BACKGROUND"


@dataclass(frozen=True, slots=True)
class VisualAsset:
    scene_order: int
    kind: VisualAssetKind
    relative_path: str | None = None
    source_provider: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    license_reference: str | None = None

    def __post_init__(self) -> None:
        if self.scene_order < 1:
            raise DomainValidationError("Visual scene order is invalid")
        if self.kind is VisualAssetKind.GENERATED_BACKGROUND:
            if self.relative_path is not None:
                raise DomainValidationError("Generated background cannot name a file")
        elif self.relative_path is None:
            raise DomainValidationError("Downloaded visual requires a relative path")
        elif self.relative_path is not None:
            object.__setattr__(
                self, "relative_path", validate_relative_path(self.relative_path)
            )


@dataclass(frozen=True, slots=True)
class PreparedScene:
    order: int
    start_ms: int
    end_ms: int
    visual: VisualAsset

    def __post_init__(self) -> None:
        if self.order != self.visual.scene_order or self.end_ms <= self.start_ms:
            raise DomainValidationError("Prepared scene timing is invalid")


@dataclass(frozen=True, slots=True)
class PreviewBundle:
    job_id: str
    content_revision: int
    artifacts: tuple[ArtifactManifest, ...]

    def __post_init__(self) -> None:
        if self.content_revision < 1 or not self.artifacts:
            raise DomainValidationError("Preview bundle is invalid")
        if any(
            item.job_id != self.job_id or item.content_revision != self.content_revision
            for item in self.artifacts
        ):
            raise DomainValidationError("Preview artifacts belong to another revision")
