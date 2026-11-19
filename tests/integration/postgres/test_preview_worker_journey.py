from __future__ import annotations

import io
import wave
from datetime import UTC, datetime
from pathlib import Path

from config import AppConfig
from core.adapters.media.ffmpeg_preview import FfmpegPreviewRenderer, FfprobeMediaProbe
from core.adapters.persistence.artifact_manifest_store import (
    PostgresArtifactManifestStore,
)
from core.adapters.persistence.channel_repository import PostgresChannelRepository
from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.application.media_ports import TtsResult
from core.application.preview_service import (
    PreviewPreparationConfig,
    PreviewPreparationService,
)
from core.application.video_workflow import DefaultWorkflowProcessor
from core.composition import build_preview_worker
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    VisualPreset,
)
from core.domain.media_models import SubtitleCue
from core.domain.models import (
    ArtifactKind,
    JobPhase,
    JobStatus,
    JobType,
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
from core.runtime.preview_handler import PreviewRenderHandler
from core.runtime.worker import Worker

NOW = datetime(2026, 11, 16, 8, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


class WaveTts:
    def __init__(self):
        self.calls = 0

    async def synthesize(self, request):
        self.calls += 1
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16_000)
            output.writeframes(b"\x00\x00" * 16_000)
        return TtsResult(
            buffer.getvalue(),
            (SubtitleCue(1, 0, 900, "Xin chào Việt Nam"),),
            "wav",
        )


class NoDownload:
    async def download(self, *args, **kwargs):
        raise AssertionError("generated fallback should not download")


def _story() -> ScriptDraft:
    return ScriptDraft(
        "vi-VN",
        "Preview",
        "Xin chào Việt Nam",
        (ScriptScene(1, "Xin chào Việt Nam", ("Vietnam",)),),
        SuggestedMetadata("Preview"),
        ScriptProvenance(StorySource.USER_SCRIPT, "v1", "a" * 64, "b" * 64, NOW),
    )


def test_preview_worker_renders_and_enters_review_with_durable_manifests(
    postgres_engine,
    tmp_path: Path,
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
            AudioPreset("fake-voice"),
        ),
        None,
        NOW,
    )
    story = _story()
    job = VideoJob(
        "preview-journey",
        "preview-journey-request",
        "tech_vn",
        JobType.STORY,
        JobStatus.RENDERING_PREVIEW,
        JobPhase.PREVIEW_RENDER,
        2,
        1,
        VideoMetadata(title="Preview"),
        NOW,
        NOW,
        channel_revision=1,
        request_snapshot=StorySnapshot("Xin chào Việt Nam", None),
        prepared_story=story,
    )
    workflow = PostgresWorkflowStore(postgres_engine)
    workflow.create(job, WorkIntent(job.job_id, WorkKind.RENDER_PREVIEW, 1))
    manifests = PostgresArtifactManifestStore(postgres_engine)
    tts = WaveTts()
    service = PreviewPreparationService(
        tts=tts,
        stock_providers=(),
        downloader=NoDownload(),
        probe=FfprobeMediaProbe(timeout_seconds=10),
        renderer=FfmpegPreviewRenderer(timeout_seconds=30),
        manifests=manifests,
        config=PreviewPreparationConfig(tmp_path),
        now=lambda: NOW,
    )
    queue = PostgresWorkQueue(postgres_engine)
    worker = Worker(
        worker_id="preview-worker",
        queue=queue,
        processor=DefaultWorkflowProcessor(workflow, Clock()),
        handlers={
            WorkKind.RENDER_PREVIEW: PreviewRenderHandler(workflow, channels, service)
        },
    )

    try:
        assert worker.run_once() is True
        assert worker.run_once() is False
    finally:
        worker.close()

    completed = workflow.get(job.job_id)
    assert completed is not None
    assert completed.status is JobStatus.AWAITING_REVIEW
    assert (
        next(
            item.artifact_id
            for item in completed.artifacts
            if item.kind is ArtifactKind.PREVIEW
        )
        == "preview:1"
    )
    assert {item.kind for item in completed.artifacts} == {
        ArtifactKind.VOICE,
        ArtifactKind.SUBTITLE,
        ArtifactKind.VISUAL_SOURCE,
        ArtifactKind.PREVIEW,
    }
    preview = manifests.get(job.job_id, "preview:1")
    assert preview is not None
    assert preview.media_info is not None
    assert preview.media_info.codec == "h264"
    assert (preview.media_info.width, preview.media_info.height) == (854, 480)
    assert (
        tmp_path / "jobs/preview-journey/revision-1" / preview.relative_path
    ).is_file()
    assert tts.calls == 1


def test_preview_worker_composition_starts_with_current_database_schema(
    postgres_url: str,
    tmp_path: Path,
) -> None:
    runtime = build_preview_worker(
        AppConfig(
            DATABASE_URL=postgres_url,
            TEMP_DIR=tmp_path,
            MEDIA_MIN_FREE_DISK_GB=0,
        )
    )
    try:
        assert runtime.worker.run_once() is False
    finally:
        runtime.close()
