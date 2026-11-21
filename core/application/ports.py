"""Dependency interfaces consumed by the workflow module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from core.application.events import WorkflowEvent
from core.domain.models import (
    Platform,
    VideoJob,
    WorkflowDecision,
    WorkIntent,
    WorkKind,
)


@dataclass(frozen=True, slots=True)
class ChannelSnapshot:
    """Safe channel identity captured when a job is submitted."""

    channel_id: str
    display_name: str
    revision: int
    available_targets: tuple[Platform, ...] = ()


class WorkflowStore(Protocol):
    """Atomic persistence seam implemented by Module 3."""

    def get_request_result(self, request_id: str) -> VideoJob | None: ...

    def create(self, job: VideoJob, initial_work: WorkIntent) -> VideoJob: ...

    def get(self, job_id: str) -> VideoJob | None: ...

    def get_command_result(self, command_id: str) -> VideoJob | None: ...

    def commit(
        self,
        decision: WorkflowDecision,
        expected_revision: int,
    ) -> VideoJob: ...


class ChannelReader(Protocol):
    """Read-only channel seam used at submission time."""

    def get_snapshot(self, channel_id: str) -> ChannelSnapshot | None: ...


class Clock(Protocol):
    """Deterministic source of UTC timestamps."""

    def now(self) -> datetime: ...


class IdGenerator(Protocol):
    """Deterministic source of job identifiers."""

    def new_job_id(self) -> str: ...


class QueueStatus(str, Enum):
    """Infrastructure-neutral lifecycle of one durable work item."""

    READY = "READY"
    CLAIMED = "CLAIMED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD = "DEAD"


@dataclass(frozen=True, slots=True)
class QueuedWork:
    """Safe queue projection consumed by a worker runtime."""

    work_id: str
    intent: WorkIntent
    status: QueueStatus
    attempts: int
    max_attempts: int
    available_at: datetime
    lease_owner: str | None = None
    lease_until: datetime | None = None
    last_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class DeferredWork:
    """Ask a worker to persist an optional event and retry the lease later."""

    event: WorkflowEvent | None
    retry_at: datetime
    error_code: str


class WorkQueue(Protocol):
    """Durable queue seam implemented by Module 3."""

    def enqueue(self, intent: WorkIntent, max_attempts: int = 3) -> QueuedWork: ...

    def get(self, work_id: str) -> QueuedWork | None: ...

    def claim_next(
        self,
        worker_id: str,
        lease_seconds: int,
        supported_kinds: tuple[WorkKind, ...] | None = None,
    ) -> QueuedWork | None: ...

    def heartbeat(
        self, work_id: str, worker_id: str, lease_seconds: int
    ) -> QueuedWork: ...

    def ack(self, work_id: str, worker_id: str) -> QueuedWork: ...

    def retry(
        self,
        work_id: str,
        worker_id: str,
        error_code: str,
        available_at: datetime,
    ) -> QueuedWork: ...

    def mark_dead(
        self, work_id: str, worker_id: str, error_code: str
    ) -> QueuedWork: ...

    def recover_expired_leases(self, now: datetime) -> int: ...
