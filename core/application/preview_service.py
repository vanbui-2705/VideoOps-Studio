"""Idempotent orchestration for story voice, visuals, and preview rendering."""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core.adapters.media.workspace import JobWorkspace
from core.application.media_ports import (
    ArtifactManifestStore,
    MediaProbe,
    PreviewRenderer,
    StockMediaProvider,
    StockSearchRequest,
    TtsProvider,
    TtsRequest,
)
from core.domain.channel_models import ChannelProfile
from core.domain.errors import MediaInvalidOutput, MediaPreparationError
from core.domain.media_models import (
    ArtifactManifest,
    PreparedScene,
    PreviewBundle,
    VisualAsset,
    VisualAssetKind,
    subtitles_to_srt,
)
from core.domain.story_models import ScriptDraft


@dataclass(frozen=True, slots=True)
class PreviewPreparationConfig:
    temp_root: Path
    duration_tolerance_ms: int = 250
    assets_root: Path | None = None
    max_attempts: int = 3


@dataclass(frozen=True, slots=True)
class PreparePreviewRequest:
    job_id: str
    content_revision: int
    story: ScriptDraft
    channel: ChannelProfile


class PreviewPreparationService:
    def __init__(
        self,
        *,
        tts: TtsProvider,
        stock_providers: tuple[StockMediaProvider, ...],
        downloader: Any,
        probe: MediaProbe,
        renderer: PreviewRenderer,
        manifests: ArtifactManifestStore,
        config: PreviewPreparationConfig,
        now: Callable[[], datetime] | None = None,
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._tts = tts
        self._stock = stock_providers
        self._downloader = downloader
        self._probe = probe
        self._renderer = renderer
        self._manifests = manifests
        self._config = config
        self._now = now or (lambda: datetime.now(UTC))
        self._sleeper = sleeper

    async def prepare(
        self,
        request: PreparePreviewRequest,
        heartbeat: Callable[[], None] | None = None,
    ) -> PreviewBundle:
        workspace = JobWorkspace(
            self._config.temp_root,
            request.job_id,
            request.content_revision,
        )
        cached = self._valid_cached_bundle(request, workspace)
        if cached is not None:
            return cached

        voice_relative = "voice/narration.mp3"
        subtitle_relative = "subtitles/narration.srt"
        voice_manifest = self._manifests.get(
            request.job_id, f"voice:{request.content_revision}"
        )
        subtitle_manifest = self._manifests.get(
            request.job_id, f"subtitle:{request.content_revision}"
        )
        if self._valid_manifest(voice_manifest, workspace) and self._valid_manifest(
            subtitle_manifest, workspace
        ):
            assert voice_manifest is not None and subtitle_manifest is not None
            voice_path = workspace.final_path(voice_manifest.relative_path)
            subtitle_path = workspace.final_path(subtitle_manifest.relative_path)
            voice_info = voice_manifest.media_info or self._probe.probe(voice_path)
        else:
            tts_result = await self._synthesize_with_retry(
                TtsRequest(
                    request.story.narration,
                    request.channel.draft.audio.voice,
                    request.channel.draft.audio.rate_percent,
                ),
                heartbeat,
            )
            if heartbeat:
                heartbeat()
            voice_relative = f"voice/narration.{tts_result.file_extension}"
            voice_path = _write_atomic(
                workspace, voice_relative, tts_result.audio_bytes
            )
            voice_info = self._probe.probe(voice_path)
            voice_manifest = self._save_manifest(
                request,
                "voice",
                "VOICE",
                voice_relative,
                voice_path,
                media_info=voice_info,
                metadata={"provider": type(self._tts).__name__},
            )
            subtitle_bytes = subtitles_to_srt(tts_result.cues).encode("utf-8")
            subtitle_path = _write_atomic(workspace, subtitle_relative, subtitle_bytes)
            subtitle_manifest = self._save_manifest(
                request,
                "subtitle",
                "SUBTITLE",
                subtitle_relative,
                subtitle_path,
                metadata={"cue_count": len(tts_result.cues), "encoding": "utf-8"},
            )

        timings = _scene_timings(request.story, voice_info.duration_ms)
        prepared_scenes: list[PreparedScene] = []
        visual_manifests: list[ArtifactManifest] = []
        seen_sources: set[tuple[str, str]] = set()
        for scene, (start_ms, end_ms) in zip(request.story.scenes, timings):
            keywords = tuple(
                dict.fromkeys(
                    (
                        *scene.visual_keywords,
                        *request.channel.draft.visual.stock_keywords,
                    )
                )
            )
            visual, manifest = await self._prepare_visual(
                request,
                workspace,
                scene.order,
                keywords,
                seen_sources,
                heartbeat,
            )
            prepared_scenes.append(PreparedScene(scene.order, start_ms, end_ms, visual))
            visual_manifests.append(manifest)
            if heartbeat:
                heartbeat()

        preview_relative = "preview/preview.mp4"
        preview_partial = workspace.part_path(preview_relative)
        try:
            self._renderer.render(
                voice_path=voice_path,
                subtitle_path=subtitle_path,
                scenes=tuple(prepared_scenes),
                output_path=preview_partial,
                aspect_ratio=request.channel.draft.visual.aspect_ratio,
                subtitle_style=request.channel.draft.visual.subtitle_style,
                bgm_path=self._bgm_path(request.channel),
                workspace_root=workspace.root,
                heartbeat=heartbeat,
            )
            preview_info = self._probe.probe(preview_partial)
            _validate_preview(
                preview_info,
                voice_info.duration_ms,
                request.channel.draft.visual.aspect_ratio,
                self._config.duration_tolerance_ms,
            )
            preview_path = workspace.promote(preview_relative)
        except Exception:
            workspace.remove_partial(preview_relative)
            raise
        preview_manifest = self._save_manifest(
            request,
            "preview",
            "PREVIEW",
            preview_relative,
            preview_path,
            media_info=preview_info,
        )
        artifacts = tuple(
            sorted(
                (
                    voice_manifest,
                    subtitle_manifest,
                    *visual_manifests,
                    preview_manifest,
                ),
                key=lambda item: item.artifact_id,
            )
        )
        return PreviewBundle(request.job_id, request.content_revision, artifacts)

    async def _synthesize_with_retry(self, request, heartbeat):
        attempts = max(1, self._config.max_attempts)
        for attempt in range(1, attempts + 1):
            try:
                return await self._tts.synthesize(request)
            except MediaPreparationError as exc:
                if not exc.retryable or attempt >= attempts:
                    raise
                if heartbeat:
                    heartbeat()
                await self._sleeper(float(2 ** (attempt - 1)))
        raise AssertionError("TTS retry loop did not terminate")

    def _valid_cached_bundle(
        self, request: PreparePreviewRequest, workspace: JobWorkspace
    ) -> PreviewBundle | None:
        manifests = self._manifests.list_for_revision(
            request.job_id, request.content_revision
        )
        types = {item.artifact_type for item in manifests}
        required = {"VOICE", "SUBTITLE", "VISUAL_SOURCE", "PREVIEW"}
        if not required.issubset(types):
            return None
        expected_ids = {
            f"voice:{request.content_revision}",
            f"subtitle:{request.content_revision}",
            f"preview:{request.content_revision}",
            *(
                f"visual:{scene.order}:{request.content_revision}"
                for scene in request.story.scenes
            ),
        }
        if not expected_ids.issubset({item.artifact_id for item in manifests}):
            return None
        for manifest in manifests:
            if not self._valid_manifest(manifest, workspace):
                return None
        return PreviewBundle(
            request.job_id,
            request.content_revision,
            tuple(sorted(manifests, key=lambda item: item.artifact_id)),
        )

    async def _prepare_visual(
        self,
        request: PreparePreviewRequest,
        workspace: JobWorkspace,
        scene_order: int,
        keywords: tuple[str, ...],
        seen_sources: set[tuple[str, str]],
        heartbeat: Callable[[], None] | None,
    ) -> tuple[VisualAsset, ArtifactManifest]:
        role = f"visual:{scene_order}"
        cached = self._manifests.get(
            request.job_id, f"{role}:{request.content_revision}"
        )
        if self._valid_manifest(cached, workspace):
            assert cached is not None
            kind = VisualAssetKind(cached.metadata["kind"])
            return (
                VisualAsset(
                    scene_order,
                    kind,
                    None
                    if kind is VisualAssetKind.GENERATED_BACKGROUND
                    else cached.relative_path,
                    cached.metadata.get("provider"),
                    cached.metadata.get("provider_id"),
                    cached.metadata.get("source_url"),
                    cached.metadata.get("license_reference"),
                ),
                cached,
            )
        candidate = None
        for provider in self._ordered_stock(request.channel):
            try:
                found = await self._search_stock_with_retry(
                    provider,
                    StockSearchRequest(
                        keywords,
                        request.channel.draft.visual.aspect_ratio,
                        scene_order,
                    ),
                    heartbeat,
                )
            except MediaPreparationError:
                continue
            if (
                found is not None
                and (found.provider, found.provider_id) not in seen_sources
            ):
                candidate = found
                seen_sources.add((found.provider, found.provider_id))
                break
        if candidate is None:
            relative = f"visuals/scene-{scene_order}.generated.json"
            payload = json.dumps(
                {"kind": "GENERATED_BACKGROUND", "scene_order": scene_order},
                sort_keys=True,
            ).encode("utf-8")
            path = _write_atomic(workspace, relative, payload)
            visual = VisualAsset(scene_order, VisualAssetKind.GENERATED_BACKGROUND)
            manifest = self._save_manifest(
                request,
                role,
                "VISUAL_SOURCE",
                relative,
                path,
                metadata={"kind": visual.kind.value},
            )
            return visual, manifest

        extension = "mp4" if candidate.media_type == "video/mp4" else "jpg"
        relative = f"visuals/scene-{scene_order}.{extension}"
        try:
            path = await self._downloader.download(
                candidate.download_url, workspace, relative
            )
            media_info = self._probe.probe(path)
        except MediaPreparationError:
            return await self._generated_visual(request, workspace, scene_order, role)
        visual = VisualAsset(
            scene_order,
            VisualAssetKind.VIDEO
            if candidate.media_type == "video/mp4"
            else VisualAssetKind.IMAGE,
            relative,
            candidate.provider,
            candidate.provider_id,
            candidate.source_url,
            candidate.license_reference,
        )
        manifest = self._save_manifest(
            request,
            role,
            "VISUAL_SOURCE",
            relative,
            path,
            media_info=media_info,
            metadata={
                "kind": visual.kind.value,
                "provider": candidate.provider,
                "provider_id": candidate.provider_id,
                "source_url": candidate.source_url,
                "license_reference": candidate.license_reference,
            },
        )
        return visual, manifest

    async def _search_stock_with_retry(self, provider, request, heartbeat):
        attempts = max(1, self._config.max_attempts)
        for attempt in range(1, attempts + 1):
            try:
                return await provider.search(request)
            except MediaPreparationError as exc:
                if not exc.retryable or attempt >= attempts:
                    raise
                if heartbeat:
                    heartbeat()
                await self._sleeper(float(2 ** (attempt - 1)))
        raise AssertionError("Stock retry loop did not terminate")

    def _ordered_stock(self, channel: ChannelProfile):
        preferences = tuple(
            value.casefold()
            for value in channel.draft.visual.stock_provider_preferences
        )
        positions = {name: index for index, name in enumerate(preferences)}
        return tuple(
            sorted(
                self._stock,
                key=lambda provider: positions.get(
                    str(getattr(provider, "name", "")).casefold(),
                    len(positions),
                ),
            )
        )

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

    async def _generated_visual(
        self,
        request: PreparePreviewRequest,
        workspace: JobWorkspace,
        scene_order: int,
        role: str,
    ) -> tuple[VisualAsset, ArtifactManifest]:
        relative = f"visuals/scene-{scene_order}.generated.json"
        path = _write_atomic(
            workspace,
            relative,
            json.dumps(
                {"kind": "GENERATED_BACKGROUND", "scene_order": scene_order},
                sort_keys=True,
            ).encode("utf-8"),
        )
        visual = VisualAsset(scene_order, VisualAssetKind.GENERATED_BACKGROUND)
        return visual, self._save_manifest(
            request,
            role,
            "VISUAL_SOURCE",
            relative,
            path,
            metadata={"kind": visual.kind.value},
        )

    def _save_manifest(
        self,
        request: PreparePreviewRequest,
        role: str,
        artifact_type: str,
        relative_path: str,
        path: Path,
        *,
        media_info=None,
        metadata: dict[str, Any] | None = None,
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
            metadata=metadata or {},
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


def _write_atomic(workspace: JobWorkspace, relative_path: str, content: bytes) -> Path:
    partial = workspace.part_path(relative_path)
    try:
        partial.write_bytes(content)
        return workspace.promote(relative_path)
    except Exception:
        workspace.remove_partial(relative_path)
        raise


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _scene_timings(story: ScriptDraft, duration_ms: int) -> tuple[tuple[int, int], ...]:
    weights = [max(1, len(scene.narration)) for scene in story.scenes]
    total_weight = sum(weights)
    timings: list[tuple[int, int]] = []
    start = 0
    accumulated = 0
    for index, weight in enumerate(weights):
        accumulated += weight
        end = (
            duration_ms
            if index == len(weights) - 1
            else round(duration_ms * accumulated / total_weight)
        )
        timings.append((start, max(start + 1, end)))
        start = end
    return tuple(timings)


def _validate_preview(
    info,
    voice_duration_ms: int,
    aspect_ratio: str,
    tolerance_ms: int,
) -> None:
    expected = (270, 480) if aspect_ratio == "9:16" else (854, 480)
    if info.codec != "h264" or (info.width, info.height) != expected:
        raise MediaInvalidOutput("Preview profile is invalid")
    if info.duration_ms + tolerance_ms < voice_duration_ms:
        raise MediaInvalidOutput("Preview does not cover the voice track")
