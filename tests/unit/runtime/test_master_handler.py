from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.application.events import MasterRendered, StepFailed
from core.application.ports import QueuedWork, QueueStatus
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    VisualPreset,
)
from core.domain.errors import MediaTimeoutError
from core.domain.media_models import ArtifactManifest, MediaInfo
from core.domain.models import (
    ApprovalSnapshot,
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
from core.runtime.master_handler import MasterRenderHandler

NOW = datetime(2026, 11, 20, tzinfo=UTC)


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


def _job() -> VideoJob:
    metadata = VideoMetadata(title="Approved")
    return VideoJob(
        "job-1",
        "request-1",
        "tech_vn",
        JobType.STORY,
        JobStatus.RENDERING_MASTER,
        JobPhase.MASTER_RENDER,
        5,
        1,
        metadata,
        NOW,
        NOW,
        channel_revision=2,
        approval_snapshot=ApprovalSnapshot(
            1,
            2,
            metadata,
            (Platform.YOUTUBE,),
            NOW,
        ),
        request_snapshot=StorySnapshot("story", None),
    )


def _work(content_revision: int = 1) -> QueuedWork:
    return QueuedWork(
        "work-1",
        WorkIntent("job-1", WorkKind.RENDER_MASTER, content_revision),
        QueueStatus.CLAIMED,
        1,
        3,
        NOW,
    )


class Store:
    def __init__(self, job: VideoJob) -> None:
        self.job = job

    def get(self, job_id: str) -> VideoJob | None:
        return self.job


class Channels:
    def get_revision(self, channel_id: str, revision: int):
        return _profile()


class MasterService:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls = 0

    def render(self, request, heartbeat=None) -> ArtifactManifest:
        self.calls += 1
        if self.error:
            raise self.error
        return ArtifactManifest(
            "master:1",
            "job-1",
            "MASTER",
            "master/master.mp4",
            "a" * 64,
            100,
            1,
            NOW,
            MediaInfo(4_000, "h264", 1920, 1080, "mp4", True),
        )


@pytest.mark.asyncio
async def test_master_handler_emits_revision_safe_master_event() -> None:
    service = MasterService()
    handler = MasterRenderHandler(Store(_job()), Channels(), service)

    event = await handler.handle(_work(), lambda: None)

    assert event == MasterRendered(5, "master:1", 1)
    assert service.calls == 1


@pytest.mark.asyncio
async def test_master_handler_ignores_stale_work() -> None:
    service = MasterService()
    handler = MasterRenderHandler(Store(_job()), Channels(), service)

    event = await handler.handle(_work(content_revision=2), lambda: None)

    assert event is None
    assert service.calls == 0


@pytest.mark.asyncio
async def test_master_handler_sanitizes_retryable_failure() -> None:
    service = MasterService(MediaTimeoutError("secret absolute path"))
    handler = MasterRenderHandler(Store(_job()), Channels(), service)

    event = await handler.handle(_work(), lambda: None)

    assert isinstance(event, StepFailed)
    assert event.failure.phase is JobPhase.MASTER_RENDER
    assert event.failure.resume_action.value == "MASTER"
    assert event.failure.retryable is True
    assert "secret" not in event.failure.message_safe


@pytest.mark.asyncio
async def test_master_handler_rejects_mismatched_approval_snapshot() -> None:
    service = MasterService()
    stale = replace(
        _job(),
        approval_snapshot=replace(_job().approval_snapshot, content_revision=2),
    )
    handler = MasterRenderHandler(Store(stale), Channels(), service)

    event = await handler.handle(_work(), lambda: None)

    assert isinstance(event, StepFailed)
    assert event.failure.retryable is False
    assert service.calls == 0
