"""Dependency interfaces consumed by the workflow module."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core.domain.models import Platform, VideoJob, WorkflowDecision, WorkIntent


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
