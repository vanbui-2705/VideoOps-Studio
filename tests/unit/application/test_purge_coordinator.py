from datetime import UTC, datetime, timedelta

from core.application.events import PurgeCompleted
from core.application.ports import DeferredWork, QueuedWork, QueueStatus
from core.application.purge import PurgeCoordinator, PurgeResult
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    PublishTarget,
    TargetStatus,
    VideoJob,
    VideoMetadata,
    WorkIntent,
    WorkKind,
)

NOW = datetime(2026, 11, 21, 9, tzinfo=UTC)


class Store:
    def __init__(self, job):
        self.job = job

    def get(self, job_id):
        return self.job if self.job.job_id == job_id else None


class Audit:
    def __init__(self):
        self.recorded = False

    def ensure_purge_snapshot(self, job, now):
        self.recorded = True


class Purger:
    def __init__(self, audit, remaining_bytes=0):
        self.audit = audit
        self.remaining_bytes = remaining_bytes
        self.calls = 0

    def purge(self, job_id, content_revision, heartbeat=None):
        assert self.audit.recorded is True
        self.calls += 1
        return PurgeResult(1, self.remaining_bytes)


def _job():
    return VideoJob(
        "job-purge",
        "request-purge",
        "tech_vn",
        JobType.STORY,
        JobStatus.PURGING,
        JobPhase.PURGE,
        8,
        1,
        VideoMetadata(title="Approved"),
        NOW,
        NOW,
        publish_targets=(
            PublishTarget(
                Platform.YOUTUBE,
                TargetStatus.SUCCEEDED,
                "yt-1",
                "https://www.youtube.com/watch?v=yt-1",
            ),
        ),
    )


def _work(attempts=1, max_attempts=3):
    return QueuedWork(
        "work-purge",
        WorkIntent("job-purge", WorkKind.PURGE_JOB, 1),
        QueueStatus.CLAIMED,
        attempts,
        max_attempts,
        NOW,
    )


def test_purge_coordinator_commits_audit_before_deleting_and_verifies_zero_bytes():
    audit = Audit()
    purger = Purger(audit)
    coordinator = PurgeCoordinator(Store(_job()), audit, purger, now=lambda: NOW)

    event = coordinator.execute(_work(), lambda: None)

    assert event == PurgeCompleted(8, 0)
    assert purger.calls == 1


def test_purge_coordinator_defers_incomplete_deletion_without_completing_job():
    audit = Audit()
    coordinator = PurgeCoordinator(
        Store(_job()),
        audit,
        Purger(audit, remaining_bytes=10),
        now=lambda: NOW,
        retry_base_seconds=5,
    )

    result = coordinator.execute(_work(), lambda: None)

    assert result == DeferredWork(None, NOW + timedelta(seconds=5), "PURGE_INCOMPLETE")


def test_purge_coordinator_ignores_obsolete_non_purging_job():
    job = _job()
    job = VideoJob(
        job.job_id,
        job.request_id,
        job.channel_id,
        job.job_type,
        JobStatus.COMPLETED,
        job.phase,
        job.revision,
        job.content_revision,
        job.metadata_draft,
        job.created_at,
        job.updated_at,
    )
    audit = Audit()
    purger = Purger(audit)

    result = PurgeCoordinator(Store(job), audit, purger).execute(_work(), lambda: None)

    assert result is None
    assert audit.recorded is False
    assert purger.calls == 0
