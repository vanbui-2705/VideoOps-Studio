from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from core.application.events import JobClaimed
from core.application.ports import QueuedWork, QueueStatus
from core.domain.models import WorkIntent, WorkKind
from core.runtime.worker import Worker


class FakeQueue:
    def __init__(self, work: QueuedWork) -> None:
        self.work = work
        self.acked = False
        self.retried = False
        self.heartbeat_count = 0
        self.supported_kinds = None

    def claim_next(self, worker_id: str, lease_seconds: int, supported_kinds=None):
        self.supported_kinds = supported_kinds
        work, self.work = self.work, None
        return work

    def heartbeat(self, work_id: str, worker_id: str, lease_seconds: int):
        self.heartbeat_count += 1

    def ack(self, work_id: str, worker_id: str):
        self.acked = True

    def retry(self, work_id, worker_id, error_code, available_at):
        self.retried = True
        self.error_code = error_code
        self.available_at = available_at

    def recover_expired_leases(self, now):
        return 0


class ClaimHandler:
    def handle(self, work, heartbeat):
        heartbeat()
        return JobClaimed(expected_revision=0)


class AsyncClaimHandler:
    async def handle(self, work, heartbeat):
        heartbeat()
        return JobClaimed(expected_revision=0)


class ObsoleteHandler:
    async def handle(self, work, heartbeat):
        return None


class FakeProcessor:
    def __init__(self, fails: bool = False) -> None:
        self.fails = fails
        self.applied = False

    def apply(self, job_id, event):
        self.applied = True
        if self.fails:
            raise RuntimeError("database unavailable with password=secret")


def _work() -> QueuedWork:
    now = datetime(2026, 11, 16, 10, 0, tzinfo=UTC)
    return QueuedWork(
        "work-1",
        WorkIntent("job-1", WorkKind.PREPARE_STORY, 1),
        QueueStatus.CLAIMED,
        1,
        3,
        now,
        "worker-a",
        now,
    )


def test_worker_commits_event_before_acknowledging_work() -> None:
    queue = FakeQueue(_work())
    processor = FakeProcessor()
    worker = Worker(
        worker_id="worker-a",
        queue=queue,
        processor=processor,
        handlers={WorkKind.PREPARE_STORY: ClaimHandler()},
    )

    assert worker.run_once() is True
    assert processor.applied is True
    assert queue.heartbeat_count == 1
    assert queue.acked is True
    assert queue.retried is False
    assert queue.supported_kinds == (WorkKind.PREPARE_STORY,)


def test_workflow_commit_failure_retries_without_leaking_exception_message() -> None:
    queue = FakeQueue(_work())
    worker = Worker(
        worker_id="worker-a",
        queue=queue,
        processor=FakeProcessor(fails=True),
        handlers={WorkKind.PREPARE_STORY: ClaimHandler()},
        now=lambda: datetime(2026, 11, 16, 10, 0, tzinfo=UTC),
    )

    worker.run_once()

    assert queue.acked is False
    assert queue.retried is True
    assert queue.error_code == "WORKER_RUNTIMEERROR"
    assert "secret" not in queue.error_code


def test_worker_runs_async_handler_at_one_runtime_boundary() -> None:
    queue = FakeQueue(_work())
    processor = FakeProcessor()
    worker = Worker(
        worker_id="worker-a",
        queue=queue,
        processor=processor,
        handlers={WorkKind.PREPARE_STORY: AsyncClaimHandler()},
    )

    assert worker.run_once() is True
    assert processor.applied is True
    assert queue.acked is True


def test_worker_acknowledges_obsolete_work_without_applying_an_event() -> None:
    queue = FakeQueue(_work())
    processor = FakeProcessor()
    worker = Worker(
        worker_id="worker-a",
        queue=queue,
        processor=processor,
        handlers={WorkKind.PREPARE_STORY: ObsoleteHandler()},
    )

    assert worker.run_once() is True
    assert processor.applied is False
    assert queue.acked is True


def test_worker_reuses_one_event_loop_for_async_clients() -> None:
    worker = Worker(
        worker_id="worker-a",
        queue=FakeQueue(_work()),
        processor=FakeProcessor(),
        handlers={WorkKind.PREPARE_STORY: AsyncClaimHandler()},
    )

    async def loop_id():
        return id(asyncio.get_running_loop())

    try:
        assert worker.run_coroutine(loop_id()) == worker.run_coroutine(loop_id())
    finally:
        worker.close()
