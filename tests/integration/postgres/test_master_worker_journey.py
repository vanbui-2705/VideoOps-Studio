from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from core.adapters.media.workspace import JobWorkspace
from core.adapters.persistence.artifact_manifest_store import (
    PostgresArtifactManifestStore,
)
from core.adapters.persistence.channel_repository import PostgresChannelRepository
from core.adapters.persistence.models import WorkItemRow
from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.application.commands import Approve
from core.application.master_service import MasterRenderConfig, MasterRenderService
from core.application.video_workflow import (
    DefaultVideoWorkflow,
    DefaultWorkflowProcessor,
)
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    VisualPreset,
)
from core.domain.media_models import ArtifactManifest, MediaInfo
from core.domain.models import (
    ArtifactKind,
    ArtifactRef,
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    StorySnapshot,
    VideoJob,
    VideoMetadata,
    WorkIntent,
    WorkKind,
)
from core.domain.story_models import (
    ScriptDraft,
    ScriptProvenance,
    ScriptScene,
    StorySource,
    SuggestedMetadata,
)
from core.runtime.master_handler import MasterRenderHandler
from core.runtime.worker import Worker

NOW = datetime(2026, 11, 20, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


class Ids:
    def new_job_id(self):
        return "unused"


class Renderer:
    def render_story(self, **kwargs):
        kwargs["output_path"].write_bytes(b"durable-master")

    def render_remix(self, **kwargs):
        raise AssertionError("story journey must not render remix")


class Probe:
    def probe(self, path):
        return MediaInfo(1_000, "h264", 1920, 1080, "mp4", True)


def test_approval_to_master_to_publish_intents_without_platform_calls(
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
            VisualPreset(aspect_ratio="16:9"),
            AudioPreset("voice"),
        ),
        None,
        NOW,
    )
    story = ScriptDraft(
        "vi-VN",
        "Master",
        "Narration",
        (ScriptScene(1, "Narration", ("technology",)),),
        SuggestedMetadata("Master"),
        ScriptProvenance(StorySource.USER_SCRIPT, "v1", "a" * 64, "b" * 64, NOW),
    )
    job = VideoJob(
        "master-journey",
        "master-request",
        "tech_vn",
        JobType.STORY,
        JobStatus.AWAITING_REVIEW,
        JobPhase.PREVIEW_RENDER,
        3,
        1,
        VideoMetadata(title="Draft"),
        NOW,
        NOW,
        artifacts=(ArtifactRef("preview:1", ArtifactKind.PREVIEW, 1),),
        channel_revision=1,
        request_snapshot=StorySnapshot("Narration", None),
        available_targets=(Platform.YOUTUBE, Platform.TIKTOK),
        prepared_story=story,
    )
    store = PostgresWorkflowStore(postgres_engine)
    store.create(job, WorkIntent(job.job_id, WorkKind.PREPARE_STORY, 1))
    manifests = PostgresArtifactManifestStore(postgres_engine)
    workspace = JobWorkspace(tmp_path, job.job_id, 1)
    _save(
        manifests,
        workspace,
        "voice:1",
        "VOICE",
        "voice/narration.wav",
        b"voice",
        MediaInfo(1_000, "wav", has_audio=True),
    )
    _save(
        manifests,
        workspace,
        "subtitle:1",
        "SUBTITLE",
        "subtitles/narration.srt",
        b"subtitle",
    )
    _save(
        manifests,
        workspace,
        "visual:1:1",
        "VISUAL_SOURCE",
        "visuals/scene-1.mp4",
        b"visual",
        MediaInfo(2_000, "h264", 1920, 1080, "mp4", True),
        {"kind": "VIDEO"},
    )
    _save(
        manifests,
        workspace,
        "preview:1",
        "PREVIEW",
        "preview/preview.mp4",
        b"preview",
        MediaInfo(1_000, "h264", 854, 480, "mp4", True),
    )
    workflow = DefaultVideoWorkflow(store, channels, Clock(), Ids())

    approved = workflow.command(
        job.job_id,
        Approve(
            "approve-master-journey",
            3,
            VideoMetadata(title="Approved"),
            (Platform.YOUTUBE, Platform.TIKTOK),
        ),
    )
    service = MasterRenderService(
        renderer=Renderer(),
        probe=Probe(),
        manifests=manifests,
        config=MasterRenderConfig(tmp_path),
        now=lambda: NOW,
    )
    worker = Worker(
        worker_id="master-worker",
        queue=PostgresWorkQueue(postgres_engine),
        processor=DefaultWorkflowProcessor(store, Clock()),
        handlers={
            WorkKind.RENDER_MASTER: MasterRenderHandler(store, channels, service)
        },
    )
    try:
        assert approved.status is JobStatus.RENDERING_MASTER
        assert worker.run_once() is True
    finally:
        worker.close()

    completed = store.get(job.job_id)
    assert completed is not None
    assert completed.status is JobStatus.PUBLISHING
    assert sum(item.kind is ArtifactKind.MASTER for item in completed.artifacts) == 1
    assert manifests.get(job.job_id, "master:1") is not None
    with postgres_engine.connect() as connection:
        publish_work = connection.scalars(
            select(WorkItemRow.platform).where(
                WorkItemRow.job_id == job.job_id,
                WorkItemRow.kind == WorkKind.PUBLISH_TARGET.value,
            )
        ).all()
    assert set(publish_work) == {"YOUTUBE", "TIKTOK"}


def _save(
    manifests,
    workspace,
    artifact_id,
    artifact_type,
    relative_path,
    content,
    media_info=None,
    metadata=None,
):
    path = workspace.final_path(relative_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    manifests.save(
        ArtifactManifest(
            artifact_id,
            "master-journey",
            artifact_type,
            relative_path,
            hashlib.sha256(content).hexdigest(),
            len(content),
            1,
            NOW,
            media_info,
            metadata or {},
        )
    )
