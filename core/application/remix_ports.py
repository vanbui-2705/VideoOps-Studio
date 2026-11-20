"""Infrastructure-neutral contracts for remix source preparation."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from core.adapters.media.workspace import JobWorkspace
from core.domain.models import RemixClipSnapshot


class RemixSourceDownloader(Protocol):
    def download(
        self,
        url: str,
        workspace: JobWorkspace,
        relative_path: str,
        heartbeat: Callable[[], None] | None = None,
    ) -> Path: ...


class RemixClipProcessor(Protocol):
    def normalize(
        self,
        *,
        source_path: Path,
        output_path: Path,
        clip: RemixClipSnapshot,
        aspect_ratio: str,
        has_audio: bool,
        heartbeat: Callable[[], None] | None = None,
    ) -> None: ...


class RemixPreviewRenderer(Protocol):
    def render(
        self,
        *,
        clips: tuple[Path, ...],
        output_path: Path,
        aspect_ratio: str,
        bgm_path: Path | None = None,
        heartbeat: Callable[[], None] | None = None,
    ) -> None: ...
