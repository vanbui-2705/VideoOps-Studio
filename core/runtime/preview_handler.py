"""Worker handler for revision-safe story preview preparation."""

from __future__ import annotations

from collections.abc import Callable

from core.application.channel_ports import ChannelRepository
from core.application.events import PreviewRendered, StepFailed
from core.application.ports import QueuedWork, WorkflowStore
from core.application.preview_service import (
    PreparePreviewRequest,
    PreviewPreparationService,
)
from core.domain.errors import (
    DomainValidationError,
    MediaConfigurationError,
    MediaPreparationError,
)
from core.domain.models import (
    ArtifactKind,
    ArtifactRef,
    JobFailure,
    JobPhase,
    JobStatus,
    JobType,
    ResumeAction,
    WorkKind,
)


class PreviewRenderHandler:
    def __init__(
        self,
        workflow_store: WorkflowStore,
        channels: ChannelRepository,
        service: PreviewPreparationService,
    ) -> None:
        self._workflow_store = workflow_store
        self._channels = channels
        self._service = service

    async def handle(
        self, work: QueuedWork, heartbeat: Callable[[], None]
    ) -> PreviewRendered | StepFailed | None:
        job = self._workflow_store.get(work.intent.job_id)
        if (
            job is None
            or work.intent.kind is not WorkKind.RENDER_PREVIEW
            or job.job_type is not JobType.STORY
            or job.status is not JobStatus.RENDERING_PREVIEW
            or job.content_revision != work.intent.content_revision
        ):
            return None
        try:
            if job.prepared_story is None:
                raise MediaConfigurationError("Prepared story is unavailable")
            channel = self._channels.get_revision(job.channel_id, job.channel_revision)
            if channel is None:
                raise MediaConfigurationError("Frozen channel revision is unavailable")
            bundle = await self._service.prepare(
                PreparePreviewRequest(
                    job.job_id,
                    job.content_revision,
                    job.prepared_story,
                    channel,
                ),
                heartbeat,
            )
            preview = [
                item for item in bundle.artifacts if item.artifact_type == "PREVIEW"
            ]
            if len(preview) != 1:
                raise DomainValidationError("Preview bundle requires one preview")
            supporting = tuple(
                ArtifactRef(
                    item.artifact_id,
                    ArtifactKind(item.artifact_type),
                    item.content_revision,
                )
                for item in bundle.artifacts
                if item.artifact_type != "PREVIEW"
            )
            return PreviewRendered(
                expected_revision=job.revision,
                artifact_id=preview[0].artifact_id,
                content_revision=job.content_revision,
                supporting_artifacts=supporting,
            )
        except MediaPreparationError as exc:
            return StepFailed(
                expected_revision=job.revision,
                failure=JobFailure(
                    code=exc.code,
                    phase=JobPhase.PREVIEW_RENDER,
                    message_safe="Không thể chuẩn bị video xem trước. Kiểm tra cấu hình hoặc thử lại.",
                    retryable=exc.retryable,
                    resume_action=ResumeAction.PREVIEW,
                ),
            )
        except (DomainValidationError, ValueError):
            return StepFailed(
                expected_revision=job.revision,
                failure=JobFailure(
                    code="MEDIA_INVALID_OUTPUT",
                    phase=JobPhase.PREVIEW_RENDER,
                    message_safe="Tài nguyên xem trước không hợp lệ.",
                    retryable=False,
                    resume_action=ResumeAction.PREVIEW,
                ),
            )
