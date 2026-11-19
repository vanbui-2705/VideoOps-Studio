from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.application.ports import QueueStatus
from core.domain.errors import RevisionConflict
from core.domain.models import (
    ApprovalSnapshot,
    ArtifactKind,
    ArtifactRef,
    JobFailure,
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    PublishTarget,
    RemixClipSnapshot,
    RemixSnapshot,
    ResumeAction,
    StorySnapshot,
    TargetStatus,
    VideoJob,
    VideoMetadata,
    WorkflowDecision,
    WorkIntent,
    WorkKind,
)


def _job(job_id: str = "job-1", request_id: str = "request-1") -> VideoJob:
    now = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)
    return VideoJob(
        job_id=job_id,
        request_id=request_id,
        channel_id="tech-vn",
        job_type=JobType.STORY,
        status=JobStatus.QUEUED,
        phase=JobPhase.SUBMIT,
        revision=0,
        content_revision=1,
        metadata_draft=VideoMetadata(title="Story"),
        created_at=now,
        updated_at=now,
        request_snapshot=StorySnapshot(script="Nội dung", prompt=None),
    )


def _work(job: VideoJob) -> WorkIntent:
    return WorkIntent(job.job_id, WorkKind.PREPARE_STORY, job.content_revision)


def test_create_round_trips_and_deduplicates_request_and_initial_work(
    postgres_engine,
) -> None:
    store = PostgresWorkflowStore(postgres_engine)
    queue = PostgresWorkQueue(postgres_engine)
    original = _job()

    first = store.create(original, _work(original))
    duplicate = _job("job-other", original.request_id)
    second = store.create(duplicate, _work(duplicate))

    assert store.get(first.job_id) == original
    assert second == original
    claimed = queue.claim_next("worker-a", 60)
    assert claimed is not None
    assert claimed.intent.job_id == original.job_id
    assert queue.claim_next("worker-b", 60) is None


def test_create_rolls_back_job_when_initial_work_is_invalid(postgres_engine) -> None:
    store = PostgresWorkflowStore(postgres_engine)
    job = _job()
    wrong_work = WorkIntent("missing-job", WorkKind.PREPARE_STORY, 1)

    with pytest.raises(IntegrityError):
        store.create(job, wrong_work)

    assert store.get(job.job_id) is None


def test_commit_is_revision_checked_and_command_idempotent(postgres_engine) -> None:
    store = PostgresWorkflowStore(postgres_engine)
    job = _job()
    store.create(job, _work(job))
    updated = replace(
        job,
        status=JobStatus.INGESTING,
        phase=JobPhase.INGEST,
        revision=1,
        updated_at=datetime(2026, 11, 16, 9, 1, tzinfo=UTC),
    )
    decision = WorkflowDecision(
        updated,
        (WorkIntent(job.job_id, WorkKind.RENDER_PREVIEW, 1),),
        "command-1",
    )

    first = store.commit(decision, expected_revision=0)
    second = store.commit(decision, expected_revision=0)

    assert first == second == updated
    with pytest.raises(RevisionConflict):
        store.commit(
            WorkflowDecision(replace(updated, revision=2)),
            expected_revision=0,
        )


def test_concurrent_duplicate_command_commits_once(postgres_engine) -> None:
    store = PostgresWorkflowStore(postgres_engine)
    job = _job()
    store.create(job, _work(job))
    updated = replace(
        job,
        status=JobStatus.INGESTING,
        phase=JobPhase.INGEST,
        revision=1,
        updated_at=datetime(2026, 11, 16, 9, 1, tzinfo=UTC),
    )
    decision = WorkflowDecision(updated, command_id="command-race")

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: store.commit(decision, 0), range(2)))

    assert results == [updated, updated]
    assert store.get(job.job_id) == updated


def test_concurrent_duplicate_request_creates_one_job_and_one_work_item(
    postgres_engine,
) -> None:
    store = PostgresWorkflowStore(postgres_engine)
    jobs = (_job("job-a", "request-race"), _job("job-b", "request-race"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda job: store.create(job, _work(job)), jobs))

    assert results[0].job_id == results[1].job_id
    queue = PostgresWorkQueue(postgres_engine)
    assert queue.claim_next("worker-a", 60) is not None
    assert queue.claim_next("worker-b", 60) is None


def test_queue_projection_does_not_expose_database_or_secret_fields(
    postgres_engine,
) -> None:
    store = PostgresWorkflowStore(postgres_engine)
    queue = PostgresWorkQueue(postgres_engine)
    job = _job()
    store.create(job, _work(job))

    claimed = queue.claim_next("worker-a", 60)

    assert claimed is not None
    assert claimed.status is QueueStatus.CLAIMED
    assert not hasattr(claimed, "aggregate_snapshot")
    assert not hasattr(claimed, "database_url")


def test_complex_remix_approval_failure_artifacts_and_targets_round_trip(
    postgres_engine,
) -> None:
    store = PostgresWorkflowStore(postgres_engine)
    now = datetime(2026, 11, 16, 11, 0, tzinfo=UTC)
    metadata = VideoMetadata(title="Remix approved", tags=("one", "two"))
    job = VideoJob(
        "job-remix",
        "request-remix",
        "tech-vn",
        JobType.REMIX,
        JobStatus.FAILED,
        JobPhase.PUBLISH,
        5,
        2,
        metadata,
        now,
        now,
        artifacts=(ArtifactRef("master-r2", ArtifactKind.MASTER, 2),),
        channel_revision=3,
        approval_snapshot=ApprovalSnapshot(2, 3, metadata, (Platform.YOUTUBE,), now),
        publish_targets=(
            PublishTarget(
                Platform.YOUTUBE,
                TargetStatus.UNKNOWN,
                last_error_code="PUBLISH_UNKNOWN",
            ),
        ),
        failure=JobFailure(
            "PUBLISH_UNKNOWN",
            JobPhase.PUBLISH,
            "Cần đối soát.",
            True,
            ResumeAction.PUBLISH,
            target_platform=Platform.YOUTUBE,
        ),
        request_snapshot=RemixSnapshot(
            (RemixClipSnapshot("https://example.test/video", 0, 5, 0, 1),),
            True,
        ),
    )

    store.create(
        job, WorkIntent(job.job_id, WorkKind.RECONCILE_TARGET, 2, Platform.YOUTUBE)
    )

    assert store.get(job.job_id) == job
