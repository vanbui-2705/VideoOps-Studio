from __future__ import annotations

from datetime import UTC, datetime

import pytest

from core.adapters.persistence.story_generation_store import (
    PostgresStoryGenerationStore,
)
from core.adapters.persistence.workflow_store import PostgresWorkflowStore
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
from core.domain.story_models import (
    ScriptDraft,
    ScriptProvenance,
    ScriptScene,
    StorySource,
    SuggestedMetadata,
)
from core.llm.errors import StoryGenerationConflict


def _draft(now: datetime) -> ScriptDraft:
    return ScriptDraft(
        language="vi",
        title="Cache",
        narration="Nội dung cache.",
        scenes=(ScriptScene(1, "Nội dung cache.", ("cache",)),),
        suggested_metadata=SuggestedMetadata("Cache"),
        provenance=ScriptProvenance(
            StorySource.USER_SCRIPT,
            "v1",
            "a" * 64,
            "b" * 64,
            now,
        ),
    )


def _create_job(engine, now: datetime) -> None:
    job = VideoJob(
        job_id="story-cache-job",
        request_id="story-cache-request",
        channel_id="tech_vn",
        job_type=JobType.STORY,
        status=JobStatus.QUEUED,
        phase=JobPhase.SUBMIT,
        revision=0,
        content_revision=1,
        metadata_draft=VideoMetadata(title="Cache"),
        created_at=now,
        updated_at=now,
        request_snapshot=StorySnapshot(script="Nội dung cache.", prompt=None),
    )
    PostgresWorkflowStore(engine).create(
        job, WorkIntent(job.job_id, WorkKind.PREPARE_STORY, 1)
    )


def test_story_generation_store_is_idempotent_and_detects_changed_inputs(
    postgres_engine,
) -> None:
    now = datetime(2026, 11, 17, 8, tzinfo=UTC)
    _create_job(postgres_engine, now)
    store = PostgresStoryGenerationStore(postgres_engine)
    draft = _draft(now)

    assert store.get_completed("story-cache-job", 1, "c" * 64) is None
    first = store.record_completed("story-cache-job", 1, "c" * 64, draft, now)
    second = store.record_completed("story-cache-job", 1, "c" * 64, draft, now)

    assert first == draft
    assert second == draft
    assert store.get_completed("story-cache-job", 1, "c" * 64) == draft
    with pytest.raises(StoryGenerationConflict):
        store.get_completed("story-cache-job", 1, "d" * 64)
