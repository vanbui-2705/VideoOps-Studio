"""End-to-end workflow proof using only in-memory fake adapters."""

from __future__ import annotations

from datetime import UTC, datetime

from core.application.commands import Approve
from core.application.events import (
    IngestionCompleted,
    JobClaimed,
    MasterRendered,
    PreviewRendered,
    PurgeCompleted,
    TargetPublishSucceeded,
)
from core.application.ports import ChannelSnapshot
from core.application.requests import StoryRequest
from core.application.video_workflow import (
    DefaultVideoWorkflow,
    DefaultWorkflowProcessor,
)
from core.domain.errors import RevisionConflict
from core.domain.models import (
    JobStatus,
    Platform,
    VideoJob,
    VideoMetadata,
    WorkflowDecision,
    WorkIntent,
    WorkKind,
)


class FixedClock:
    def now(self) -> datetime:
        return datetime(2026, 11, 16, 12, 0, tzinfo=UTC)


class FixedIds:
    def new_job_id(self) -> str:
        return "job-e2e"


class FakeChannels:
    def get_snapshot(self, channel_id: str) -> ChannelSnapshot | None:
        return ChannelSnapshot(
            channel_id,
            "Tech Việt Nam",
            7,
            available_targets=(Platform.YOUTUBE, Platform.TIKTOK),
        )


class AtomicFakeStore:
    def __init__(self) -> None:
        self.jobs: dict[str, VideoJob] = {}
        self.requests: dict[str, str] = {}
        self.commands: dict[str, str] = {}
        self.work: list[WorkIntent] = []

    def get_request_result(self, request_id: str) -> VideoJob | None:
        job_id = self.requests.get(request_id)
        return self.jobs.get(job_id) if job_id else None

    def create(self, job: VideoJob, initial_work: WorkIntent) -> VideoJob:
        self.jobs[job.job_id] = job
        self.requests[job.request_id] = job.job_id
        self.work.append(initial_work)
        return job

    def get(self, job_id: str) -> VideoJob | None:
        return self.jobs.get(job_id)

    def get_command_result(self, command_id: str) -> VideoJob | None:
        job_id = self.commands.get(command_id)
        return self.jobs.get(job_id) if job_id else None

    def commit(
        self,
        decision: WorkflowDecision,
        expected_revision: int,
    ) -> VideoJob:
        current = self.jobs[decision.job.job_id]
        if current.revision != expected_revision:
            raise RevisionConflict(decision.job.job_id)
        self.jobs[decision.job.job_id] = decision.job
        self.work.extend(decision.work_intents)
        if decision.command_id:
            self.commands[decision.command_id] = decision.job.job_id
        return decision.job


def test_story_can_reach_completed_without_real_infrastructure() -> None:
    store = AtomicFakeStore()
    workflow = DefaultVideoWorkflow(store, FakeChannels(), FixedClock(), FixedIds())
    processor = DefaultWorkflowProcessor(store, FixedClock())

    submitted = workflow.submit(
        StoryRequest(
            request_id="request-e2e",
            channel_id="tech-vn",
            script="Kịch bản đã được người dùng cung cấp.",
            metadata=VideoMetadata(title="Draft"),
        )
    )
    processor.apply(submitted.job_id, JobClaimed(expected_revision=0))
    processor.apply(submitted.job_id, IngestionCompleted(expected_revision=1))
    review = processor.apply(
        submitted.job_id,
        PreviewRendered(2, artifact_id="preview-e2e", content_revision=1),
    )
    approved = workflow.command(
        submitted.job_id,
        Approve(
            command_id="approve-e2e",
            expected_revision=review.revision,
            metadata=VideoMetadata(title="Bản đã duyệt"),
            target_platforms=(Platform.YOUTUBE,),
        ),
    )
    publishing = processor.apply(
        submitted.job_id,
        MasterRendered(
            approved.revision,
            artifact_id="master-e2e",
            content_revision=1,
        ),
    )
    purging = processor.apply(
        submitted.job_id,
        TargetPublishSucceeded(
            publishing.revision,
            platform=Platform.YOUTUBE,
            external_video_id="video-e2e",
            public_url="https://youtube.example/video-e2e",
        ),
    )
    completed = processor.apply(
        submitted.job_id,
        PurgeCompleted(purging.revision, media_bytes=0),
    )

    assert completed.status is JobStatus.COMPLETED
    assert completed.preview_artifact_id is None
    assert completed.allowed_actions == ()
    assert [intent.kind for intent in store.work] == [
        WorkKind.PREPARE_STORY,
        WorkKind.RENDER_PREVIEW,
        WorkKind.RENDER_MASTER,
        WorkKind.PUBLISH_TARGET,
        WorkKind.PURGE_JOB,
    ]
