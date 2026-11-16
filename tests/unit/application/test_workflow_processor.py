"""Behavioral tests for trusted worker events."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.application.events import (
    IngestionCompleted,
    JobClaimed,
    MasterRendered,
    PreviewRendered,
    PurgeCompleted,
    StepFailed,
    TargetPublishSucceeded,
    TargetPublishUnknown,
)
from core.application.video_workflow import DefaultWorkflowProcessor
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
        return datetime(2026, 11, 16, 9, 0, tzinfo=UTC)


class FakeProcessorStore:
    def __init__(self, job: VideoJob) -> None:
        self.jobs = {job.job_id: job}
        self.work: list[object] = []

    def get(self, job_id: str) -> VideoJob | None:
        return self.jobs.get(job_id)

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
        return decision.job


def _queued_job() -> VideoJob:
    now = datetime(2026, 11, 16, 8, 0, tzinfo=UTC)
    return VideoJob(
        job_id="job-001",
        request_id="request-001",
        channel_id="tech-vn",
        job_type=JobType.STORY,
        status=JobStatus.QUEUED,
        phase=JobPhase.SUBMIT,
        revision=0,
        content_revision=1,
        metadata_draft=VideoMetadata(title="Story"),
        created_at=now,
        updated_at=now,
    )


def test_worker_events_advance_job_to_review_with_preview_reference() -> None:
    store = FakeProcessorStore(_queued_job())
    processor = DefaultWorkflowProcessor(store, FixedClock())

    claimed = processor.apply("job-001", JobClaimed(expected_revision=0))
    ingested = processor.apply("job-001", IngestionCompleted(expected_revision=1))
    reviewed = processor.apply(
        "job-001",
        PreviewRendered(
            expected_revision=2,
            artifact_id="preview-1",
            content_revision=1,
        ),
    )

    assert claimed.status is JobStatus.INGESTING
    assert ingested.status is JobStatus.RENDERING_PREVIEW
    assert store.work[-1].kind is WorkKind.RENDER_PREVIEW
    assert reviewed.status is JobStatus.AWAITING_REVIEW
    assert reviewed.preview_artifact_id == "preview-1"
    assert store.jobs["job-001"].artifacts[0].kind is ArtifactKind.PREVIEW
    assert store.jobs["job-001"].revision == 3


def test_master_render_schedules_each_pending_publish_target() -> None:
    job = replace(
        _queued_job(),
        status=JobStatus.RENDERING_MASTER,
        phase=JobPhase.MASTER_RENDER,
        revision=4,
        publish_targets=(
            PublishTarget(Platform.YOUTUBE),
            PublishTarget(Platform.TIKTOK),
        ),
    )
    store = FakeProcessorStore(job)

    view = DefaultWorkflowProcessor(store, FixedClock()).apply(
        job.job_id,
        MasterRendered(expected_revision=4, artifact_id="master-1"),
    )

    assert view.status is JobStatus.PUBLISHING
    assert [intent.kind for intent in store.work] == [
        WorkKind.PUBLISH_TARGET,
        WorkKind.PUBLISH_TARGET,
    ]
    assert [intent.platform for intent in store.work] == [
        Platform.YOUTUBE,
        Platform.TIKTOK,
    ]
    assert store.jobs[job.job_id].artifacts[-1].kind is ArtifactKind.MASTER


def test_all_publish_targets_succeeded_schedules_purge() -> None:
    job = replace(
        _queued_job(),
        status=JobStatus.PUBLISHING,
        phase=JobPhase.PUBLISH,
        revision=5,
        publish_targets=(
            PublishTarget(Platform.YOUTUBE),
            PublishTarget(Platform.TIKTOK),
        ),
        artifacts=(ArtifactRef("master-1", ArtifactKind.MASTER, 1),),
    )
    store = FakeProcessorStore(job)
    processor = DefaultWorkflowProcessor(store, FixedClock())

    first = processor.apply(
        job.job_id,
        TargetPublishSucceeded(
            expected_revision=5,
            platform=Platform.YOUTUBE,
            external_video_id="yt-1",
            public_url="https://youtube.example/yt-1",
        ),
    )
    second = processor.apply(
        job.job_id,
        TargetPublishSucceeded(
            expected_revision=6,
            platform=Platform.TIKTOK,
            external_video_id="tt-1",
            public_url="https://tiktok.example/tt-1",
        ),
    )

    assert first.status is JobStatus.PUBLISHING
    assert second.status is JobStatus.PURGING
    assert store.work[-1].kind is WorkKind.PURGE_JOB


def test_unknown_publish_result_preserves_master_and_requires_reconcile() -> None:
    job = replace(
        _queued_job(),
        status=JobStatus.PUBLISHING,
        phase=JobPhase.PUBLISH,
        revision=5,
        publish_targets=(PublishTarget(Platform.YOUTUBE),),
        artifacts=(ArtifactRef("master-1", ArtifactKind.MASTER, 1),),
    )
    store = FakeProcessorStore(job)

    view = DefaultWorkflowProcessor(store, FixedClock()).apply(
        job.job_id,
        TargetPublishUnknown(
            expected_revision=5,
            platform=Platform.YOUTUBE,
            diagnostic_ref="diag-1",
        ),
    )

    stored = store.jobs[job.job_id]
    assert view.status is JobStatus.FAILED
    assert stored.publish_targets[0].status is TargetStatus.UNKNOWN
    assert stored.failure is not None
    assert stored.failure.resume_action is ResumeAction.PUBLISH
    assert stored.artifacts[0].artifact_id == "master-1"


def test_purge_only_finishes_when_no_media_bytes_remain() -> None:
    purging = replace(
        _queued_job(),
        status=JobStatus.PURGING,
        phase=JobPhase.PURGE,
        revision=7,
        terminal_after_purge=JobStatus.CANCELLED,
    )
    successful_store = FakeProcessorStore(purging)
    failed_store = FakeProcessorStore(purging)

    completed = DefaultWorkflowProcessor(successful_store, FixedClock()).apply(
        purging.job_id,
        PurgeCompleted(expected_revision=7, media_bytes=0),
    )
    failed = DefaultWorkflowProcessor(failed_store, FixedClock()).apply(
        purging.job_id,
        PurgeCompleted(expected_revision=7, media_bytes=128),
    )

    assert completed.status is JobStatus.CANCELLED
    assert failed.status is JobStatus.FAILED
    assert failed_store.jobs[purging.job_id].failure is not None
    assert failed_store.jobs[purging.job_id].failure.resume_action is ResumeAction.PURGE


def test_step_failure_records_sanitized_retry_policy() -> None:
    failure = JobFailure(
        code="RENDER_TIMEOUT",
        phase=JobPhase.PREVIEW_RENDER,
        message_safe="Preview render timed out.",
        retryable=True,
        resume_action=ResumeAction.PREVIEW,
        diagnostic_ref="diag-render-1",
    )
    job = replace(
        _queued_job(),
        status=JobStatus.RENDERING_PREVIEW,
        phase=JobPhase.PREVIEW_RENDER,
        revision=2,
    )
    store = FakeProcessorStore(job)

    view = DefaultWorkflowProcessor(store, FixedClock()).apply(
        job.job_id,
        StepFailed(expected_revision=2, failure=failure),
    )

    assert view.status is JobStatus.FAILED
    assert store.jobs[job.job_id].failure == failure
