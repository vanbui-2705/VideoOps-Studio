from datetime import UTC, datetime

from core.adapters.persistence.audit_store import PostgresAuditStore
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
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

NOW = datetime(2026, 11, 21, 10, tzinfo=UTC)


def test_purge_audit_snapshot_is_idempotent_and_contains_only_safe_receipts(
    postgres_engine,
) -> None:
    job = VideoJob(
        "audit-purge-job",
        "audit-purge-request",
        "tech_vn",
        JobType.STORY,
        JobStatus.PURGING,
        JobPhase.PURGE,
        8,
        1,
        VideoMetadata(title="Approved", description="must not be retained"),
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
    PostgresWorkflowStore(postgres_engine).create(
        job, WorkIntent(job.job_id, WorkKind.PURGE_JOB, 1)
    )
    audit = PostgresAuditStore(postgres_engine)

    audit.ensure_purge_snapshot(job, NOW)
    audit.ensure_purge_snapshot(job, NOW)
    records = audit.list_for_job(job.job_id)

    purge_records = [record for record in records if record.action == "PURGE_SNAPSHOT"]
    assert len(purge_records) == 1
    metadata = purge_records[0].metadata
    assert metadata["title"] == "Approved"
    assert metadata["targets"][0]["external_id"] == "yt-1"
    assert "description" not in metadata
    assert "request_id" not in metadata
