"""Single-item worker runtime; heavy media handlers arrive in later modules."""

from __future__ import annotations

import asyncio
import inspect
import logging
import threading
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeVar

from core.application.events import WorkflowEvent
from core.application.ports import QueuedWork, WorkQueue
from core.application.video_workflow import WorkflowProcessor
from core.domain.models import WorkKind

logger = logging.getLogger(__name__)
T = TypeVar("T")


class WorkHandler(Protocol):
    """A side-effect boundary that turns leased work into a typed event."""

    def handle(
        self,
        work: QueuedWork,
        heartbeat: Callable[[], None],
    ) -> WorkflowEvent | Awaitable[WorkflowEvent | None] | None: ...


class Worker:
    """Claim one durable item, commit its event, then acknowledge the lease."""

    def __init__(
        self,
        *,
        worker_id: str,
        queue: WorkQueue,
        processor: WorkflowProcessor,
        handlers: Mapping[WorkKind, WorkHandler],
        lease_seconds: int = 300,
        poll_interval_seconds: float = 2.0,
        retry_base_seconds: int = 5,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._worker_id = worker_id
        self._queue = queue
        self._processor = processor
        self._handlers = dict(handlers)
        self._lease_seconds = lease_seconds
        self._poll_interval_seconds = poll_interval_seconds
        self._retry_base_seconds = retry_base_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._stop = threading.Event()
        self._async_loop: asyncio.AbstractEventLoop | None = None

    def run_coroutine(self, awaitable: Awaitable[T]) -> T:
        """Run async adapters on one persistent loop for this worker process."""
        if self._async_loop is None:
            self._async_loop = asyncio.new_event_loop()
        return self._async_loop.run_until_complete(awaitable)

    def run_once(self) -> bool:
        """Process at most one item; return whether work was claimed."""
        work = self._queue.claim_next(
            self._worker_id,
            self._lease_seconds,
            tuple(self._handlers),
        )
        if work is None:
            return False
        try:
            handler = self._handlers[work.intent.kind]
            event = handler.handle(
                work,
                lambda: self._queue.heartbeat(
                    work.work_id,
                    self._worker_id,
                    self._lease_seconds,
                ),
            )
            if inspect.isawaitable(event):
                event = self.run_coroutine(event)
            if event is not None:
                self._processor.apply(work.intent.job_id, event)
            self._queue.ack(work.work_id, self._worker_id)
        except Exception as exc:  # noqa: BLE001 - preserve leases at process boundary
            error_code = f"WORKER_{type(exc).__name__.upper()}"[:128]
            delay = self._retry_base_seconds * (2 ** max(0, work.attempts - 1))
            self._queue.retry(
                work.work_id,
                self._worker_id,
                error_code,
                self._now() + timedelta(seconds=delay),
            )
            logger.warning(
                "Work item failed and was rescheduled",
                extra={
                    "work_id": work.work_id,
                    "job_id": work.intent.job_id,
                    "error_code": error_code,
                },
            )
        return True

    def run_forever(self) -> None:
        """Recover abandoned leases and poll until graceful shutdown."""
        self._queue.recover_expired_leases(self._now())
        while not self._stop.is_set():
            if not self.run_once():
                self._stop.wait(self._poll_interval_seconds)

    def stop(self) -> None:
        self._stop.set()

    def close(self) -> None:
        """Release the worker-owned async loop after providers are closed."""
        if self._async_loop is not None:
            self._async_loop.close()
            self._async_loop = None
