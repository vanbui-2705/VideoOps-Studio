from datetime import UTC, datetime, timedelta

from core.adapters.persistence.publish_attempt_store import PostgresPublishAttemptStore
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.application.publish_attempts import PublishAttemptStatus
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    VideoJob,
    VideoMetadata,
    WorkIntent,
    WorkKind,
)

NOW = datetime(2026, 11, 20, 10, tzinfo=UTC)


def test_publish_attempt_store_reuses_logical_operation_and_tracks_safe_checkpoint(
    postgres_engine,
) -> None:
    job = VideoJob(
        "publish-attempt-job",
        "publish-attempt-request",
        "tech_vn",
        JobType.STORY,
        JobStatus.PUBLISHING,
        JobPhase.PUBLISH,
        1,
        1,
        VideoMetadata(title="Approved"),
        NOW,
        NOW,
    )
    PostgresWorkflowStore(postgres_engine).create(
        job, WorkIntent(job.job_id, WorkKind.PUBLISH_TARGET, 1, Platform.YOUTUBE)
    )
    store = PostgresPublishAttemptStore(postgres_engine)

    first = store.begin_or_get(job.job_id, Platform.YOUTUBE, "a" * 64, NOW)
    same = store.begin_or_get(job.job_id, Platform.YOUTUBE, "a" * 64, NOW)
    processing = store.update(
        "a" * 64,
        PublishAttemptStatus.PROCESSING,
        NOW + timedelta(seconds=1),
        provider_operation_id="safe-operation-id",
        retry_after=NOW + timedelta(minutes=1),
    )

    assert first == same
    assert first.attempt_number == 1
    assert processing.provider_operation_id == "safe-operation-id"
    assert processing.retry_after == NOW + timedelta(minutes=1)
    assert processing.error_code is None

    succeeded = store.update(
        "a" * 64,
        PublishAttemptStatus.SUCCEEDED,
        NOW + timedelta(seconds=2),
        provider_operation_id="safe-operation-id",
        external_id="video-1",
        public_url="https://www.youtube.com/watch?v=video-1",
    )
    assert succeeded.public_url == "https://www.youtube.com/watch?v=video-1"
