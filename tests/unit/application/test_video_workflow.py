"""Behavioral tests for the external VideoWorkflow interface."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.application.commands import Approve
from core.application.ports import ChannelSnapshot
from core.application.requests import RemixClip, RemixRequest, StoryRequest
from core.application.video_workflow import DefaultVideoWorkflow
from core.domain.errors import (
    ApprovalPreconditionFailed,
    DomainValidationError,
    JobNotFound,
    RevisionConflict,
)
from core.domain.models import (
    ArtifactKind,
    ArtifactRef,
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    StorySnapshot,
    VideoJob,
    VideoMetadata,
    WorkflowDecision,
    WorkIntent,
    WorkKind,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 16, 8, 0, tzinfo=UTC)


class FixedIds:
    def new_job_id(self) -> str:
        return "job-001"


class FakeChannels:
    def __init__(
        self,
        available_targets: tuple[Platform, ...] = (
            Platform.YOUTUBE,
            Platform.TIKTOK,
        ),
    ) -> None:
        self.available_targets = available_targets

    def get_snapshot(self, channel_id: str) -> ChannelSnapshot | None:
        if channel_id != "tech-vn":
            return None
        return ChannelSnapshot(
            channel_id=channel_id,
            display_name="Tech Việt Nam",
            revision=3,
            available_targets=self.available_targets,
        )


class FakeWorkflowStore:
    def __init__(self) -> None:
        self.jobs: dict[str, VideoJob] = {}
        self.request_jobs: dict[str, str] = {}
        self.initial_work: list[WorkIntent] = []
        self.command_jobs: dict[str, str] = {}

    def get_request_result(self, request_id: str) -> VideoJob | None:
        job_id = self.request_jobs.get(request_id)
        return self.jobs.get(job_id) if job_id else None

    def create(self, job: VideoJob, initial_work: WorkIntent) -> VideoJob:
        self.jobs[job.job_id] = job
        self.request_jobs[job.request_id] = job.job_id
        self.initial_work.append(initial_work)
        return job

    def get(self, job_id: str) -> VideoJob | None:
        return self.jobs.get(job_id)

    def get_command_result(self, command_id: str) -> VideoJob | None:
        job_id = self.command_jobs.get(command_id)
        return self.jobs.get(job_id) if job_id else None

    def commit(
        self,
        decision: WorkflowDecision,
        expected_revision: int,
    ) -> VideoJob:
        current = self.jobs[decision.job.job_id]
        if current.revision != expected_revision:
            raise RevisionConflict(decision.job.job_id)
        self.jobs[decision.job.job_id] = decision.job
        self.initial_work.extend(decision.work_intents)
        if decision.command_id:
            self.command_jobs[decision.command_id] = decision.job.job_id
        return decision.job


def test_story_submit_creates_queued_job_and_prepare_intent() -> None:
    store = FakeWorkflowStore()
    workflow = DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())
    request = StoryRequest(
        request_id="request-001",
        channel_id="tech-vn",
        script="Một kịch bản hợp lệ.",
        metadata=VideoMetadata(title="AI chip mới"),
    )

    view = workflow.submit(request)

    assert view.job_id == "job-001"
    assert view.status is JobStatus.QUEUED
    assert view.revision == 0
    assert len(store.initial_work) == 1
    assert store.initial_work[0].kind is WorkKind.PREPARE_STORY
    snapshot = store.jobs[view.job_id].request_snapshot
    assert isinstance(snapshot, StorySnapshot)
    assert snapshot.script == "Một kịch bản hợp lệ."


def test_repeated_request_id_returns_existing_job_without_new_work() -> None:
    store = FakeWorkflowStore()
    workflow = DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())
    request = StoryRequest(
        request_id="request-001",
        channel_id="tech-vn",
        script="Một kịch bản hợp lệ.",
        metadata=VideoMetadata(title="AI chip mới"),
    )

    first = workflow.submit(request)
    second = workflow.submit(request)

    assert second.job_id == first.job_id
    assert len(store.initial_work) == 1


def test_remix_submit_creates_prepare_remix_intent() -> None:
    store = FakeWorkflowStore()
    workflow = DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())
    request = RemixRequest(
        request_id="request-remix",
        channel_id="tech-vn",
        clips=(
            RemixClip(
                url="https://example.com/video",
                start_seconds=5,
                end_seconds=20,
                order=0,
                speed=1.0,
            ),
        ),
        copyright_confirmed=True,
        metadata=VideoMetadata(title="Remix"),
    )

    view = workflow.submit(request)

    assert view.job_type is JobType.REMIX
    assert store.initial_work[0].kind is WorkKind.PREPARE_REMIX


def test_remix_requires_copyright_confirmation() -> None:
    with pytest.raises(DomainValidationError):
        RemixRequest(
            request_id="request-remix",
            channel_id="tech-vn",
            clips=(
                RemixClip(
                    url="https://example.com/video",
                    start_seconds=0,
                    end_seconds=5,
                    order=0,
                    speed=1.0,
                ),
            ),
            copyright_confirmed=False,
            metadata=VideoMetadata(title="Remix"),
        )


@pytest.mark.parametrize(
    ("script", "prompt"),
    [(None, None), ("script", "prompt")],
)
def test_story_requires_exactly_one_content_source(
    script: str | None,
    prompt: str | None,
) -> None:
    with pytest.raises(DomainValidationError):
        StoryRequest(
            request_id="invalid-story",
            channel_id="tech-vn",
            script=script,
            prompt=prompt,
            metadata=VideoMetadata(title="Invalid"),
        )


def test_get_unknown_job_raises_typed_error() -> None:
    workflow = DefaultVideoWorkflow(
        FakeWorkflowStore(), FakeChannels(), FixedClock(), FixedIds()
    )

    with pytest.raises(JobNotFound):
        workflow.get("missing")


def test_approve_freezes_snapshot_and_is_idempotent_by_command_id() -> None:
    store = FakeWorkflowStore()
    workflow = DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())
    submitted = workflow.submit(
        StoryRequest(
            request_id="request-001",
            channel_id="tech-vn",
            script="Một kịch bản hợp lệ.",
            metadata=VideoMetadata(title="Draft"),
        )
    )
    job = store.jobs[submitted.job_id]
    store.jobs[job.job_id] = replace(
        job,
        status=JobStatus.AWAITING_REVIEW,
        phase=JobPhase.PREVIEW_RENDER,
        revision=3,
        artifacts=(
            ArtifactRef(
                artifact_id="preview-1",
                kind=ArtifactKind.PREVIEW,
                content_revision=1,
            ),
        ),
    )
    metadata = VideoMetadata(title="Bản đã duyệt", privacy="private")
    command = Approve(
        command_id="command-approve",
        expected_revision=3,
        metadata=metadata,
        target_platforms=(Platform.YOUTUBE,),
    )

    first = workflow.command(job.job_id, command)
    second = workflow.command(job.job_id, command)

    stored = store.jobs[job.job_id]
    assert first.status is JobStatus.RENDERING_MASTER
    assert first.metadata == metadata
    assert second.revision == first.revision
    assert stored.approval_snapshot is not None
    assert stored.approval_snapshot.metadata == metadata
    assert stored.publish_targets[0].platform is Platform.YOUTUBE
    assert [work.kind for work in store.initial_work].count(WorkKind.RENDER_MASTER) == 1


def test_approve_requires_current_preview() -> None:
    store = FakeWorkflowStore()
    workflow = DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())
    submitted = workflow.submit(
        StoryRequest(
            request_id="request-no-preview",
            channel_id="tech-vn",
            script="Script",
            metadata=VideoMetadata(title="Draft"),
        )
    )
    job = store.jobs[submitted.job_id]
    store.jobs[job.job_id] = replace(
        job,
        status=JobStatus.AWAITING_REVIEW,
        phase=JobPhase.PREVIEW_RENDER,
        revision=3,
    )

    with pytest.raises(ApprovalPreconditionFailed):
        workflow.command(
            job.job_id,
            Approve(
                command_id="approve-no-preview",
                expected_revision=3,
                metadata=VideoMetadata(title="Approved"),
                target_platforms=(Platform.YOUTUBE,),
            ),
        )


def test_job_view_exposes_allowed_actions_without_internal_state() -> None:
    store = FakeWorkflowStore()
    workflow = DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())
    submitted = workflow.submit(
        StoryRequest(
            request_id="request-view",
            channel_id="tech-vn",
            script="Script",
            metadata=VideoMetadata(title="Draft"),
        )
    )
    job = store.jobs[submitted.job_id]
    store.jobs[job.job_id] = replace(
        job,
        status=JobStatus.AWAITING_REVIEW,
        phase=JobPhase.PREVIEW_RENDER,
        revision=3,
        artifacts=(ArtifactRef("preview", ArtifactKind.PREVIEW, 1),),
    )

    view = workflow.get(job.job_id)

    assert view.allowed_actions == (
        "update_metadata",
        "approve",
        "regenerate",
        "cancel",
    )
    assert not hasattr(view, "artifacts")
    assert not hasattr(view, "request_snapshot")
    assert not hasattr(view, "diagnostic_ref")


def test_approve_rejects_target_without_channel_credential() -> None:
    store = FakeWorkflowStore()
    workflow = DefaultVideoWorkflow(
        store,
        FakeChannels(available_targets=()),
        FixedClock(),
        FixedIds(),
    )
    submitted = workflow.submit(
        StoryRequest(
            request_id="request-no-credential",
            channel_id="tech-vn",
            script="Script",
            metadata=VideoMetadata(title="Draft"),
        )
    )
    job = store.jobs[submitted.job_id]
    store.jobs[job.job_id] = replace(
        job,
        status=JobStatus.AWAITING_REVIEW,
        phase=JobPhase.PREVIEW_RENDER,
        revision=3,
        artifacts=(ArtifactRef("preview", ArtifactKind.PREVIEW, 1),),
    )

    with pytest.raises(ApprovalPreconditionFailed):
        workflow.command(
            job.job_id,
            Approve(
                command_id="approve-no-credential",
                expected_revision=3,
                metadata=VideoMetadata(title="Approved"),
                target_platforms=(Platform.YOUTUBE,),
            ),
        )
