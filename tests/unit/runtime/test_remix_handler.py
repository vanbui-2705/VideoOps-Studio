from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.application.events import IngestionCompleted, PreviewRendered, StepFailed
from core.application.ports import QueuedWork, QueueStatus
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    VisualPreset,
)
from core.domain.errors import MediaTimeoutError
from core.domain.media_models import ArtifactManifest, MediaInfo, PreviewBundle
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    RemixClipSnapshot,
    RemixSnapshot,
    VideoJob,
    VideoMetadata,
    WorkIntent,
    WorkKind,
)
from core.runtime.preview_handler import PreviewRenderHandler
from core.runtime.remix_handler import RemixPreparationHandler

NOW = datetime(2026, 11, 19, tzinfo=UTC)


def _profile() -> ChannelProfile:
    return ChannelProfile(
        ChannelDraft(
            "tech_vn",
            "Tech VN",
            "technology",
            "vi-VN",
            ContentPreset("expert", "clear", "Write {input}"),
            VisualPreset(),
            AudioPreset("voice"),
        ),
        2,
        NOW,
        NOW,
    )


def _snapshot() -> RemixSnapshot:
    return RemixSnapshot(
        (
            RemixClipSnapshot(
                "https://media.example.com/video", 0, 4, 1, 1, "fill", False
            ),
        ),
        True,
    )


def _job(status=JobStatus.QUEUED, revision=0) -> VideoJob:
    return VideoJob(
        "job-1",
        "request-1",
        "tech_vn",
        JobType.REMIX,
        status,
        JobPhase.SUBMIT if status is JobStatus.QUEUED else JobPhase.PREVIEW_RENDER,
        revision,
        1,
        VideoMetadata(title="Remix"),
        NOW,
        NOW,
        channel_revision=2,
        request_snapshot=_snapshot(),
    )


class Store:
    def __init__(self, job) -> None:
        self.job = job

    def get(self, job_id):
        return self.job


class Channels:
    def get_revision(self, channel_id, revision):
        return _profile()


class RemixService:
    def __init__(self, error=None) -> None:
        self.error = error
        self.prepared = 0
        self.rendered = 0

    def prepare_sources(self, request, heartbeat=None):
        self.prepared += 1
        if self.error:
            raise self.error
        return ()

    def render_preview(self, request, heartbeat=None):
        self.rendered += 1
        if self.error:
            raise self.error
        media = MediaInfo(4000, "h264", 854, 480, "mp4", True)
        visual = ArtifactManifest(
            "remix:1:1",
            "job-1",
            "VISUAL_SOURCE",
            "remix/clip-1.mp4",
            "a" * 64,
            10,
            1,
            NOW,
            media,
            {"role": "normalized", "order": 1},
        )
        preview = ArtifactManifest(
            "preview:1",
            "job-1",
            "PREVIEW",
            "preview/remix.mp4",
            "b" * 64,
            10,
            1,
            NOW,
            media,
        )
        return PreviewBundle("job-1", 1, (visual, preview))


def _work(kind, revision=1):
    return QueuedWork(
        "work-1",
        WorkIntent("job-1", kind, revision),
        QueueStatus.CLAIMED,
        1,
        3,
        NOW,
    )


@pytest.mark.asyncio
async def test_remix_prepare_handler_emits_ingestion_completed() -> None:
    service = RemixService()
    handler = RemixPreparationHandler(Store(_job()), Channels(), service)

    event = await handler.handle(_work(WorkKind.PREPARE_REMIX), lambda: None)

    assert event == IngestionCompleted(0, 1)
    assert service.prepared == 1


@pytest.mark.asyncio
async def test_remix_prepare_handler_sanitizes_media_failure() -> None:
    handler = RemixPreparationHandler(
        Store(_job()), Channels(), RemixService(MediaTimeoutError("secret URL"))
    )

    event = await handler.handle(_work(WorkKind.PREPARE_REMIX), lambda: None)

    assert isinstance(event, StepFailed)
    assert event.failure.code == "MEDIA_TIMEOUT"
    assert "secret" not in event.failure.message_safe


@pytest.mark.asyncio
async def test_preview_handler_dispatches_remix_service() -> None:
    service = RemixService()
    job = replace(
        _job(JobStatus.RENDERING_PREVIEW, revision=2),
        phase=JobPhase.PREVIEW_RENDER,
    )
    handler = PreviewRenderHandler(Store(job), Channels(), None, service)

    event = await handler.handle(_work(WorkKind.RENDER_PREVIEW), lambda: None)

    assert isinstance(event, PreviewRendered)
    assert event.artifact_id == "preview:1"
    assert event.supporting_artifacts[0].artifact_id == "remix:1:1"
    assert service.rendered == 1


@pytest.mark.asyncio
async def test_remix_handlers_ignore_stale_work() -> None:
    service = RemixService()
    prepare = RemixPreparationHandler(Store(_job()), Channels(), service)
    preview = PreviewRenderHandler(
        Store(_job(JobStatus.RENDERING_PREVIEW, revision=2)),
        Channels(),
        None,
        service,
    )

    assert await prepare.handle(_work(WorkKind.PREPARE_REMIX, 2), lambda: None) is None
    assert await preview.handle(_work(WorkKind.RENDER_PREVIEW, 2), lambda: None) is None
    assert service.prepared == service.rendered == 0
