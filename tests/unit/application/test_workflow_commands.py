"""Behavioral tests for review, cancellation, and recovery commands."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.application.commands import (
    Cancel,
    Regenerate,
    Retry,
    RetryScope,
    SkipTarget,
    UpdateMetadata,
)
from core.application.ports import ChannelSnapshot
from core.application.video_workflow import DefaultVideoWorkflow
from core.domain.errors import RevisionConflict
from core.domain.models import (
    ArtifactKind,
    ArtifactRef,
    JobFailure,
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    PublishTarget,
    ResumeAction,
    TargetStatus,
    VideoJob,
    VideoMetadata,
    WorkflowDecision,
    WorkKind,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 16, 10, 0, tzinfo=UTC)


class FixedIds:
    def new_job_id(self) -> str:
        return "unused"


class FakeChannels:
    def get_snapshot(self, channel_id: str) -> ChannelSnapshot | None:
        return ChannelSnapshot(
            channel_id,
            "Channel",
            1,
            available_targets=(Platform.YOUTUBE, Platform.TIKTOK),
        )


class FakeStore:
    def __init__(self, job: VideoJob) -> None:
        self.jobs = {job.job_id: job}
        self.command_jobs: dict[str, str] = {}
        self.work: list[object] = []

    def get_request_result(self, request_id: str) -> VideoJob | None:
        return None

    def create(self, job: VideoJob, initial_work: object) -> VideoJob:
        self.jobs[job.job_id] = job
        self.work.append(initial_work)
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
        self.work.extend(decision.work_intents)
        if decision.command_id:
            self.command_jobs[decision.command_id] = decision.job.job_id
        return decision.job


def _job(status: JobStatus = JobStatus.AWAITING_REVIEW) -> VideoJob:
    now = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
    return VideoJob(
        job_id="job-1",
        request_id="request-1",
        channel_id="tech-vn",
        job_type=JobType.STORY,
        status=status,
        phase=JobPhase.PREVIEW_RENDER,
        revision=3,
        content_revision=1,
        metadata_draft=VideoMetadata(title="Draft"),
        created_at=now,
        updated_at=now,
        artifacts=(ArtifactRef("preview-1", ArtifactKind.PREVIEW, 1),),
    )


def _workflow(store: FakeStore) -> DefaultVideoWorkflow:
    return DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())


def test_metadata_update_uses_revision_and_rejects_stale_write() -> None:
    store = FakeStore(_job())
    workflow = _workflow(store)
    metadata = VideoMetadata(title="Tiêu đề mới")

    updated = workflow.command(
        "job-1",
        UpdateMetadata("metadata-1", expected_revision=3, metadata=metadata),
    )

    assert updated.metadata == metadata
    with pytest.raises(RevisionConflict):
        workflow.command(
            "job-1",
            UpdateMetadata("metadata-2", expected_revision=3, metadata=metadata),
        )


def test_regenerate_increments_content_revision_and_replaces_preview() -> None:
    store = FakeStore(_job())

    view = _workflow(store).command(
        "job-1",
        Regenerate("regen-1", expected_revision=3, changes="Đổi tone"),
    )

    assert view.status is JobStatus.QUEUED
    assert view.content_revision == 2
    assert store.jobs["job-1"].artifacts == ()
    assert store.jobs["job-1"].regeneration_instructions == ("Đổi tone",)
    assert store.work[-1].kind is WorkKind.PREPARE_STORY


def test_cancel_schedules_purge_and_marks_cancelled_outcome() -> None:
    store = FakeStore(_job(JobStatus.QUEUED))

    view = _workflow(store).command(
        "job-1",
        Cancel("cancel-1", expected_revision=3, reason="Người dùng hủy"),
    )

    assert view.status is JobStatus.PURGING
    assert store.jobs["job-1"].terminal_after_purge is JobStatus.CANCELLED
    assert store.work[-1].kind is WorkKind.PURGE_JOB


def test_publish_retry_reconciles_unknown_and_does_not_repeat_success() -> None:
    failure = JobFailure(
        code="PUBLISH_UNKNOWN",
        phase=JobPhase.PUBLISH,
        message_safe="Cần kiểm tra trạng thái nền tảng.",
        retryable=True,
        resume_action=ResumeAction.PUBLISH,
    )
    job = replace(
        _job(JobStatus.FAILED),
        phase=JobPhase.PUBLISH,
        failure=failure,
        publish_targets=(
            PublishTarget(Platform.YOUTUBE, TargetStatus.SUCCEEDED),
            PublishTarget(Platform.TIKTOK, TargetStatus.UNKNOWN),
        ),
    )
    store = FakeStore(job)

    view = _workflow(store).command(
        "job-1",
        Retry("retry-1", expected_revision=3, scope=RetryScope.PUBLISH),
    )

    assert view.status is JobStatus.PUBLISHING
    assert len(store.work) == 1
    assert store.work[0].kind is WorkKind.RECONCILE_TARGET
    assert store.work[0].platform is Platform.TIKTOK


def test_skipping_last_failed_target_moves_job_to_purge() -> None:
    job = replace(
        _job(JobStatus.FAILED),
        phase=JobPhase.PUBLISH,
        publish_targets=(
            PublishTarget(Platform.YOUTUBE, TargetStatus.SUCCEEDED),
            PublishTarget(Platform.TIKTOK, TargetStatus.FAILED),
        ),
    )
    store = FakeStore(job)

    view = _workflow(store).command(
        "job-1",
        SkipTarget(
            "skip-1",
            expected_revision=3,
            platform=Platform.TIKTOK,
            reason="Đăng thủ công",
        ),
    )

    assert view.status is JobStatus.PURGING
    assert store.jobs["job-1"].publish_targets[1].skip_reason == "Đăng thủ công"
    assert store.work[-1].kind is WorkKind.PURGE_JOB
