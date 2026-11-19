from datetime import UTC, datetime

import pytest

from core.application.events import StoryPrepared
from core.application.video_workflow import DefaultWorkflowProcessor
from core.domain.errors import DomainValidationError, RevisionConflict
from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    VideoJob,
    VideoMetadata,
    WorkflowDecision,
    WorkKind,
)
from core.domain.story_models import (
    ScriptDraft,
    ScriptProvenance,
    ScriptScene,
    StorySource,
    SuggestedMetadata,
)


class Clock:
    def now(self):
        return datetime(2026, 11, 17, 10, 0, tzinfo=UTC)


class Store:
    def __init__(self, job):
        self.job = job
        self.work = []

    def get(self, job_id):
        return self.job if self.job.job_id == job_id else None

    def commit(self, decision: WorkflowDecision, expected_revision: int):
        if self.job.revision != expected_revision:
            raise RevisionConflict(self.job.job_id)
        self.job = decision.job
        self.work.extend(decision.work_intents)
        return self.job

    def get_command_result(self, command_id):
        return None


def _draft() -> ScriptDraft:
    return ScriptDraft(
        "vi-VN",
        "Title",
        "Prepared narration",
        (ScriptScene(1, "Prepared narration", ("technology",)),),
        SuggestedMetadata("Title"),
        ScriptProvenance(
            StorySource.USER_SCRIPT,
            "story-v1",
            "a" * 64,
            "b" * 64,
            datetime(2026, 11, 17, tzinfo=UTC),
        ),
    )


def _job(job_type=JobType.STORY):
    now = datetime(2026, 11, 17, tzinfo=UTC)
    return VideoJob(
        "job-story",
        "request-story",
        "tech_vn",
        job_type,
        JobStatus.QUEUED,
        JobPhase.SUBMIT,
        0,
        1,
        VideoMetadata(title="Draft"),
        now,
        now,
    )


def test_story_prepared_persists_content_and_schedules_preview() -> None:
    store = Store(_job())

    view = DefaultWorkflowProcessor(store, Clock()).apply(
        "job-story", StoryPrepared(0, 1, _draft())
    )

    assert view.status is JobStatus.RENDERING_PREVIEW
    assert store.job.prepared_story == _draft()
    assert store.job.revision == 2
    assert store.work[-1].kind is WorkKind.RENDER_PREVIEW


def test_story_prepared_rejects_remix_or_stale_content() -> None:
    with pytest.raises(DomainValidationError):
        DefaultWorkflowProcessor(Store(_job(JobType.REMIX)), Clock()).apply(
            "job-story", StoryPrepared(0, 1, _draft())
        )
    with pytest.raises(DomainValidationError):
        DefaultWorkflowProcessor(Store(_job()), Clock()).apply(
            "job-story", StoryPrepared(0, 2, _draft())
        )
