"""Typed requests accepted by VideoWorkflow.submit."""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.errors import DomainValidationError
from core.domain.models import VideoMetadata


@dataclass(frozen=True, slots=True)
class StoryRequest:
    """Request to prepare a story from exactly one content source."""

    request_id: str
    channel_id: str
    metadata: VideoMetadata
    script: str | None = None
    prompt: str | None = None

    def __post_init__(self) -> None:
        has_script = bool(self.script and self.script.strip())
        has_prompt = bool(self.prompt and self.prompt.strip())
        if has_script == has_prompt:
            raise DomainValidationError("Provide exactly one of script or prompt")


@dataclass(frozen=True, slots=True)
class RemixClip:
    """One ordered source range in a remix request."""

    url: str
    start_seconds: float
    end_seconds: float
    order: int
    speed: float = 1.0

    def __post_init__(self) -> None:
        if not self.url.startswith(("https://", "http://")):
            raise DomainValidationError("Remix source URL must use HTTP or HTTPS")
        if self.start_seconds < 0 or self.end_seconds <= self.start_seconds:
            raise DomainValidationError("Remix clip time range is invalid")
        if self.speed <= 0:
            raise DomainValidationError("Remix clip speed must be positive")


@dataclass(frozen=True, slots=True)
class RemixRequest:
    """Request to prepare an ordered remix from remote sources."""

    request_id: str
    channel_id: str
    clips: tuple[RemixClip, ...]
    copyright_confirmed: bool
    metadata: VideoMetadata

    def __post_init__(self) -> None:
        if not self.clips:
            raise DomainValidationError("At least one remix clip is required")
        if not self.copyright_confirmed:
            raise DomainValidationError("Copyright confirmation is required")
        orders = [clip.order for clip in self.clips]
        if len(orders) != len(set(orders)):
            raise DomainValidationError("Remix clip order values must be unique")
