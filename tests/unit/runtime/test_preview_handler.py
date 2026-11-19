from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.application.events import PreviewRendered, StepFailed
from core.application.ports import QueuedWork, QueueStatus
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    VisualPreset,
)
from core.domain.errors import MediaTimeoutError
from core.domain.media_models import ArtifactManifest, PreviewBundle
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

NOW = datetime(2026, 11, 17, tzinfo=UTC)


def _story():
    return ScriptDraft(
        "vi-VN",
        "Story",
        "Narration",
        (ScriptScene(1, "Narration", ("visual",)),),
        SuggestedMetadata("Story"),
        ScriptProvenance(StorySource.USER_SCRIPT, "v1", "a" * 64, "b" * 64, NOW),
    )


def _job():
    return VideoJob(
        "job-1",
        "request-1",
        "tech_vn",
        JobType.STORY,
        JobStatus.RENDERING_PREVIEW,
        JobPhase.PREVIEW_RENDER,
        2,
        1,
        VideoMetadata(title="Story"),
        NOW,
        NOW,
        channel_revision=3,
        request_snapshot=StorySnapshot("Narration", None),
        prepared_story=_story(),
    )


def _profile():
    return ChannelProfile(
        ChannelDraft(
            "tech_vn",
            "Tech",
            "technology",
            "vi-VN",
            ContentPreset("expert", "clear", "Write {input}"),
            VisualPreset(),
            AudioPreset("voice"),
        ),
        3,
        NOW,
        NOW,
    )


def _manifest(role, kind):
    return ArtifactManifest(
        f"{role}:1",
        "job-1",
        kind,
        f"{role}/file.bin",
        "a" * 64,
        10,
        1,
        NOW,
    )


class Store:
    def __init__(self, job):
        self.job = job

    def get(self, job_id):
        return self.job


class Channels:
    def __init__(self):
        self.requested = None

    def get_revision(self, channel_id, revision):
        self.requested = (channel_id, revision)
        return _profile()


class Service:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls = 0

    async def prepare(self, request, heartbeat=None):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result


def _work(revision=1):
    return QueuedWork(
        "work-preview",
        WorkIntent("job-1", WorkKind.RENDER_PREVIEW, revision),
        QueueStatus.CLAIMED,
        1,
        3,
        NOW,
    )


@pytest.mark.asyncio
async def test_preview_handler_maps_bundle_to_typed_workflow_event() -> None:
    bundle = PreviewBundle(
        "job-1",
        1,
        (
            _manifest("preview", "PREVIEW"),
            _manifest("voice", "VOICE"),
            _manifest("subtitle", "SUBTITLE"),
            _manifest("visual", "VISUAL_SOURCE"),
        ),
    )
    channels = Channels()
    handler = PreviewRenderHandler(Store(_job()), channels, Service(bundle))

    event = await handler.handle(_work(), lambda: None)

    assert isinstance(event, PreviewRendered)
    assert event.expected_revision == 2
    assert event.artifact_id == "preview:1"
    assert {item.kind for item in event.supporting_artifacts} == {
        ArtifactKind.VOICE,
        ArtifactKind.SUBTITLE,
        ArtifactKind.VISUAL_SOURCE,
    }
    assert channels.requested == ("tech_vn", 3)


@pytest.mark.asyncio
async def test_preview_handler_maps_timeout_to_safe_retryable_failure() -> None:
    handler = PreviewRenderHandler(
        Store(_job()), Channels(), Service(error=MediaTimeoutError("path secret"))
    )

    event = await handler.handle(_work(), lambda: None)

    assert isinstance(event, StepFailed)
    assert event.failure.code == "MEDIA_TIMEOUT"
    assert event.failure.retryable is True
    assert "secret" not in event.failure.message_safe


@pytest.mark.asyncio
async def test_preview_handler_acks_stale_work_without_side_effect() -> None:
    service = Service()
    handler = PreviewRenderHandler(
        Store(replace(_job(), content_revision=2)), Channels(), service
    )

    assert await handler.handle(_work(1), lambda: None) is None
    assert service.calls == 0
