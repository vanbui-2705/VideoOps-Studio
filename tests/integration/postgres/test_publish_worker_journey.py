from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select

from core.adapters.media.workspace import JobWorkspace
from core.adapters.persistence import (
    PostgresArtifactManifestStore,
    PostgresChannelRepository,
    PostgresPublishAttemptStore,
)
from core.adapters.persistence.models import PublishAttemptRow, WorkItemRow
from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.application.channel_ports import TikTokCredential, YoutubeCredential
from core.application.publish_coordinator import PublishCoordinator
from core.application.publish_ports import PublishReceipt, PublishSucceeded
from core.application.video_workflow import DefaultWorkflowProcessor
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    CredentialReferences,
    VisualPreset,
)
from core.domain.media_models import ArtifactManifest, MediaInfo
from core.domain.models import (
    ApprovalSnapshot,
    ArtifactKind,
    ArtifactRef,
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    PublishTarget,
    VideoJob,
    VideoMetadata,
    WorkIntent,
    WorkKind,
)
from core.runtime.publish_handler import PublishTargetHandler
from core.runtime.worker import Worker

NOW = datetime(2026, 11, 20, 14, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


class Secrets:
    def resolve_youtube(self, reference):
        assert reference == "YT_TECH"
        return YoutubeCredential("client", "secret", "refresh")

    def resolve_tiktok(self, reference):
        assert reference == "TT_TECH"
        return TikTokCredential("token", "open-id")


class Publisher:
    def __init__(self, platform):
        self.platform = platform
        self.calls = 0

    def publish(self, request, heartbeat=None):
        self.calls += 1
        if heartbeat:
            heartbeat()
        video_id = "yt-safe-1" if self.platform is Platform.YOUTUBE else "tt-safe-1"
        host = (
            "www.youtube.com/watch?v="
            if self.platform is Platform.YOUTUBE
            else "www.tiktok.com/@video/video/"
        )
        return PublishSucceeded(
            PublishReceipt(video_id, f"https://{host}{video_id}", video_id, NOW)
        )

    def reconcile(self, request, provider_operation_id, heartbeat=None):
        raise AssertionError("fresh work must use publish")


def test_publish_worker_persists_both_receipts_then_schedules_one_purge(
    postgres_engine, tmp_path: Path
) -> None:
    channels = PostgresChannelRepository(postgres_engine)
    channels.save(
        ChannelDraft(
            "tech_vn",
            "Tech VN",
            "technology",
            "vi-VN",
            ContentPreset("expert", "clear", "Write {input}"),
            VisualPreset(),
            AudioPreset("voice"),
            credential_refs=CredentialReferences("YT_TECH", "TT_TECH"),
        ),
        None,
        NOW,
    )
    metadata = VideoMetadata(title="Approved", privacy="private")
    job = VideoJob(
        "publish-journey",
        "publish-request",
        "tech_vn",
        JobType.STORY,
        JobStatus.PUBLISHING,
        JobPhase.PUBLISH,
        5,
        1,
        metadata,
        NOW,
        NOW,
        artifacts=(ArtifactRef("master:1", ArtifactKind.MASTER, 1),),
        channel_revision=1,
        approval_snapshot=ApprovalSnapshot(
            1, 1, metadata, (Platform.YOUTUBE, Platform.TIKTOK), NOW
        ),
        publish_targets=(
            PublishTarget(Platform.YOUTUBE),
            PublishTarget(Platform.TIKTOK),
        ),
    )
    store = PostgresWorkflowStore(postgres_engine)
    store.create(
        job, WorkIntent(job.job_id, WorkKind.PUBLISH_TARGET, 1, Platform.YOUTUBE)
    )
    queue = PostgresWorkQueue(postgres_engine)
    queue.enqueue(WorkIntent(job.job_id, WorkKind.PUBLISH_TARGET, 1, Platform.TIKTOK))
    workspace = JobWorkspace(tmp_path, job.job_id, 1)
    path = workspace.final_path("master/master.mp4")
    path.parent.mkdir(parents=True)
    content = b"validated-publish-master"
    path.write_bytes(content)
    PostgresArtifactManifestStore(postgres_engine).save(
        ArtifactManifest(
            "master:1",
            job.job_id,
            "MASTER",
            "master/master.mp4",
            hashlib.sha256(content).hexdigest(),
            len(content),
            1,
            NOW,
            MediaInfo(1_000, "h264", 1920, 1080, "mp4", True, "aac"),
        )
    )
    processor = DefaultWorkflowProcessor(store, Clock())
    publishers = {
        Platform.YOUTUBE: Publisher(Platform.YOUTUBE),
        Platform.TIKTOK: Publisher(Platform.TIKTOK),
    }
    coordinator = PublishCoordinator(
        workflow_store=store,
        processor=processor,
        channels=channels,
        secrets=Secrets(),
        manifests=PostgresArtifactManifestStore(postgres_engine),
        attempts=PostgresPublishAttemptStore(postgres_engine),
        publishers=publishers,
        temp_root=tmp_path,
        now=lambda: NOW,
    )
    worker = Worker(
        worker_id="publish-worker",
        queue=queue,
        processor=processor,
        handlers={
            WorkKind.PUBLISH_TARGET: PublishTargetHandler(coordinator),
            WorkKind.RECONCILE_TARGET: PublishTargetHandler(
                coordinator, reconcile=True
            ),
        },
    )
    try:
        assert worker.run_once() is True
        assert worker.run_once() is True
    finally:
        worker.close()

    completed = store.get(job.job_id)
    assert completed is not None
    assert completed.status is JobStatus.PURGING
    assert all(target.public_url for target in completed.publish_targets)
    assert any(item.kind is ArtifactKind.MASTER for item in completed.artifacts)
    with postgres_engine.connect() as connection:
        attempts = connection.scalar(
            select(func.count()).select_from(PublishAttemptRow)
        )
        purges = connection.scalar(
            select(func.count())
            .select_from(WorkItemRow)
            .where(
                WorkItemRow.job_id == job.job_id,
                WorkItemRow.kind == WorkKind.PURGE_JOB.value,
            )
        )
    assert attempts == 2
    assert purges == 1
    assert all(publisher.calls == 1 for publisher in publishers.values())
