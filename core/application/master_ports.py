"""Infrastructure-neutral contracts for approved master rendering."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from core.domain.channel_models import SubtitleStyle
from core.domain.media_models import PreparedScene
from core.domain.models import RemixClipSnapshot


class MasterRenderer(Protocol):
    def render_story(
        self,
        *,
        voice_path: Path,
        subtitle_path: Path,
        scenes: tuple[PreparedScene, ...],
        source_paths: tuple[Path, ...],
        output_path: Path,
        aspect_ratio: str,
        subtitle_style: SubtitleStyle,
        bgm_path: Path | None,
        workspace_root: Path,
        preset: str,
        crf: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> None: ...

    def render_remix(
        self,
        *,
        sources: tuple[tuple[Path, RemixClipSnapshot, bool], ...],
        output_path: Path,
        aspect_ratio: str,
        bgm_path: Path | None,
        preset: str,
        crf: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> None: ...
