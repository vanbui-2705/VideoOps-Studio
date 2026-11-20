from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.adapters.media.workspace import JobWorkspace
from core.application.review_service import ReviewService
from core.application.views import JobView
from core.domain.errors import DomainValidationError
from core.domain.media_models import ArtifactManifest
from core.domain.models import JobPhase, JobStatus, JobType, Platform, VideoMetadata


class Workflow:
    def __init__(self, view: JobView) -> None:
        self.view = view
        self.commands = []

    def get(self, job_id):
        assert job_id == self.view.job_id
        return self.view

    def command(self, job_id, command):
        self.commands.append(command)
        self.view = replace(self.view, revision=self.view.revision + 1)
        return self.view


class Manifests:
    def __init__(self, manifest):
        self.manifest = manifest

    def get(self, job_id, artifact_id):
        return self.manifest


def _view() -> JobView:
    return JobView(
        job_id="job-review",
        channel_id="channel",
        job_type=JobType.STORY,
        status=JobStatus.AWAITING_REVIEW,
        phase=JobPhase.PREVIEW_RENDER,
        revision=4,
        content_revision=2,
        metadata=VideoMetadata(title="Title"),
        allowed_actions=("APPROVE",),
        preview_artifact_id="preview:2",
        available_targets=(Platform.YOUTUBE,),
        publish_targets=(),
        failure=None,
        progress=60,
    )


def _service(tmp_path: Path):
    workspace = JobWorkspace(tmp_path, "job-review", 2)
    path = workspace.final_path("preview/preview.mp4")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"preview")
    manifest = ArtifactManifest(
        artifact_id="preview:2",
        job_id="job-review",
        artifact_type="PREVIEW",
        relative_path="preview/preview.mp4",
        checksum=hashlib.sha256(b"preview").hexdigest(),
        byte_size=7,
        content_revision=2,
        created_at=datetime.now(UTC),
    )
    workflow = Workflow(_view())
    return ReviewService(workflow, Manifests(manifest), tmp_path), workflow, path


def test_refresh_is_read_only_and_returns_validated_current_preview(tmp_path):
    service, workflow, path = _service(tmp_path)

    result = service.get("job-review")

    assert result.preview_path == str(path)
    assert result.available_targets == (Platform.YOUTUBE,)
    assert workflow.commands == []


def test_approve_uses_revision_metadata_and_selected_targets(tmp_path):
    service, workflow, _ = _service(tmp_path)
    metadata = VideoMetadata(title="Approved")

    service.approve("job-review", 4, metadata, (Platform.YOUTUBE,))

    command = workflow.commands[0]
    assert command.expected_revision == 4
    assert command.metadata == metadata
    assert command.target_platforms == (Platform.YOUTUBE,)


def test_refresh_rejects_corrupt_preview(tmp_path):
    service, _, path = _service(tmp_path)
    path.write_bytes(b"changed")

    with pytest.raises(DomainValidationError, match="preview file"):
        service.get("job-review")
