"""Worker handler for idempotent story preparation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from core.application.channel_ports import ChannelRepository
from core.application.events import StepFailed, StoryPrepared
from core.application.ports import QueuedWork, WorkflowStore
from core.application.story_ports import StoryGenerationStore
from core.application.story_service import (
    PrepareStoryRequest,
    StoryScriptService,
    story_request_hash,
)
from core.domain.errors import DomainValidationError
from core.domain.models import (
    JobFailure,
    JobPhase,
    JobStatus,
    JobType,
    ResumeAction,
    StorySnapshot,
    WorkKind,
)
from core.llm.errors import LlmConfigurationError, LlmError


class StoryPreparationHandler:
    """Resolve frozen inputs, reuse cached output, and emit one workflow event."""

    def __init__(
        self,
        workflow_store: WorkflowStore,
        channels: ChannelRepository,
        service: StoryScriptService,
        generations: StoryGenerationStore,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._workflow_store = workflow_store
        self._channels = channels
        self._service = service
        self._generations = generations
        self._now = now or (lambda: datetime.now(UTC))

    async def handle(
        self, work: QueuedWork, heartbeat: Callable[[], None]
    ) -> StoryPrepared | StepFailed | None:
        job = self._workflow_store.get(work.intent.job_id)
        if (
            job is None
            or work.intent.kind is not WorkKind.PREPARE_STORY
            or job.job_type is not JobType.STORY
            or job.status not in {JobStatus.QUEUED, JobStatus.INGESTING}
            or job.content_revision != work.intent.content_revision
        ):
            return None
        try:
            if not isinstance(job.request_snapshot, StorySnapshot):
                raise LlmConfigurationError("Story request snapshot is unavailable")
            channel = self._channels.get_revision(job.channel_id, job.channel_revision)
            if channel is None:
                raise LlmConfigurationError("Frozen channel revision is unavailable")
            request = PrepareStoryRequest(
                job_id=job.job_id,
                content_revision=job.content_revision,
                story=job.request_snapshot,
                channel=channel,
                metadata=job.metadata_draft,
                regeneration_instructions=job.regeneration_instructions,
            )
            hash_method = getattr(self._service, "request_hash", None)
            request_hash = (
                hash_method(request) if hash_method else story_request_hash(request)
            )
            draft = self._generations.get_completed(
                job.job_id, job.content_revision, request_hash
            )
            if draft is None:
                draft = await self._service.prepare(request, heartbeat)
                draft = self._generations.record_completed(
                    job.job_id,
                    job.content_revision,
                    request_hash,
                    draft,
                    self._now(),
                )
            return StoryPrepared(job.revision, job.content_revision, draft)
        except LlmError as exc:
            retry_after = (
                self._now() + timedelta(seconds=exc.retry_after)
                if exc.retry_after is not None
                else None
            )
            return StepFailed(
                expected_revision=job.revision,
                failure=JobFailure(
                    code=exc.code,
                    phase=JobPhase.STORY_PREPARATION,
                    message_safe="Không thể chuẩn bị kịch bản. Kiểm tra cấu hình hoặc thử lại.",
                    retryable=exc.retryable,
                    resume_action=ResumeAction.PREPARE,
                    retry_after=retry_after,
                    diagnostic_ref=exc.diagnostic_ref,
                ),
            )
        except DomainValidationError:
            return StepFailed(
                expected_revision=job.revision,
                failure=JobFailure(
                    code="STORY_INPUT_INVALID",
                    phase=JobPhase.STORY_PREPARATION,
                    message_safe="Kịch bản không đáp ứng giới hạn nội dung đã cấu hình.",
                    retryable=False,
                    resume_action=ResumeAction.PREPARE,
                ),
            )
