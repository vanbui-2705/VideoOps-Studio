from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from core.adapters.media.workspace import JobWorkspace
from core.application.events import TargetPublishSucceeded
from core.application.ports import QueuedWork, QueueStatus
from core.application.publish_attempts import PublishAttempt, PublishAttemptStatus
from core.application.publish_coordinator import PublishCoordinator
from core.application.publish_ports import PublishReceipt, PublishSucceeded
from core.application.video_workflow import DefaultWorkflowProcessor
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
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
    TargetStatus,
    VideoJob,
    VideoMetadata,
    WorkIntent,
    WorkKind,
)

NOW = datetime(2026, 11, 20, 12, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


class Store:
    def __init__(self, job):
        self.job = job
        self.work = []

    def get(self, job_id):
        return self.job if self.job.job_id == job_id else None

    def commit(self, decision, expected_revision):
        assert self.job.revision == expected_revision
        self.job = decision.job
        self.work.extend(decision.work_intents)
        return self.job


class Channels:
    def __init__(self, profile):
        self.profile = profile

    def get_revision(self, channel_id, revision):
        return self.profile if revision == self.profile.revision else None


class Secrets:
    def __init__(self):
        self.calls = 0

    def resolve_youtube(self, reference):
        self.calls += 1
        return object()


class Manifests:
    def __init__(self, manifest):
        self.manifest = manifest

    def get(self, job_id, artifact_id):
        return self.manifest


class Attempts:
    def __init__(self):
        self.attempt = None

    def get(self, key):
        return self.attempt

    def begin_or_get(self, job_id, platform, key, now, restart=False):
        if self.attempt is None:
            self.attempt = PublishAttempt(
                job_id,
                platform,
                1,
                PublishAttemptStatus.STARTED,
                key,
                now,
                now,
            )
        return self.attempt

    def update(self, key, status, now, **changes):
        self.attempt = PublishAttempt(
            job_id=self.attempt.job_id,
            platform=self.attempt.platform,
            attempt_number=self.attempt.attempt_number,
            status=status,
            idempotency_key=key,
            created_at=self.attempt.created_at,
            updated_at=now,
            provider_operation_id=changes.get("provider_operation_id"),
            external_id=changes.get("external_id"),
            public_url=changes.get("public_url"),
            error_code=changes.get("error_code"),
            retry_after=changes.get("retry_after"),
            completed_at=now if status is PublishAttemptStatus.SUCCEEDED else None,
        )
        return self.attempt


class Publisher:
    platform = Platform.YOUTUBE

    def __init__(self, store):
        self.store = store
        self.calls = 0

    def publish(self, request, heartbeat=None):
        self.calls += 1
        assert self.store.job.publish_targets[0].status is TargetStatus.UPLOADING
        return PublishSucceeded(
            PublishReceipt(
                "video-1",
                "https://www.youtube.com/watch?v=video-1",
                "operation-1",
                NOW,
            )
        )

    def reconcile(self, request, provider_operation_id, heartbeat=None):
        raise AssertionError("initial publish must not reconcile")


def test_publish_coordinator_persists_started_before_provider_and_receipt_before_event(
    tmp_path: Path,
) -> None:
    metadata = VideoMetadata(title="Approved")
    job = VideoJob(
        "job-publish",
        "request-publish",
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
        channel_revision=2,
        approval_snapshot=ApprovalSnapshot(1, 2, metadata, (Platform.YOUTUBE,), NOW),
        publish_targets=(PublishTarget(Platform.YOUTUBE),),
    )
    profile = ChannelProfile(
        ChannelDraft(
            "tech_vn",
            "Tech VN",
            "technology",
            "vi-VN",
            ContentPreset("expert", "clear", "Write {input}"),
            VisualPreset(),
            AudioPreset("voice"),
            credential_refs=CredentialReferences(youtube_secret_ref="YT_TECH"),
        ),
        2,
        NOW,
        NOW,
    )
    workspace = JobWorkspace(tmp_path, job.job_id, 1)
    path = workspace.final_path("master/master.mp4")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"master")
    manifest = ArtifactManifest(
        "master:1",
        job.job_id,
        "MASTER",
        "master/master.mp4",
        hashlib.sha256(b"master").hexdigest(),
        6,
        1,
        NOW,
        MediaInfo(1_000, "h264", 1920, 1080, "mp4", True, "aac"),
    )
    store = Store(job)
    processor = DefaultWorkflowProcessor(store, Clock())
    attempts = Attempts()
    publisher = Publisher(store)
    coordinator = PublishCoordinator(
        workflow_store=store,
        processor=processor,
        channels=Channels(profile),
        secrets=Secrets(),
        manifests=Manifests(manifest),
        attempts=attempts,
        publishers={Platform.YOUTUBE: publisher},
        temp_root=tmp_path,
        now=lambda: NOW,
    )
    work = QueuedWork(
        "work-1",
        WorkIntent(job.job_id, WorkKind.PUBLISH_TARGET, 1, Platform.YOUTUBE),
        QueueStatus.CLAIMED,
        1,
        3,
        NOW,
    )

    event = coordinator.execute(work, lambda: None)

    assert event == TargetPublishSucceeded(
        expected_revision=6,
        platform=Platform.YOUTUBE,
        external_video_id="video-1",
        public_url="https://www.youtube.com/watch?v=video-1",
    )
    assert attempts.attempt.status is PublishAttemptStatus.SUCCEEDED
    assert attempts.attempt.external_id == "video-1"
    assert attempts.attempt.public_url == "https://www.youtube.com/watch?v=video-1"
    assert publisher.calls == 1

    processor.apply(job.job_id, event)
    assert coordinator.execute(work, lambda: None) is None
    assert publisher.calls == 1
