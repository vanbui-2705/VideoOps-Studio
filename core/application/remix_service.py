"""Revision-safe orchestration for remix ingestion and preview rendering."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from core.adapters.media.workspace import JobWorkspace
from core.application.media_ports import ArtifactManifestStore, MediaProbe
from core.application.remix_ports import (
    RemixClipProcessor,
    RemixPreviewRenderer,
    RemixSourceDownloader,
)
from core.domain.channel_models import ChannelProfile
from core.domain.errors import (
    MediaConfigurationError,
    MediaInvalidOutput,
)
from core.domain.media_models import ArtifactManifest, MediaInfo, PreviewBundle
from core.domain.models import RemixSnapshot


@dataclass(frozen=True, slots=True)
class RemixMediaConfig:
    temp_root: Path
    assets_root: Path | None = None
    max_sources: int = 10
    max_source_duration_seconds: float = 7200
    duration_tolerance_ms: int = 750


@dataclass(frozen=True, slots=True)
class PrepareRemixRequest:
    job_id: str
    content_revision: int
    remix: RemixSnapshot
    channel: ChannelProfile


class RemixMediaService:
    def __init__(
        self,
        *,
        downloader: RemixSourceDownloader,
        processor: RemixClipProcessor,
        renderer: RemixPreviewRenderer,
        probe: MediaProbe,
        manifests: ArtifactManifestStore,
        config: RemixMediaConfig,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._downloader = downloader
        self._processor = processor
        self._renderer = renderer
        self._probe = probe
        self._manifests = manifests
        self._config = config
        self._now = now or (lambda: datetime.now(UTC))

    def prepare_sources(
        self,
        request: PrepareRemixRequest,
        heartbeat: Callable[[], None] | None = None,
    ) -> tuple[ArtifactManifest, ...]:
        if not request.remix.copyright_confirmed:
            raise MediaConfigurationError("Copyright confirmation is required")
        clips = tuple(sorted(request.remix.clips, key=lambda item: item.order))
        if not clips or len(clips) > self._config.max_sources:
            raise MediaConfigurationError("Remix source count is invalid")
        workspace = JobWorkspace(
            self._config.temp_root, request.job_id, request.content_revision
        )
        prepared: list[ArtifactManifest] = []
        for clip in clips:
            normalized_id = f"remix:{clip.order}:{request.content_revision}"
            cached = self._manifests.get(request.job_id, normalized_id)
            if self._valid_manifest(cached, workspace):
                assert cached is not None
                prepared.append(cached)
                continue

            source_relative = f"sources/source-{clip.order}.mp4"
            source_id = f"source:{clip.order}:{request.content_revision}"
            source_manifest = self._manifests.get(request.job_id, source_id)
            if self._valid_manifest(source_manifest, workspace):
                assert source_manifest is not None
                source_path = workspace.final_path(source_manifest.relative_path)
                source_info = source_manifest.media_info or self._probe.probe(
                    source_path
                )
            else:
                source_path = self._downloader.download(
                    clip.url, workspace, source_relative, heartbeat
                )
                source_info = self._probe.probe(source_path)
                self._validate_source(source_info, clip.end_seconds)
                source_manifest = self._save_manifest(
                    request,
                    role=f"source:{clip.order}",
                    artifact_type="VISUAL_SOURCE",
                    relative_path=source_relative,
                    path=source_path,
                    media_info=source_info,
                    metadata={
                        "role": "source",
                        "order": clip.order,
                        "source_host": urlsplit(clip.url).hostname or "",
                    },
                )
            self._validate_source(source_info, clip.end_seconds)

            normalized_relative = f"remix/clip-{clip.order}.mp4"
            partial = workspace.part_path(normalized_relative)
            try:
                self._processor.normalize(
                    source_path=source_path,
                    output_path=partial,
                    clip=clip,
                    aspect_ratio=request.channel.draft.visual.aspect_ratio,
                    has_audio=source_info.has_audio,
                    heartbeat=heartbeat,
                )
                normalized_info = self._probe.probe(partial)
                expected_duration = round(
                    (clip.end_seconds - clip.start_seconds) * 1000 / clip.speed
                )
                self._validate_normalized(
                    normalized_info,
                    expected_duration,
                    request.channel.draft.visual.aspect_ratio,
                )
                normalized_path = workspace.promote(normalized_relative)
            except Exception:
                workspace.remove_partial(normalized_relative)
                raise
            prepared.append(
                self._save_manifest(
                    request,
                    role=f"remix:{clip.order}",
                    artifact_type="VISUAL_SOURCE",
                    relative_path=normalized_relative,
                    path=normalized_path,
                    media_info=normalized_info,
                    metadata={
                        "role": "normalized",
                        "order": clip.order,
                        "source_artifact_id": source_id,
                        "crop_mode": clip.crop_mode,
                        "mirror": clip.mirror,
                        "speed": clip.speed,
                    },
                )
            )
        return tuple(prepared)

    def render_preview(
        self,
        request: PrepareRemixRequest,
        heartbeat: Callable[[], None] | None = None,
    ) -> PreviewBundle:
        workspace = JobWorkspace(
            self._config.temp_root, request.job_id, request.content_revision
        )
        preview_id = f"preview:{request.content_revision}"
        preview = self._manifests.get(request.job_id, preview_id)
        normalized = self._normalized_manifests(request, workspace)
        if self._valid_manifest(preview, workspace):
            assert preview is not None
            return PreviewBundle(
                request.job_id, request.content_revision, (*normalized, preview)
            )
        paths = tuple(workspace.final_path(item.relative_path) for item in normalized)
        relative = "preview/remix.mp4"
        partial = workspace.part_path(relative)
        try:
            self._renderer.render(
                clips=paths,
                output_path=partial,
                aspect_ratio=request.channel.draft.visual.aspect_ratio,
                bgm_path=self._bgm_path(request.channel),
                heartbeat=heartbeat,
            )
            info = self._probe.probe(partial)
            expected_duration = sum(
                item.media_info.duration_ms
                for item in normalized
                if item.media_info is not None
            )
            self._validate_normalized(
                info,
                expected_duration,
                request.channel.draft.visual.aspect_ratio,
            )
            output = workspace.promote(relative)
        except Exception:
            workspace.remove_partial(relative)
            raise
        preview = self._save_manifest(
            request,
            role="preview",
            artifact_type="PREVIEW",
            relative_path=relative,
            path=output,
            media_info=info,
            metadata={"role": "remix_preview", "clip_count": len(normalized)},
        )
        return PreviewBundle(
            request.job_id, request.content_revision, (*normalized, preview)
        )

    def _normalized_manifests(
        self, request: PrepareRemixRequest, workspace: JobWorkspace
    ) -> tuple[ArtifactManifest, ...]:
        manifests = tuple(
            sorted(
                (
                    item
                    for item in self._manifests.list_for_revision(
                        request.job_id, request.content_revision
                    )
                    if item.artifact_type == "VISUAL_SOURCE"
                    and item.metadata.get("role") == "normalized"
                ),
                key=lambda item: int(item.metadata.get("order", 0)),
            )
        )
        if len(manifests) != len(request.remix.clips) or any(
            not self._valid_manifest(item, workspace) for item in manifests
        ):
            raise MediaConfigurationError("Prepared remix clips are unavailable")
        return manifests

    def _validate_source(self, info: MediaInfo, end_seconds: float) -> None:
        if info.width is None or info.height is None:
            raise MediaInvalidOutput("Remix source requires video")
        if info.duration_ms > self._config.max_source_duration_seconds * 1000:
            raise MediaConfigurationError("Remix source duration exceeds the limit")
        if end_seconds * 1000 > info.duration_ms + self._config.duration_tolerance_ms:
            raise MediaConfigurationError("Remix clip range exceeds source duration")

    def _validate_normalized(
        self, info: Any, expected_duration_ms: int, aspect_ratio: str
    ) -> None:
        expected_size = (270, 480) if aspect_ratio == "9:16" else (854, 480)
        if (
            info.codec != "h264"
            or (info.width, info.height) != expected_size
            or not info.has_audio
            or abs(info.duration_ms - expected_duration_ms)
            > self._config.duration_tolerance_ms
        ):
            raise MediaInvalidOutput("Remix media profile is invalid")

    @staticmethod
    def _valid_manifest(
        manifest: ArtifactManifest | None, workspace: JobWorkspace
    ) -> bool:
        if manifest is None:
            return False
        path = workspace.final_path(manifest.relative_path)
        return (
            path.is_file()
            and path.stat().st_size == manifest.byte_size
            and _sha256(path) == manifest.checksum
        )

    def _save_manifest(
        self,
        request: PrepareRemixRequest,
        *,
        role: str,
        artifact_type: str,
        relative_path: str,
        path: Path,
        media_info: Any,
        metadata: dict[str, Any],
    ) -> ArtifactManifest:
        manifest = ArtifactManifest(
            artifact_id=f"{role}:{request.content_revision}",
            job_id=request.job_id,
            artifact_type=artifact_type,
            relative_path=relative_path,
            checksum=_sha256(path),
            byte_size=path.stat().st_size,
            content_revision=request.content_revision,
            created_at=self._now(),
            media_info=media_info,
            metadata=metadata,
        )
        return self._manifests.save(manifest)

    def _bgm_path(self, channel: ChannelProfile) -> Path | None:
        reference = channel.draft.audio.bgm_ref
        if not reference or self._config.assets_root is None:
            return None
        root = (self._config.assets_root / "bgm").resolve()
        candidate = (root / reference).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
        return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
