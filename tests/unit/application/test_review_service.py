from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core.adapters.media.workspace import JobWorkspace
from core.application.review_service import ReviewService
from core.application.security import AuthorizationPolicy, Principal, Role
from core.application.views import FailureView, JobView, PublishTargetView
from core.domain.errors import DomainValidationError
from core.domain.media_models import ArtifactManifest, MediaInfo
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    TargetStatus,
    VideoMetadata,
)


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

    def list_for_revision(self, job_id, content_revision):
        return (self.manifest,)


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


def _service(tmp_path: Path, principal: Principal | None = None):
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
    return (
        ReviewService(
            workflow,
            Manifests(manifest),
            tmp_path,
            principal=principal,
            authorization=AuthorizationPolicy() if principal else None,
        ),
        workflow,
        path,
    )


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


def test_authorized_command_carries_actor_into_audit_decision(tmp_path):
    principal = Principal("reviewer-7", frozenset({Role.REVIEWER}))
    service, workflow, _ = _service(tmp_path, principal)

    service.approve(
        "job-review", 4, VideoMetadata(title="Approved"), (Platform.YOUTUBE,)
    )

    assert workflow.commands[0].actor_id == "reviewer-7"


def test_publish_recovery_commands_keep_revision_and_target_explicit(tmp_path):
    service, workflow, _ = _service(tmp_path)

    service.retry_publish("job-review", 4)
    service.skip_target("job-review", 5, Platform.YOUTUBE, "Published manually")

    retry, skip = workflow.commands
    assert retry.expected_revision == 4
    assert retry.scope.value == "PUBLISH"
    assert skip.expected_revision == 5
    assert skip.platform is Platform.YOUTUBE
    assert skip.reason == "Published manually"


def test_cancel_uses_revision_and_requires_explicit_reason(tmp_path):
    service, workflow, _ = _service(tmp_path)

    service.cancel("job-review", 4, "Operator cancelled")

    command = workflow.commands[0]
    assert command.expected_revision == 4
    assert command.reason == "Operator cancelled"


def test_refresh_rejects_corrupt_preview(tmp_path):
    service, _, path = _service(tmp_path)
    path.write_bytes(b"changed")

    with pytest.raises(DomainValidationError, match="preview file"):
        service.get("job-review")


def test_failed_tiktok_exposes_only_validated_current_master(tmp_path):
    workspace = JobWorkspace(tmp_path, "job-review", 2)
    master = workspace.final_path("master/master.mp4")
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master")
    manifest = ArtifactManifest(
        "master:2",
        "job-review",
        "MASTER",
        "master/master.mp4",
        hashlib.sha256(b"master").hexdigest(),
        6,
        2,
        datetime.now(UTC),
        MediaInfo(1_000, "h264", 1080, 1920, "mp4", True, "aac"),
    )
    view = replace(
        _view(),
        status=JobStatus.FAILED,
        preview_artifact_id=None,
        allowed_actions=("retry", "skip_target"),
        publish_targets=(
            PublishTargetView(
                Platform.TIKTOK, TargetStatus.FAILED, None, None, "TIKTOK_REJECTED"
            ),
        ),
        failure=FailureView(
            "TIKTOK_REJECTED",
            JobPhase.PUBLISH,
            "Publishing failed.",
            False,
            Platform.TIKTOK,
        ),
    )

    result = ReviewService(Workflow(view), Manifests(manifest), tmp_path).get(
        "job-review"
    )

    assert result.manual_master_path == str(master)
