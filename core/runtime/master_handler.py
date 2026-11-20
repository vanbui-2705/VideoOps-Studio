"""Worker handler for revision-safe approved master rendering."""

from __future__ import annotations

from collections.abc import Callable

from core.application.channel_ports import ChannelRepository
from core.application.events import MasterRendered, StepFailed
from core.application.master_service import MasterRenderRequest, MasterRenderService
from core.application.ports import QueuedWork, WorkflowStore
from core.domain.errors import (
    DomainValidationError,
    MediaConfigurationError,
    MediaPreparationError,
)
from core.domain.models import (
    JobFailure,
    JobPhase,
    JobStatus,
    ResumeAction,
    WorkKind,
)


class MasterRenderHandler:
    def __init__(
        self,
        workflow_store: WorkflowStore,
        channels: ChannelRepository,
        service: MasterRenderService,
    ) -> None:
        self._workflow_store = workflow_store
        self._channels = channels
        self._service = service

    async def handle(
        self, work: QueuedWork, heartbeat: Callable[[], None]
    ) -> MasterRendered | StepFailed | None:
        job = self._workflow_store.get(work.intent.job_id)
        if (
            job is None
            or work.intent.kind is not WorkKind.RENDER_MASTER
            or job.status is not JobStatus.RENDERING_MASTER
            or job.content_revision != work.intent.content_revision
        ):
            return None
        try:
            approval = job.approval_snapshot
            if (
                approval is None
                or approval.content_revision != job.content_revision
                or approval.channel_revision != job.channel_revision
            ):
                raise MediaConfigurationError("Approved master snapshot is invalid")
            channel = self._channels.get_revision(job.channel_id, job.channel_revision)
            if channel is None:
                raise MediaConfigurationError("Frozen channel revision is unavailable")
            manifest = self._service.render(
                MasterRenderRequest(job, channel),
                heartbeat,
            )
            return MasterRendered(
                expected_revision=job.revision,
                artifact_id=manifest.artifact_id,
                content_revision=job.content_revision,
            )
        except MediaPreparationError as exc:
            return StepFailed(
                expected_revision=job.revision,
                failure=JobFailure(
                    code=exc.code,
                    phase=JobPhase.MASTER_RENDER,
                    message_safe="Master rendering failed. Check media or retry.",
                    retryable=exc.retryable,
                    resume_action=ResumeAction.MASTER,
                ),
            )
        except (DomainValidationError, ValueError):
            return StepFailed(
                expected_revision=job.revision,
                failure=JobFailure(
                    code="MASTER_INPUT_INVALID",
                    phase=JobPhase.MASTER_RENDER,
                    message_safe="Approved master inputs are invalid.",
                    retryable=False,
                    resume_action=ResumeAction.MASTER,
                ),
            )
