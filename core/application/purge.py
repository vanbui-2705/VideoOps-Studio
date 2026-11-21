"""Deep application module for audited, verified zero-retention cleanup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from core.application.events import PurgeCompleted, StepFailed, WorkflowEvent
from core.application.ports import DeferredWork, QueuedWork, WorkflowStore
from core.domain.models import (
    JobFailure,
    JobPhase,
    JobStatus,
    ResumeAction,
    TargetStatus,
    VideoJob,
    WorkKind,
)


@dataclass(frozen=True, slots=True)
class PurgeResult:
    deleted_files: int
    remaining_bytes: int

    def __post_init__(self) -> None:
        if self.deleted_files < 0 or self.remaining_bytes < 0:
            raise ValueError("Purge result cannot be negative")


class Purger(Protocol):
    def purge(
        self,
        job_id: str,
        content_revision: int,
        heartbeat: Callable[[], None] | None = None,
    ) -> PurgeResult: ...


class PurgeAuditStore(Protocol):
    def ensure_purge_snapshot(self, job: VideoJob, now: datetime) -> None: ...


class PurgeCoordinator:
    def __init__(
        self,
        workflow_store: WorkflowStore,
        audit: PurgeAuditStore,
        purger: Purger,
        *,
        now: Callable[[], datetime] | None = None,
        retry_base_seconds: int = 5,
    ) -> None:
        if retry_base_seconds < 1:
            raise ValueError("Purge retry delay must be positive")
        self._workflow_store = workflow_store
        self._audit = audit
        self._purger = purger
        self._now = now or (lambda: datetime.now(UTC))
        self._retry_base_seconds = retry_base_seconds

    def execute(
        self, work: QueuedWork, heartbeat: Callable[[], None]
    ) -> WorkflowEvent | DeferredWork | None:
        job = self._workflow_store.get(work.intent.job_id)
        if (
            job is None
            or work.intent.kind is not WorkKind.PURGE_JOB
            or job.status is not JobStatus.PURGING
            or job.content_revision != work.intent.content_revision
        ):
            return None
        if not self._eligible(job):
            return self._failure(job.revision, "PURGE_POLICY", False)

        now = self._now()
        self._audit.ensure_purge_snapshot(job, now)
        result = self._purger.purge(
            job.job_id,
            job.content_revision,
            heartbeat=heartbeat,
        )
        if result.remaining_bytes == 0:
            return PurgeCompleted(job.revision, 0)
        if work.attempts >= work.max_attempts:
            return self._failure(job.revision, "PURGE_INCOMPLETE", True)
        delay = self._retry_base_seconds * (2 ** max(0, work.attempts - 1))
        return DeferredWork(
            None,
            now + timedelta(seconds=delay),
            "PURGE_INCOMPLETE",
        )

    @staticmethod
    def _eligible(job: VideoJob) -> bool:
        if job.terminal_after_purge is JobStatus.CANCELLED:
            return True
        return bool(job.publish_targets) and all(
            target.status in {TargetStatus.SUCCEEDED, TargetStatus.SKIPPED}
            for target in job.publish_targets
        )

    @staticmethod
    def _failure(revision: int, code: str, retryable: bool) -> StepFailed:
        return StepFailed(
            revision,
            JobFailure(
                code=code,
                phase=JobPhase.PURGE,
                message_safe="Media cleanup is incomplete and requires attention.",
                retryable=retryable,
                resume_action=ResumeAction.PURGE,
            ),
        )
