"""Pure state transition rules for video jobs."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from core.domain.errors import InvalidTransition
from core.domain.models import JobPhase, JobStatus, VideoJob

_ALLOWED_TRANSITIONS: dict[JobStatus, frozenset[JobStatus]] = {
    JobStatus.QUEUED: frozenset(
        {JobStatus.INGESTING, JobStatus.FAILED, JobStatus.PURGING}
    ),
    JobStatus.INGESTING: frozenset(
        {JobStatus.RENDERING_PREVIEW, JobStatus.FAILED, JobStatus.PURGING}
    ),
    JobStatus.RENDERING_PREVIEW: frozenset(
        {JobStatus.AWAITING_REVIEW, JobStatus.FAILED, JobStatus.PURGING}
    ),
    JobStatus.AWAITING_REVIEW: frozenset(
        {
            JobStatus.QUEUED,
            JobStatus.RENDERING_MASTER,
            JobStatus.FAILED,
            JobStatus.PURGING,
        }
    ),
    JobStatus.RENDERING_MASTER: frozenset({JobStatus.PUBLISHING, JobStatus.FAILED}),
    JobStatus.PUBLISHING: frozenset({JobStatus.PURGING, JobStatus.FAILED}),
    JobStatus.PURGING: frozenset(
        {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.FAILED}
    ),
    JobStatus.FAILED: frozenset(
        {
            JobStatus.QUEUED,
            JobStatus.INGESTING,
            JobStatus.RENDERING_PREVIEW,
            JobStatus.RENDERING_MASTER,
            JobStatus.PUBLISHING,
            JobStatus.PURGING,
        }
    ),
    JobStatus.COMPLETED: frozenset(),
    JobStatus.CANCELLED: frozenset(),
}


def transition(
    job: VideoJob,
    target: JobStatus,
    phase: JobPhase,
    now: datetime,
) -> VideoJob:
    """Return the next immutable snapshot or reject an illegal transition."""
    if target not in _ALLOWED_TRANSITIONS[job.status]:
        raise InvalidTransition(
            f"Cannot transition {job.status.value} to {target.value}"
        )
    return replace(
        job,
        status=target,
        phase=phase,
        revision=job.revision + 1,
        updated_at=now,
    )
