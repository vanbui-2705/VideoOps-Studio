from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.application.story_service import (
    PrepareStoryRequest,
    StoryScriptService,
    StoryServiceConfig,
)
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ChannelProfile,
    ContentPreset,
    VisualPreset,
)
from core.domain.models import StorySnapshot, VideoMetadata
from core.domain.story_models import StorySource
from core.llm.contracts import LlmCapabilities, LlmResult
from core.llm.errors import LlmAuthenticationError, LlmTimeout


class FakeProvider:
    name = "fake"
    capabilities = LlmCapabilities(structured_output=True)

    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _profile() -> ChannelProfile:
    now = datetime(2026, 11, 17, tzinfo=UTC)
    return ChannelProfile(
        ChannelDraft(
            "tech_vn",
            "Tech Việt Nam",
            "technology",
            "vi-VN",
            ContentPreset(
                "Chuyên gia giải thích công nghệ",
                "informative",
                "Hãy viết về {input}",
            ),
            VisualPreset(stock_keywords=("technology", "future")),
            AudioPreset("voice"),
        ),
        1,
        now,
        now,
    )


def _request(snapshot: StorySnapshot) -> PrepareStoryRequest:
    return PrepareStoryRequest(
        job_id="job-1",
        content_revision=1,
        story=snapshot,
        channel=_profile(),
        metadata=VideoMetadata(title="Draft title"),
        regeneration_instructions=(),
    )


def _config(**changes) -> StoryServiceConfig:
    values = {
        "model": "configured-model",
        "prompt_version": "story-v1",
        "min_characters": 5,
        "max_characters": 5000,
        "max_scenes": 10,
        "max_keywords_per_scene": 5,
        "max_attempts": 3,
        "timeout_seconds": 30,
        "max_output_tokens": 1024,
        "temperature": 0.5,
    }
    values.update(changes)
    return StoryServiceConfig(**values)


@pytest.mark.asyncio
async def test_user_script_bypasses_provider_and_is_deterministic() -> None:
    provider = FakeProvider([])
    service = StoryScriptService(
        provider,
        _config(),
        now=lambda: datetime(2026, 11, 17, tzinfo=UTC),
    )
    request = _request(StorySnapshot("Đoạn một.\n\nĐoạn hai.", None))

    first = await service.prepare(request)
    second = await service.prepare(request)

    assert provider.requests == []
    assert first == second
    assert first.provenance.source is StorySource.USER_SCRIPT
    assert len(first.scenes) == 2


@pytest.mark.asyncio
async def test_prompt_uses_profile_and_retries_only_retryable_errors() -> None:
    result = LlmResult(
        provider="fake",
        model="configured-model",
        structured_data={
            "title": "Tương lai AI",
            "language": "vi-VN",
            "narration": "Một câu chuyện đủ dài về tương lai AI.",
            "scenes": [
                {
                    "order": 1,
                    "narration": "Mở đầu câu chuyện.",
                    "visual_keywords": ["AI", "datacenter"],
                    "visual_direction": None,
                }
            ],
            "suggested_metadata": {
                "title": "Tương lai AI",
                "description": "Khám phá AI",
                "tags": ["AI"],
            },
        },
        finish_reason="STOP",
        provider_request_id="provider-1",
        input_tokens=20,
        output_tokens=50,
    )
    provider = FakeProvider([LlmTimeout(), result])
    sleeps = []
    heartbeats = []
    service = StoryScriptService(
        provider,
        _config(),
        sleeper=lambda delay: _record_sleep(sleeps, delay),
        random_value=lambda: 0.0,
        now=lambda: datetime(2026, 11, 17, tzinfo=UTC),
    )

    draft = await service.prepare(
        _request(StorySnapshot(None, "AI sẽ thay đổi thế giới thế nào?")),
        heartbeat=lambda: heartbeats.append(True),
    )

    assert len(provider.requests) == 2
    assert "Chuyên gia giải thích công nghệ" in provider.requests[0].system_instruction
    assert "AI sẽ thay đổi" in provider.requests[0].user_content
    assert sleeps == [1.0]
    assert heartbeats == [True]
    assert draft.provenance.source is StorySource.LLM
    assert draft.provenance.provider_request_id == "provider-1"


@pytest.mark.asyncio
async def test_authentication_error_is_not_retried() -> None:
    provider = FakeProvider([LlmAuthenticationError()])
    service = StoryScriptService(provider, _config())

    with pytest.raises(LlmAuthenticationError):
        await service.prepare(_request(StorySnapshot(None, "Prompt")))

    assert len(provider.requests) == 1


async def _record_sleep(values: list[float], delay: float) -> None:
    values.append(delay)
