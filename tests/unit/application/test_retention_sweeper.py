from dataclasses import replace
from datetime import UTC, datetime, timedelta

from core.application.retention import RetentionSweeper
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    PublishTarget,
    TargetStatus,
    VideoJob,
    VideoMetadata,
)

NOW = datetime(2026, 11, 21, 12, tzinfo=UTC)


def _job(job_id, status, phase, updated_at, targets=()):
    return VideoJob(
        job_id,
        f"request-{job_id}",
        "tech_vn",
        JobType.STORY,
        status,
        phase,
        3,
        1,
        VideoMetadata(title="Draft"),
        NOW - timedelta(days=2),
        updated_at,
        publish_targets=targets,
    )


class Candidates:
    def __init__(self, jobs):
        self.jobs = jobs

    def list_retention_candidates(self, draft_before, publish_before, limit):
        assert draft_before == NOW - timedelta(hours=6)
        assert publish_before == NOW - timedelta(hours=24)
        return self.jobs[:limit]


class Workflow:
    def __init__(self):
        self.commands = []

    def command(self, job_id, command):
        self.commands.append((job_id, command))


def test_retention_sweeper_cancels_old_draft_and_known_publish_failure_only():
    draft = _job(
        "draft",
        JobStatus.AWAITING_REVIEW,
        JobPhase.PREVIEW_RENDER,
        NOW - timedelta(hours=7),
    )
    failed = _job(
        "failed",
        JobStatus.FAILED,
        JobPhase.PUBLISH,
        NOW - timedelta(hours=25),
        (PublishTarget(Platform.YOUTUBE, TargetStatus.FAILED),),
    )
    unknown = replace(
        failed,
        job_id="unknown",
        publish_targets=(PublishTarget(Platform.YOUTUBE, TargetStatus.UNKNOWN),),
    )
    workflow = Workflow()
    sweeper = RetentionSweeper(
        Candidates((draft, failed, unknown)),
        workflow,
        now=lambda: NOW,
        draft_retention_hours=6,
        publish_failure_retention_hours=24,
    )

    count = sweeper.run_once()

    assert count == 2
    assert [job_id for job_id, _ in workflow.commands] == ["draft", "failed"]
    assert all(
        command.reason == "RETENTION_EXPIRED" for _, command in workflow.commands
    )
