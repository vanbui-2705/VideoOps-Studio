"""Review Gate facade for safe UI reads and revision-aware commands."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from core.adapters.media.workspace import JobWorkspace
from core.application.commands import (
    Approve,
    Cancel,
    Regenerate,
    Retry,
    RetryScope,
    SkipTarget,
    UpdateMetadata,
)
from core.application.media_ports import ArtifactManifestStore
from core.application.security import Action, AuthorizationPolicy, Principal
from core.application.video_workflow import VideoWorkflow
from core.application.views import FailureView, PublishTargetView
from core.domain.errors import DomainValidationError, UnsafeWorkspacePath
from core.domain.models import JobStatus, Platform, TargetStatus, VideoMetadata


@dataclass(frozen=True, slots=True)
class ReviewView:
    job_id: str
    status: JobStatus
    revision: int
    content_revision: int
    metadata: VideoMetadata
    available_targets: tuple[Platform, ...]
    preview_path: str | None
    progress: int
    allowed_actions: tuple[str, ...]
    publish_targets: tuple[PublishTargetView, ...]
    failure: FailureView | None
    manual_master_path: str | None


class ReviewService:
    """Expose one narrow, infrastructure-safe surface to the operator UI."""

    def __init__(
        self,
        workflow: VideoWorkflow,
        manifests: ArtifactManifestStore,
        temp_root: Path,
        *,
        command_id: Callable[[], str] | None = None,
        principal: Principal | None = None,
        authorization: AuthorizationPolicy | None = None,
    ) -> None:
        self._workflow = workflow
        self._manifests = manifests
        self._temp_root = Path(temp_root)
        self._command_id = command_id or (lambda: str(uuid4()))
        self._principal = principal
        self._authorization = authorization

    def get(self, job_id: str) -> ReviewView:
        """Refresh review state without issuing a workflow command."""
        self._require(Action.READ_JOB)
        view = self._workflow.get(job_id.strip())
        preview_path = self._resolve_preview(view) if view.preview_artifact_id else None
        manual_master = self._manual_master(view)
        return ReviewView(
            job_id=view.job_id,
            status=view.status,
            revision=view.revision,
            content_revision=view.content_revision,
            metadata=view.metadata,
            available_targets=view.available_targets,
            preview_path=str(preview_path) if preview_path else None,
            progress=view.progress,
            allowed_actions=view.allowed_actions,
            publish_targets=view.publish_targets,
            failure=view.failure,
            manual_master_path=str(manual_master) if manual_master else None,
        )

    def update_metadata(
        self, job_id: str, expected_revision: int, metadata: VideoMetadata
    ) -> ReviewView:
        self._require(Action.REVIEW_JOB)
        self._workflow.command(
            job_id,
            UpdateMetadata(
                self._command_id(),
                expected_revision,
                metadata,
                actor_id=self._actor_id(),
            ),
        )
        return self.get(job_id)

    def regenerate(
        self, job_id: str, expected_revision: int, changes: str
    ) -> ReviewView:
        self._require(Action.REVIEW_JOB)
        self._workflow.command(
            job_id,
            Regenerate(
                self._command_id(),
                expected_revision,
                changes,
                actor_id=self._actor_id(),
            ),
        )
        return self.get(job_id)

    def approve(
        self,
        job_id: str,
        expected_revision: int,
        metadata: VideoMetadata,
        target_platforms: tuple[Platform, ...],
    ) -> ReviewView:
        self._require(Action.APPROVE_JOB)
        self._workflow.command(
            job_id,
            Approve(
                self._command_id(),
                expected_revision,
                metadata,
                target_platforms,
                actor_id=self._actor_id(),
            ),
        )
        return self.get(job_id)

    def retry_publish(self, job_id: str, expected_revision: int) -> ReviewView:
        self._require(Action.RECOVER_PUBLISH)
        self._workflow.command(
            job_id,
            Retry(
                self._command_id(),
                expected_revision,
                RetryScope.PUBLISH,
                actor_id=self._actor_id(),
            ),
        )
        return self.get(job_id)

    def cancel(self, job_id: str, expected_revision: int, reason: str) -> ReviewView:
        self._require(Action.CANCEL_JOB)
        self._workflow.command(
            job_id,
            Cancel(
                self._command_id(),
                expected_revision,
                reason,
                actor_id=self._actor_id(),
            ),
        )
        return self.get(job_id)

    def skip_target(
        self,
        job_id: str,
        expected_revision: int,
        platform: Platform,
        reason: str,
    ) -> ReviewView:
        self._require(Action.RECOVER_PUBLISH)
        self._workflow.command(
            job_id,
            SkipTarget(
                self._command_id(),
                expected_revision,
                platform,
                reason,
                actor_id=self._actor_id(),
            ),
        )
        return self.get(job_id)

    def _resolve_preview(self, view) -> Path:
        manifest = self._manifests.get(view.job_id, view.preview_artifact_id)
        if (
            manifest is None
            or manifest.job_id != view.job_id
            or manifest.artifact_type != "PREVIEW"
            or manifest.content_revision != view.content_revision
        ):
            raise DomainValidationError("Current preview manifest is invalid")
        workspace = JobWorkspace(self._temp_root, view.job_id, view.content_revision)
        try:
            path = workspace.final_path(manifest.relative_path)
            if (
                not path.is_file()
                or path.stat().st_size != manifest.byte_size
                or _sha256(path) != manifest.checksum
            ):
                raise DomainValidationError("Current preview file is invalid")
            return path
        except (OSError, UnsafeWorkspacePath) as exc:
            raise DomainValidationError("Current preview file is invalid") from exc

    def _manual_master(self, view) -> Path | None:
        if view.status is not JobStatus.FAILED or not any(
            target.platform is Platform.TIKTOK
            and target.status in {TargetStatus.FAILED, TargetStatus.UNKNOWN}
            for target in view.publish_targets
        ):
            return None
        manifests = tuple(
            item
            for item in self._manifests.list_for_revision(
                view.job_id, view.content_revision
            )
            if item.artifact_type == "MASTER"
        )
        if len(manifests) != 1:
            return None
        manifest = manifests[0]
        media = manifest.media_info
        if (
            manifest.job_id != view.job_id
            or manifest.content_revision != view.content_revision
            or media is None
            or media.codec != "h264"
            or not media.has_audio
            or media.audio_codec not in {None, "aac"}
            or (media.width, media.height) not in {(1920, 1080), (1080, 1920)}
        ):
            return None
        workspace = JobWorkspace(self._temp_root, view.job_id, view.content_revision)
        try:
            path = workspace.final_path(manifest.relative_path)
            if (
                not path.is_file()
                or path.stat().st_size != manifest.byte_size
                or _sha256(path) != manifest.checksum
            ):
                return None
            return path
        except (OSError, UnsafeWorkspacePath):
            return None

    def _require(self, action: Action) -> None:
        if self._authorization is not None and self._principal is not None:
            self._authorization.require(self._principal, action)

    def _actor_id(self) -> str | None:
        return self._principal.principal_id if self._principal is not None else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
