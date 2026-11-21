from datetime import UTC, datetime
from pathlib import Path

from core.adapters.media.workspace import JobWorkspace
from core.adapters.persistence import PostgresAuditStore
from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.adapters.purge.workspace import WorkspacePurger
from core.application.purge import PurgeCoordinator
from core.application.video_workflow import DefaultWorkflowProcessor
from core.domain.models import (
    ArtifactKind,
    ArtifactRef,
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
from core.runtime.purge_handler import PurgeHandler
from core.runtime.worker import Worker

NOW = datetime(2026, 11, 21, 11, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


def test_purge_worker_retains_audit_and_completes_only_after_zero_bytes(
    postgres_engine, tmp_path: Path
) -> None:
    job = VideoJob(
        "purge-worker-job",
        "purge-worker-request",
        "tech_vn",
        JobType.STORY,
        JobStatus.PURGING,
        JobPhase.PURGE,
        9,
        1,
        VideoMetadata(title="Approved"),
        NOW,
        NOW,
        artifacts=(ArtifactRef("master:1", ArtifactKind.MASTER, 1),),
        publish_targets=(
            PublishTarget(
                Platform.YOUTUBE,
                TargetStatus.SUCCEEDED,
                "yt-1",
                "https://www.youtube.com/watch?v=yt-1",
            ),
        ),
    )
    store = PostgresWorkflowStore(postgres_engine)
    store.create(job, WorkIntent(job.job_id, WorkKind.PURGE_JOB, 1))
    workspace = JobWorkspace(tmp_path, job.job_id, 1)
    master = workspace.final_path("master/master.mp4")
    master.parent.mkdir(parents=True)
    master.write_bytes(b"master")
    audit = PostgresAuditStore(postgres_engine)
    coordinator = PurgeCoordinator(
        store, audit, WorkspacePurger(tmp_path), now=lambda: NOW
    )
    worker = Worker(
        worker_id="purge-worker",
        queue=PostgresWorkQueue(postgres_engine),
        processor=DefaultWorkflowProcessor(store, Clock()),
        handlers={WorkKind.PURGE_JOB: PurgeHandler(coordinator)},
    )
    try:
        assert worker.run_once() is True
    finally:
        worker.close()

    completed = store.get(job.job_id)
    assert completed is not None
    assert completed.status is JobStatus.COMPLETED
    assert completed.artifacts == ()
    assert not workspace.root.parent.exists()
    assert any(
        record.action == "PURGE_SNAPSHOT" for record in audit.list_for_job(job.job_id)
    )
