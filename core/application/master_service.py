"""Revision-safe orchestration for approved 1080p master rendering."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from core.adapters.media.workspace import JobWorkspace
from core.application.master_ports import MasterRenderer
from core.application.media_ports import ArtifactManifestStore, MediaProbe
from core.domain.channel_models import ChannelProfile
from core.domain.errors import (
    MediaConfigurationError,
    MediaInvalidOutput,
    UnsafeWorkspacePath,
)
from core.domain.media_models import (
    ArtifactManifest,
    MediaInfo,
    PreparedScene,
    VisualAsset,
    VisualAssetKind,
)
from core.domain.models import (
    JobStatus,
    JobType,
    RemixClipSnapshot,
    RemixSnapshot,
    VideoJob,
)


@dataclass(frozen=True, slots=True)
class MasterRenderConfig:
    temp_root: Path
    assets_root: Path | None = None
    duration_tolerance_ms: int = 1_000
    preset: str = "superfast"
    crf: int = 23

    def __post_init__(self) -> None:
        if (
            self.duration_tolerance_ms < 0
            or self.preset not in {"superfast"}
            or not 0 <= self.crf <= 51
        ):
            raise MediaConfigurationError("Master render configuration is invalid")


@dataclass(frozen=True, slots=True)
class MasterRenderRequest:
    job: VideoJob
    channel: ChannelProfile


class MasterRenderService:
    """Hide artifact selection, reuse, composition, and validation behind one call."""

    def __init__(
        self,
        *,
        renderer: MasterRenderer,
        probe: MediaProbe,
        manifests: ArtifactManifestStore,
        config: MasterRenderConfig,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._renderer = renderer
        self._probe = probe
        self._manifests = manifests
        self._config = config
        self._now = now or (lambda: datetime.now(UTC))

    def render(
        self,
        request: MasterRenderRequest,
        heartbeat: Callable[[], None] | None = None,
    ) -> ArtifactManifest:
        job = request.job
        approval = job.approval_snapshot
        if job.status is not JobStatus.RENDERING_MASTER or approval is None:
            raise MediaConfigurationError("Job is not approved for master rendering")
        if (
            approval.content_revision != job.content_revision
            or approval.channel_revision != job.channel_revision
            or request.channel.revision != job.channel_revision
        ):
            raise MediaConfigurationError("Approved master revision is invalid")

        workspace = JobWorkspace(
            self._config.temp_root, job.job_id, job.content_revision
        )
        master_id = f"master:{job.content_revision}"
        cached = self._manifests.get(job.job_id, master_id)
        expected_duration = self._expected_duration(request, workspace)
        if (
            cached is not None
            and cached.content_revision == job.content_revision
            and self._valid_master(
                cached,
                workspace,
                request.channel.draft.visual.aspect_ratio,
                expected_duration,
            )
        ):
            assert cached is not None
            return cached

        relative_path = "master/master.mp4"
        partial = workspace.part_path(relative_path)
        workspace.remove_partial(relative_path)
        try:
            if job.job_type is JobType.STORY:
                self._render_story(request, workspace, partial, heartbeat)
            else:
                self._render_remix(request, workspace, partial, heartbeat)
            info = self._probe.probe(partial)
            self._validate_master(
                info,
                request.channel.draft.visual.aspect_ratio,
                expected_duration,
            )
            output = workspace.promote(relative_path)
        except Exception:
            workspace.remove_partial(relative_path)
            raise

        manifest = ArtifactManifest(
            artifact_id=master_id,
            job_id=job.job_id,
            artifact_type="MASTER",
            relative_path=relative_path,
            checksum=_sha256(output),
            byte_size=output.stat().st_size,
            content_revision=job.content_revision,
            created_at=self._now(),
            media_info=info,
            metadata={
                "role": "master",
                "job_type": job.job_type.value,
                "channel_revision": job.channel_revision,
            },
        )
        return self._manifests.save(manifest)

    def _render_story(
        self,
        request: MasterRenderRequest,
        workspace: JobWorkspace,
        output_path: Path,
        heartbeat: Callable[[], None] | None,
    ) -> None:
        job = request.job
        story = job.prepared_story
        if story is None:
            raise MediaConfigurationError("Prepared story is unavailable")
        voice = self._required_manifest(
            job, f"voice:{job.content_revision}", "VOICE", workspace
        )
        subtitle = self._required_manifest(
            job, f"subtitle:{job.content_revision}", "SUBTITLE", workspace
        )
        voice_info = voice.media_info
        if voice_info is None:
            voice_info = self._probe.probe(workspace.final_path(voice.relative_path))
        timings = _scene_timings(story, voice_info.duration_ms)
        scenes: list[PreparedScene] = []
        source_paths: list[Path] = []
        for scene, (start_ms, end_ms) in zip(story.scenes, timings):
            manifest = self._required_manifest(
                job,
                f"visual:{scene.order}:{job.content_revision}",
                "VISUAL_SOURCE",
                workspace,
            )
            try:
                kind = VisualAssetKind(manifest.metadata["kind"])
            except (KeyError, ValueError) as exc:
                raise MediaConfigurationError(
                    "Story visual metadata is invalid"
                ) from exc
            visual = VisualAsset(
                scene.order,
                kind,
                None
                if kind is VisualAssetKind.GENERATED_BACKGROUND
                else manifest.relative_path,
            )
            scenes.append(PreparedScene(scene.order, start_ms, end_ms, visual))
            source_paths.append(workspace.final_path(manifest.relative_path))

        self._renderer.render_story(
            voice_path=workspace.final_path(voice.relative_path),
            subtitle_path=workspace.final_path(subtitle.relative_path),
            scenes=tuple(scenes),
            source_paths=tuple(source_paths),
            output_path=output_path,
            aspect_ratio=request.channel.draft.visual.aspect_ratio,
            subtitle_style=request.channel.draft.visual.subtitle_style,
            bgm_path=self._bgm_path(request.channel),
            workspace_root=workspace.root,
            preset=self._config.preset,
            crf=self._config.crf,
            heartbeat=heartbeat,
        )

    def _render_remix(
        self,
        request: MasterRenderRequest,
        workspace: JobWorkspace,
        output_path: Path,
        heartbeat: Callable[[], None] | None,
    ) -> None:
        job = request.job
        snapshot = job.request_snapshot
        if not isinstance(snapshot, RemixSnapshot) or not snapshot.clips:
            raise MediaConfigurationError("Approved Remix snapshot is unavailable")
        sources: list[tuple[Path, RemixClipSnapshot, bool]] = []
        for clip in sorted(snapshot.clips, key=lambda item: item.order):
            manifest = self._required_manifest(
                job,
                f"source:{clip.order}:{job.content_revision}",
                "VISUAL_SOURCE",
                workspace,
            )
            info = manifest.media_info or self._probe.probe(
                workspace.final_path(manifest.relative_path)
            )
            if (
                info.width is None
                or info.height is None
                or clip.end_seconds * 1000
                > info.duration_ms + self._config.duration_tolerance_ms
            ):
                raise MediaConfigurationError("Approved Remix source is invalid")
            sources.append(
                (
                    workspace.final_path(manifest.relative_path),
                    clip,
                    info.has_audio,
                )
            )
        self._renderer.render_remix(
            sources=tuple(sources),
            output_path=output_path,
            aspect_ratio=request.channel.draft.visual.aspect_ratio,
            bgm_path=self._bgm_path(request.channel),
            preset=self._config.preset,
            crf=self._config.crf,
            heartbeat=heartbeat,
        )

    def _expected_duration(
        self, request: MasterRenderRequest, workspace: JobWorkspace
    ) -> int:
        job = request.job
        if job.job_type is JobType.STORY:
            voice = self._required_manifest(
                job, f"voice:{job.content_revision}", "VOICE", workspace
            )
            info = voice.media_info or self._probe.probe(
                workspace.final_path(voice.relative_path)
            )
            return info.duration_ms
        snapshot = job.request_snapshot
        if not isinstance(snapshot, RemixSnapshot) or not snapshot.clips:
            raise MediaConfigurationError("Approved Remix snapshot is unavailable")
        return sum(
            round((clip.end_seconds - clip.start_seconds) * 1000 / clip.speed)
            for clip in snapshot.clips
        )

    def _required_manifest(
        self,
        job: VideoJob,
        artifact_id: str,
        artifact_type: str,
        workspace: JobWorkspace,
    ) -> ArtifactManifest:
        manifest = self._manifests.get(job.job_id, artifact_id)
        if not self._valid_manifest(manifest, workspace):
            raise MediaConfigurationError("Approved source artifact is unavailable")
        assert manifest is not None
        if (
            manifest.content_revision != job.content_revision
            or manifest.artifact_type != artifact_type
        ):
            raise MediaConfigurationError("Approved source revision is invalid")
        return manifest

    def _valid_master(
        self,
        manifest: ArtifactManifest | None,
        workspace: JobWorkspace,
        aspect_ratio: str,
        expected_duration_ms: int,
    ) -> bool:
        if not self._valid_manifest(manifest, workspace):
            return False
        assert manifest is not None
        info = manifest.media_info
        if info is None:
            info = self._probe.probe(workspace.final_path(manifest.relative_path))
        try:
            self._validate_master(info, aspect_ratio, expected_duration_ms)
        except MediaInvalidOutput:
            return False
        return manifest.artifact_type == "MASTER"

    @staticmethod
    def _valid_manifest(
        manifest: ArtifactManifest | None, workspace: JobWorkspace
    ) -> bool:
        if manifest is None:
            return False
        try:
            path = workspace.final_path(manifest.relative_path)
            return (
                path.is_file()
                and path.stat().st_size == manifest.byte_size
                and _sha256(path) == manifest.checksum
            )
        except (OSError, UnsafeWorkspacePath):
            return False

    def _validate_master(
        self, info: MediaInfo, aspect_ratio: str, expected_duration_ms: int
    ) -> None:
        expected_size = (1080, 1920) if aspect_ratio == "9:16" else (1920, 1080)
        if (
            info.codec != "h264"
            or (info.width, info.height) != expected_size
            or not info.has_audio
            or info.audio_codec not in {None, "aac"}
            or abs(info.duration_ms - expected_duration_ms)
            > self._config.duration_tolerance_ms
        ):
            raise MediaInvalidOutput("Master media profile is invalid")

    def _bgm_path(self, channel: ChannelProfile) -> Path | None:
        reference = channel.draft.audio.bgm_ref
        if not reference or self._config.assets_root is None:
            return None
        root = (self._config.assets_root / "bgm").resolve()
        candidate = (root / reference).resolve()
        if candidate.is_relative_to(root) and candidate.is_file():
            return candidate
        return None


def _scene_timings(story, duration_ms: int) -> tuple[tuple[int, int], ...]:
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
