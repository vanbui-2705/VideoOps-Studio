from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from core.application.events import StepFailed, StoryPrepared
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    VisualPreset,
)
from core.domain.errors import DomainValidationError
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    ResumeAction,
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
from core.llm.errors import LlmAuthenticationError
from core.runtime.story_handler import StoryPreparationHandler

NOW = datetime(2026, 11, 17, 8, tzinfo=UTC)


def _profile() -> ChannelProfile:
    return ChannelProfile(
        ChannelDraft(
            "tech_vn",
            "Tech VN",
            "technology",
            "vi-VN",
            ContentPreset("expert", "clear", "Write {input}"),
            VisualPreset(stock_keywords=("technology",)),
            AudioPreset("voice"),
        ),
        3,
        NOW,
        NOW,
    )


def _draft() -> ScriptDraft:
    return ScriptDraft(
        "vi-VN",
        "AI",
        "Một câu chuyện về AI.",
        (ScriptScene(1, "Một câu chuyện về AI.", ("AI",)),),
        SuggestedMetadata("AI"),
        ScriptProvenance(
            StorySource.USER_SCRIPT,
            "v1",
            "a" * 64,
            "b" * 64,
            NOW,
        ),
    )


def _job() -> VideoJob:
    return VideoJob(
        "job-1",
        "request-1",
        "tech_vn",
        JobType.STORY,
        JobStatus.QUEUED,
        JobPhase.SUBMIT,
        0,
        1,
        VideoMetadata(title="AI"),
        NOW,
        NOW,
        channel_revision=3,
        request_snapshot=StorySnapshot("Một câu chuyện về AI.", None),
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


class Cache:
    def __init__(self, cached=None):
        self.cached = cached
        self.recorded = None

    def get_completed(self, job_id, content_revision, request_hash):
        return self.cached

    def record_completed(
        self, job_id, content_revision, request_hash, draft, completed_at
    ):
        self.recorded = (job_id, content_revision, request_hash, completed_at)
        return draft


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
    from core.application.ports import QueuedWork, QueueStatus

    return QueuedWork(
        "work-1",
        WorkIntent("job-1", WorkKind.PREPARE_STORY, revision),
        QueueStatus.CLAIMED,
        1,
        3,
        NOW,
    )


@pytest.mark.asyncio
async def test_handler_uses_exact_channel_revision_and_records_result() -> None:
    channels = Channels()
    cache = Cache()
    service = Service(_draft())
    handler = StoryPreparationHandler(
        Store(_job()), channels, service, cache, now=lambda: NOW
    )

    event = await handler.handle(_work(), lambda: None)

    assert event == StoryPrepared(0, 1, _draft())
    assert channels.requested == ("tech_vn", 3)
    assert service.calls == 1
    assert cache.recorded is not None


@pytest.mark.asyncio
async def test_handler_returns_cached_result_without_calling_service() -> None:
    service = Service(_draft())
    handler = StoryPreparationHandler(
        Store(_job()), Channels(), service, Cache(_draft()), now=lambda: NOW
    )

    event = await handler.handle(_work(), lambda: None)

    assert isinstance(event, StoryPrepared)
    assert service.calls == 0


@pytest.mark.asyncio
async def test_handler_converts_expected_llm_error_to_safe_failure_event() -> None:
    service = Service(error=LlmAuthenticationError("secret leaked"))
    handler = StoryPreparationHandler(
        Store(_job()), Channels(), service, Cache(), now=lambda: NOW
    )

    event = await handler.handle(_work(), lambda: None)

    assert isinstance(event, StepFailed)
    assert event.failure.code == "LLM_AUTHENTICATION"
    assert event.failure.phase is JobPhase.STORY_PREPARATION
    assert event.failure.resume_action is ResumeAction.PREPARE
    assert "secret" not in event.failure.message_safe


@pytest.mark.asyncio
async def test_handler_acks_stale_work_as_obsolete() -> None:
    handler = StoryPreparationHandler(
        Store(replace(_job(), content_revision=2)),
        Channels(),
        Service(_draft()),
        Cache(),
        now=lambda: NOW,
    )

    assert await handler.handle(_work(1), lambda: None) is None


@pytest.mark.asyncio
async def test_handler_converts_invalid_content_to_non_retryable_failure() -> None:
    handler = StoryPreparationHandler(
        Store(_job()),
        Channels(),
        Service(error=DomainValidationError("raw unsafe input")),
        Cache(),
        now=lambda: NOW,
    )

    event = await handler.handle(_work(), lambda: None)

    assert isinstance(event, StepFailed)
    assert event.failure.code == "STORY_INPUT_INVALID"
    assert event.failure.retryable is False
    assert "unsafe" not in event.failure.message_safe
