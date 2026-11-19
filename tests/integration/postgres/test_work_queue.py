from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.application.events import JobClaimed
from core.application.ports import QueueStatus
from core.application.video_workflow import DefaultWorkflowProcessor
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    VideoJob,
    VideoMetadata,
    WorkIntent,
    WorkKind,
)


def _seed(postgres_engine, *, max_attempts: int = 3):
    now = datetime.now(UTC)
    job = VideoJob(
        "job-q",
        "request-q",
        "tech-vn",
        JobType.STORY,
        JobStatus.QUEUED,
        JobPhase.SUBMIT,
        0,
        1,
        VideoMetadata(title="Queue"),
        now,
        now,
    )
    PostgresWorkflowStore(postgres_engine, default_max_attempts=max_attempts).create(
        job, WorkIntent(job.job_id, WorkKind.PREPARE_STORY, 1)
    )
    return PostgresWorkQueue(postgres_engine)


def test_two_concurrent_workers_never_claim_the_same_item(postgres_engine) -> None:
    queue = _seed(postgres_engine)

    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(
            pool.map(
                lambda worker: queue.claim_next(worker, 60), ("worker-a", "worker-b")
            )
        )

    assert sum(item is not None for item in claims) == 1


def test_retry_delays_work_and_exhaustion_moves_it_to_dead(postgres_engine) -> None:
    queue = _seed(postgres_engine, max_attempts=1)
    claimed = queue.claim_next("worker-a", 60)
    assert claimed is not None
    future = datetime.now(UTC) + timedelta(minutes=5)

    retried = queue.retry(claimed.work_id, "worker-a", "RENDER_TIMEOUT", future)

    assert retried.status is QueueStatus.DEAD
    assert retried.last_error_code == "RENDER_TIMEOUT"
    assert queue.claim_next("worker-b", 60) is None


def test_expired_lease_is_recovered_and_can_be_claimed_again(postgres_engine) -> None:
    queue = _seed(postgres_engine)
    claimed = queue.claim_next("worker-a", -1)
    assert claimed is not None

    recovered = queue.recover_expired_leases(datetime.now(UTC))
    reclaimed = queue.claim_next("worker-b", 60)

    assert recovered == 1
    assert reclaimed is not None
    assert reclaimed.work_id == claimed.work_id
    assert reclaimed.attempts == 2


def test_retry_with_attempts_remaining_is_not_claimed_before_available_at(
    postgres_engine,
) -> None:
    queue = _seed(postgres_engine, max_attempts=3)
    claimed = queue.claim_next("worker-a", 60)
    assert claimed is not None
    future = datetime.now(UTC) + timedelta(minutes=5)

    retried = queue.retry(claimed.work_id, "worker-a", "TEMPORARY", future)

    assert retried.status is QueueStatus.READY
    assert queue.claim_next("worker-b", 60) is None


def test_platform_is_part_of_the_logical_work_key(postgres_engine) -> None:
    queue = _seed(postgres_engine)
    initial = queue.claim_next("worker-a", 60)
    assert initial is not None
    queue.ack(initial.work_id, "worker-a")
    youtube = queue.enqueue(
        WorkIntent("job-q", WorkKind.PUBLISH_TARGET, 1, Platform.YOUTUBE)
    )
    tiktok = queue.enqueue(
        WorkIntent("job-q", WorkKind.PUBLISH_TARGET, 1, Platform.TIKTOK)
    )

    assert youtube.work_id != tiktok.work_id
    assert (
        queue.enqueue(
            WorkIntent("job-q", WorkKind.PUBLISH_TARGET, 1, Platform.YOUTUBE)
        ).work_id
        == youtube.work_id
    )


def test_claim_filters_out_work_kinds_the_worker_cannot_handle(postgres_engine) -> None:
    queue = _seed(postgres_engine)
    initial = queue.claim_next("setup", 60)
    assert initial is not None
    queue.ack(initial.work_id, "setup")
    render = queue.enqueue(WorkIntent("job-q", WorkKind.RENDER_PREVIEW, 1))

    assert queue.claim_next("story-worker", 60, (WorkKind.PREPARE_STORY,)) is None
    claimed = queue.claim_next("render-worker", 60, (WorkKind.RENDER_PREVIEW,))
    assert claimed is not None
    assert claimed.work_id == render.work_id


class _Clock:
    def now(self):
        return datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


class _ClaimHandler:
    def handle(self, work, heartbeat):
        return JobClaimed(expected_revision=0)


def test_worker_with_real_queue_commits_workflow_before_ack(postgres_engine) -> None:
    from core.runtime.worker import Worker

    queue = _seed(postgres_engine)
    processor = DefaultWorkflowProcessor(
        PostgresWorkflowStore(postgres_engine), _Clock()
    )
    worker = Worker(
        worker_id="worker-a",
        queue=queue,
        processor=processor,
        handlers={WorkKind.PREPARE_STORY: _ClaimHandler()},
    )

    assert worker.run_once() is True
    assert (
        PostgresWorkflowStore(postgres_engine).get("job-q").status
        is JobStatus.INGESTING
    )
