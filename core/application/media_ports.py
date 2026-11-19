"""Infrastructure-neutral media contracts used by preview preparation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from core.domain.errors import DomainValidationError
from core.domain.media_models import (
    ArtifactManifest,
    MediaInfo,
    PreparedScene,
    PreviewBundle,
    SubtitleCue,
)


@dataclass(frozen=True, slots=True)
class TtsRequest:
    narration: str
    voice: str
    rate_percent: int

    def __post_init__(self) -> None:
        if not self.narration.strip() or not self.voice.strip():
            raise DomainValidationError("TTS request is invalid")
        if not -50 <= self.rate_percent <= 100:
            raise DomainValidationError("TTS rate is invalid")


@dataclass(frozen=True, slots=True)
class TtsResult:
    audio_bytes: bytes
    cues: tuple[SubtitleCue, ...]
    file_extension: str = "mp3"

    def __post_init__(self) -> None:
        if not self.audio_bytes or not self.cues:
            raise DomainValidationError("TTS result is empty")
        if self.file_extension not in {"mp3", "wav"}:
            raise DomainValidationError("TTS audio format is unsupported")


class TtsProvider(Protocol):
    async def synthesize(self, request: TtsRequest) -> TtsResult: ...


@dataclass(frozen=True, slots=True)
class StockSearchRequest:
    keywords: tuple[str, ...]
    aspect_ratio: str
    scene_order: int

    def __post_init__(self) -> None:
        if not self.keywords or self.aspect_ratio not in {"16:9", "9:16"}:
            raise DomainValidationError("Stock search request is invalid")
        if self.scene_order < 1:
            raise DomainValidationError("Stock scene order is invalid")


@dataclass(frozen=True, slots=True)
class StockCandidate:
    provider: str
    provider_id: str
    download_url: str
    source_url: str
    license_reference: str
    media_type: str
    width: int
    height: int

    def __post_init__(self) -> None:
        parsed = urlparse(self.download_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise DomainValidationError("Stock download URL is invalid")
        for value in (self.source_url, self.license_reference):
            public = urlparse(value)
            if public.scheme != "https" or not public.hostname or public.query:
                raise DomainValidationError("Stock provenance URL is invalid")
        if self.media_type not in {"video/mp4", "image/jpeg", "image/png"}:
            raise DomainValidationError("Stock media type is invalid")
        if self.width <= 0 or self.height <= 0:
            raise DomainValidationError("Stock dimensions are invalid")


class StockMediaProvider(Protocol):
    async def search(self, request: StockSearchRequest) -> StockCandidate | None: ...


class MediaProbe(Protocol):
    def probe(self, path: Path) -> MediaInfo: ...


class PreviewRenderer(Protocol):
    def render(
        self,
        *,
        voice_path: Path,
        subtitle_path: Path,
        scenes: tuple[PreparedScene, ...],
        output_path: Path,
        aspect_ratio: str,
        subtitle_style: object,
        bgm_path: Path | None,
        workspace_root: Path | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> None: ...


class ArtifactManifestStore(Protocol):
    def get(self, job_id: str, artifact_id: str) -> ArtifactManifest | None: ...

    def save(self, manifest: ArtifactManifest) -> ArtifactManifest: ...

    def list_for_revision(
        self, job_id: str, content_revision: int
    ) -> tuple[ArtifactManifest, ...]: ...


class PreviewPreparation(Protocol):
    async def prepare(self, *args, **kwargs) -> PreviewBundle: ...
