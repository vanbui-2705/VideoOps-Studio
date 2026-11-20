"""Worker handler for revision-safe remix source preparation."""

from __future__ import annotations

from collections.abc import Callable

from core.application.channel_ports import ChannelRepository
from core.application.events import IngestionCompleted, StepFailed
from core.application.ports import QueuedWork, WorkflowStore
from core.application.remix_service import PrepareRemixRequest, RemixMediaService
from core.domain.errors import (
    DomainValidationError,
    MediaConfigurationError,
    MediaPreparationError,
)
from core.domain.models import (
    JobFailure,
    JobPhase,
    JobStatus,
    JobType,
    RemixSnapshot,
    ResumeAction,
    WorkKind,
)


class RemixPreparationHandler:
    def __init__(
        self,
        workflow_store: WorkflowStore,
        channels: ChannelRepository,
        service: RemixMediaService,
    ) -> None:
        self._workflow_store = workflow_store
        self._channels = channels
        self._service = service

    async def handle(
        self, work: QueuedWork, heartbeat: Callable[[], None]
    ) -> IngestionCompleted | StepFailed | None:
        job = self._workflow_store.get(work.intent.job_id)
        if (
            job is None
            or work.intent.kind is not WorkKind.PREPARE_REMIX
            or job.job_type is not JobType.REMIX
            or job.status not in {JobStatus.QUEUED, JobStatus.INGESTING}
            or job.content_revision != work.intent.content_revision
        ):
            return None
        try:
            if not isinstance(job.request_snapshot, RemixSnapshot):
                raise MediaConfigurationError("Remix request snapshot is unavailable")
            channel = self._channels.get_revision(job.channel_id, job.channel_revision)
            if channel is None:
                raise MediaConfigurationError("Frozen channel revision is unavailable")
            self._service.prepare_sources(
                PrepareRemixRequest(
                    job.job_id,
                    job.content_revision,
                    job.request_snapshot,
                    channel,
                ),
                heartbeat,
            )
            return IngestionCompleted(job.revision, job.content_revision)
        except MediaPreparationError as exc:
            return StepFailed(
                expected_revision=job.revision,
                failure=JobFailure(
                    code=exc.code,
                    phase=JobPhase.REMIX_PREPARATION,
                    message_safe="Không thể chuẩn bị nguồn remix. Kiểm tra dữ liệu hoặc thử lại.",
                    retryable=exc.retryable,
                    resume_action=ResumeAction.PREPARE,
                ),
            )
        except (DomainValidationError, ValueError):
            return StepFailed(
                expected_revision=job.revision,
                failure=JobFailure(
                    code="REMIX_INPUT_INVALID",
                    phase=JobPhase.REMIX_PREPARATION,
                    message_safe="Cấu hình remix không hợp lệ.",
                    retryable=False,
                    resume_action=ResumeAction.PREPARE,
                ),
            )
