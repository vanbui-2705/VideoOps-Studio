"""Retention policy that converts expired jobs into normal cancellation work."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

from core.application.commands import Cancel
from core.application.video_workflow import VideoWorkflow
from core.domain.errors import WorkflowError
from core.domain.models import JobPhase, JobStatus, TargetStatus, VideoJob


class RetentionCandidateStore(Protocol):
    def list_retention_candidates(
        self,
        draft_before: datetime,
        publish_before: datetime,
        limit: int,
    ) -> tuple[VideoJob, ...]: ...


class RetentionSweeper:
    def __init__(
        self,
        candidates: RetentionCandidateStore,
        workflow: VideoWorkflow,
        *,
        now: Callable[[], datetime] | None = None,
        draft_retention_hours: int = 6,
        publish_failure_retention_hours: int = 24,
        batch_size: int = 100,
    ) -> None:
        if (
            draft_retention_hours < 1
            or publish_failure_retention_hours < draft_retention_hours
            or batch_size < 1
        ):
            raise ValueError("Retention settings are invalid")
        self._candidates = candidates
        self._workflow = workflow
        self._now = now or (lambda: datetime.now(UTC))
        self._draft_hours = draft_retention_hours
        self._publish_hours = publish_failure_retention_hours
        self._batch_size = batch_size

    def run_once(self) -> int:
        now = self._now()
        jobs = self._candidates.list_retention_candidates(
            now - timedelta(hours=self._draft_hours),
            now - timedelta(hours=self._publish_hours),
            self._batch_size,
        )
        cancelled = 0
        for job in jobs:
            if not self._eligible(job):
                continue
            try:
                self._workflow.command(
                    job.job_id,
                    Cancel(
                        f"retention:{job.job_id}:{job.revision}",
                        job.revision,
                        "RETENTION_EXPIRED",
                    ),
                )
            except WorkflowError:
                continue
            cancelled += 1
        return cancelled

    @staticmethod
    def _eligible(job: VideoJob) -> bool:
        drafts = {
            JobStatus.QUEUED,
            JobStatus.INGESTING,
            JobStatus.RENDERING_PREVIEW,
            JobStatus.AWAITING_REVIEW,
        }
        if job.status in drafts:
            return True
        return (
            job.status is JobStatus.FAILED
            and job.phase is JobPhase.PUBLISH
            and not any(
                target.status is TargetStatus.UNKNOWN for target in job.publish_targets
            )
        )
