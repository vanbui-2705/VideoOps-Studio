from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from core.adapters.persistence.channel_repository import PostgresChannelRepository
from core.adapters.persistence.story_generation_store import (
    PostgresStoryGenerationStore,
)
from core.adapters.persistence.work_queue import PostgresWorkQueue
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
from core.application.story_service import StoryScriptService, StoryServiceConfig
from core.application.video_workflow import DefaultWorkflowProcessor
from core.domain.channel_models import (
    AudioPreset,
    ChannelDraft,
    ContentPreset,
    VisualPreset,
)
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    StorySnapshot,
    VideoJob,
    VideoMetadata,
    WorkIntent,
    WorkKind,
)
from core.llm.contracts import LlmCapabilities, LlmResult
from core.runtime.story_handler import StoryPreparationHandler
from core.runtime.worker import Worker

NOW = datetime(2026, 11, 16, 8, tzinfo=UTC)


class Clock:
    def now(self):
        return NOW


class FakeProvider:
    name = "fake"
    capabilities = LlmCapabilities(structured_output=True)

    def __init__(self, result: LlmResult) -> None:
        self.result = result
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return self.result


def _channel(persona: str) -> ChannelDraft:
    return ChannelDraft(
        "tech_vn",
        "Tech VN",
        "technology",
        "vi-VN",
        ContentPreset(persona, "clear", "Write a story about {input}"),
        VisualPreset(stock_keywords=("technology", "future")),
        AudioPreset("voice"),
    )


def _service(provider) -> StoryScriptService:
    return StoryScriptService(
        provider,
        StoryServiceConfig(
            model="fake-model",
            prompt_version="story-v1",
            min_characters=5,
            max_characters=5000,
            max_scenes=10,
            max_keywords_per_scene=5,
            max_attempts=2,
            timeout_seconds=5,
            max_output_tokens=1000,
            temperature=0.3,
        ),
        now=lambda: NOW,
    )


def _seed(postgres_engine, snapshot: StorySnapshot):
    channels = PostgresChannelRepository(postgres_engine)
    channels.save(_channel("historical-persona"), None, NOW)
    job = VideoJob(
        "story-journey",
        "story-journey-request",
        "tech_vn",
        JobType.STORY,
        JobStatus.QUEUED,
        JobPhase.SUBMIT,
        0,
        1,
        VideoMetadata(title="AI future"),
        NOW,
        NOW,
        channel_revision=1,
        request_snapshot=snapshot,
    )
    store = PostgresWorkflowStore(postgres_engine)
    store.create(job, WorkIntent(job.job_id, WorkKind.PREPARE_STORY, 1))
    channels.save(
        replace(
            _channel("historical-persona"),
            content=ContentPreset(
                "new-persona", "clear", "Write a story about {input}"
            ),
        ),
        1,
        NOW,
    )
    return store, channels


def _worker(postgres_engine, store, channels, service):
    queue = PostgresWorkQueue(postgres_engine)
    handler = StoryPreparationHandler(
        store,
        channels,
        service,
        PostgresStoryGenerationStore(postgres_engine),
        now=lambda: NOW,
    )
    return queue, Worker(
        worker_id="story-worker",
        queue=queue,
        processor=DefaultWorkflowProcessor(store, Clock()),
        handlers={WorkKind.PREPARE_STORY: handler},
    )


def test_prompt_journey_uses_frozen_profile_and_schedules_preview(
    postgres_engine,
) -> None:
    provider = FakeProvider(
        LlmResult(
            provider="fake",
            model="fake-model",
            structured_data={
                "title": "AI future",
                "language": "vi-VN",
                "narration": "Một câu chuyện đủ dài về tương lai AI.",
                "scenes": [
                    {
                        "order": 1,
                        "narration": "Mở đầu về AI.",
                        "visual_keywords": ["AI", "future"],
                    }
                ],
                "suggested_metadata": {
                    "title": "AI future",
                    "description": "",
                    "tags": ["AI"],
                },
            },
            finish_reason="STOP",
        )
    )
    store, channels = _seed(postgres_engine, StorySnapshot(None, "AI"))
    queue, worker = _worker(postgres_engine, store, channels, _service(provider))

    assert worker.run_once() is True
    assert worker.run_once() is False
    completed = store.get("story-journey")
    assert completed is not None
    assert completed.status is JobStatus.RENDERING_PREVIEW
    assert completed.prepared_story is not None
    assert "historical-persona" in provider.requests[0].system_instruction
    assert "new-persona" not in provider.requests[0].system_instruction
    preview = queue.claim_next("preview-worker", 60, (WorkKind.RENDER_PREVIEW,))
    assert preview is not None


def test_user_script_journey_never_calls_provider(postgres_engine) -> None:
    provider = FakeProvider(LlmResult("fake", "fake-model", {}, "STOP"))
    store, channels = _seed(
        postgres_engine,
        StorySnapshot("Đây là kịch bản do người dùng cung cấp.", None),
    )
    _, worker = _worker(postgres_engine, store, channels, _service(provider))

    assert worker.run_once() is True
    completed = store.get("story-journey")
    assert completed is not None
    assert completed.prepared_story is not None
    assert completed.prepared_story.narration.startswith("Đây là kịch bản")
    assert provider.requests == []
