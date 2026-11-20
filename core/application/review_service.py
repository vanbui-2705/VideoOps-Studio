"""Review Gate facade for safe UI reads and revision-aware commands."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from core.adapters.media.workspace import JobWorkspace
from core.application.commands import Approve, Regenerate, UpdateMetadata
from core.application.media_ports import ArtifactManifestStore
from core.application.video_workflow import VideoWorkflow
from core.domain.errors import DomainValidationError, UnsafeWorkspacePath
from core.domain.models import JobStatus, Platform, VideoMetadata


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


class ReviewService:
    """Expose one narrow, infrastructure-safe surface to the operator UI."""

    def __init__(
        self,
        workflow: VideoWorkflow,
        manifests: ArtifactManifestStore,
        temp_root: Path,
        *,
        command_id: Callable[[], str] | None = None,
    ) -> None:
        self._workflow = workflow
        self._manifests = manifests
        self._temp_root = Path(temp_root)
        self._command_id = command_id or (lambda: str(uuid4()))

    def get(self, job_id: str) -> ReviewView:
        """Refresh review state without issuing a workflow command."""
        view = self._workflow.get(job_id.strip())
        preview_path = self._resolve_preview(view) if view.preview_artifact_id else None
        return ReviewView(
            job_id=view.job_id,
            status=view.status,
            revision=view.revision,
            content_revision=view.content_revision,
            metadata=view.metadata,
            available_targets=view.available_targets,
            preview_path=str(preview_path) if preview_path else None,
            progress=view.progress,
        )

    def update_metadata(
        self, job_id: str, expected_revision: int, metadata: VideoMetadata
    ) -> ReviewView:
        self._workflow.command(
            job_id,
            UpdateMetadata(self._command_id(), expected_revision, metadata),
        )
        return self.get(job_id)

    def regenerate(
        self, job_id: str, expected_revision: int, changes: str
    ) -> ReviewView:
        self._workflow.command(
            job_id,
            Regenerate(self._command_id(), expected_revision, changes),
        )
        return self.get(job_id)

    def approve(
        self,
        job_id: str,
        expected_revision: int,
        metadata: VideoMetadata,
        target_platforms: tuple[Platform, ...],
    ) -> ReviewView:
        self._workflow.command(
            job_id,
            Approve(self._command_id(), expected_revision, metadata, target_platforms),
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


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
