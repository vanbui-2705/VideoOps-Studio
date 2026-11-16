"""Behavioral tests for the video job state machine."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.domain.errors import InvalidTransition
from core.domain.models import JobPhase, JobStatus, JobType, VideoJob, VideoMetadata
from core.domain.state_machine import transition


def _queued_job() -> VideoJob:
    now = datetime(2026, 11, 16, tzinfo=UTC)
    return VideoJob(
        job_id="job-1",
        request_id="request-1",
        channel_id="tech-vn",
        job_type=JobType.STORY,
        status=JobStatus.QUEUED,
        phase=JobPhase.SUBMIT,
        revision=0,
        content_revision=1,
        metadata_draft=VideoMetadata(title="Draft"),
        created_at=now,
        updated_at=now,
    )


def test_queued_job_can_be_claimed_for_ingestion() -> None:
    job = _queued_job()
    now = replace(job).updated_at

    updated = transition(job, JobStatus.INGESTING, JobPhase.INGEST, now)

    assert updated.status is JobStatus.INGESTING
    assert updated.phase is JobPhase.INGEST
    assert updated.revision == 1


def test_terminal_job_rejects_new_transition() -> None:
    job = replace(_queued_job(), status=JobStatus.COMPLETED)

    with pytest.raises(InvalidTransition):
        transition(
            job,
            JobStatus.QUEUED,
            JobPhase.SUBMIT,
            job.updated_at,
        )


@pytest.mark.parametrize(
    ("source", "target"),
    [
        (JobStatus.QUEUED, JobStatus.COMPLETED),
        (JobStatus.AWAITING_REVIEW, JobStatus.PUBLISHING),
        (JobStatus.PUBLISHING, JobStatus.COMPLETED),
        (JobStatus.PURGING, JobStatus.PUBLISHING),
    ],
)
def test_unsafe_shortcuts_are_rejected(
    source: JobStatus,
    target: JobStatus,
) -> None:
    job = replace(_queued_job(), status=source)

    with pytest.raises(InvalidTransition):
        transition(job, target, JobPhase.PUBLISH, job.updated_at)
