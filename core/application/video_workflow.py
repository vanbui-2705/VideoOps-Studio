"""External application interface for video workflow orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Protocol

from core.application.commands import (
    Approve,
    Cancel,
    JobCommand,
    Regenerate,
    Retry,
    RetryScope,
    SkipTarget,
    UpdateMetadata,
)
from core.application.events import (
    IngestionCompleted,
    JobClaimed,
    MasterRendered,
    PreviewRendered,
    PurgeCompleted,
    StepFailed,
    StoryPrepared,
    TargetPublishFailed,
    TargetPublishStarted,
    TargetPublishSucceeded,
    TargetPublishUnknown,
    WorkflowEvent,
)
from core.application.ports import ChannelReader, Clock, IdGenerator, WorkflowStore
from core.application.requests import RemixRequest, StoryRequest
from core.application.views import JobView, project_job
from core.domain.errors import (
    ApprovalPreconditionFailed,
    ChannelNotFound,
    DomainValidationError,
    InvalidTransition,
    JobNotFound,
    RevisionConflict,
)
from core.domain.models import (
    ApprovalSnapshot,
    ArtifactKind,
    ArtifactRef,
    JobFailure,
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    PublishTarget,
    RemixClipSnapshot,
    RemixSnapshot,
    RequestSnapshot,
    ResumeAction,
    StorySnapshot,
    TargetStatus,
    VideoJob,
    WorkflowDecision,
    WorkIntent,
    WorkKind,
)
from core.domain.policies import all_publish_targets_terminal, has_current_preview
from core.domain.state_machine import transition


class VideoWorkflow(Protocol):
    """Small external interface shared by UI and other callers."""

    def submit(self, request: StoryRequest | RemixRequest) -> JobView: ...

    def command(self, job_id: str, command: JobCommand) -> JobView: ...

    def get(self, job_id: str) -> JobView: ...


class WorkflowProcessor(Protocol):
    """Internal seam used only by trusted background workers."""

    def apply(self, job_id: str, event: WorkflowEvent) -> JobView: ...


class DefaultVideoWorkflow:
    """Coordinate requests while hiding persistence and infrastructure details."""

    def __init__(
        self,
        store: WorkflowStore,
        channels: ChannelReader,
        clock: Clock,
        ids: IdGenerator,
    ) -> None:
        self._store = store
        self._channels = channels
        self._clock = clock
        self._ids = ids

    def submit(self, request: StoryRequest | RemixRequest) -> JobView:
        """Create and enqueue a story or remix job."""
        existing = self._store.get_request_result(request.request_id)
        if existing is not None:
            return project_job(existing)

        channel = self._channels.get_snapshot(request.channel_id)
        if channel is None:
            raise ChannelNotFound(request.channel_id)

        now = self._clock.now()
        request_snapshot: RequestSnapshot
        if isinstance(request, StoryRequest):
            job_type = JobType.STORY
            work_kind = WorkKind.PREPARE_STORY
            request_snapshot = StorySnapshot(
                script=request.script,
                prompt=request.prompt,
            )
        else:
            job_type = JobType.REMIX
            work_kind = WorkKind.PREPARE_REMIX
            request_snapshot = RemixSnapshot(
                clips=tuple(
                    RemixClipSnapshot(
                        url=clip.url,
                        start_seconds=clip.start_seconds,
                        end_seconds=clip.end_seconds,
                        order=clip.order,
                        speed=clip.speed,
                        crop_mode=clip.crop_mode,
                        mirror=clip.mirror,
                    )
                    for clip in sorted(request.clips, key=lambda item: item.order)
                ),
                copyright_confirmed=request.copyright_confirmed,
            )
        job = VideoJob(
            job_id=self._ids.new_job_id(),
            request_id=request.request_id,
            channel_id=channel.channel_id,
            job_type=job_type,
            status=JobStatus.QUEUED,
            phase=JobPhase.SUBMIT,
            revision=0,
            content_revision=1,
            metadata_draft=request.metadata,
            created_at=now,
            updated_at=now,
            channel_revision=channel.revision,
            request_snapshot=request_snapshot,
            available_targets=channel.available_targets,
        )
        work = WorkIntent(
            job_id=job.job_id,
            kind=work_kind,
            content_revision=job.content_revision,
        )
        return project_job(self._store.create(job, work))

    def get(self, job_id: str) -> JobView:
        """Return a safe view or a typed missing-job error."""
        job = self._store.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        return project_job(job)

    def command(self, job_id: str, command: JobCommand) -> JobView:
        """Validate and atomically commit one user command."""
        prior = self._store.get_command_result(command.command_id)
        if prior is not None:
            if prior.job_id != job_id:
                raise DomainValidationError("Command ID belongs to another job")
            return project_job(prior)

        job = self._store.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        if job.revision != command.expected_revision:
            raise RevisionConflict(job_id)

        if isinstance(command, Approve):
            decision = self._approve(job, command)
        elif isinstance(command, UpdateMetadata):
            decision = self._update_metadata(job, command)
        elif isinstance(command, Regenerate):
            decision = self._regenerate(job, command)
        elif isinstance(command, Cancel):
            decision = self._cancel(job, command)
        elif isinstance(command, Retry):
            decision = self._retry(job, command)
        elif isinstance(command, SkipTarget):
            decision = self._skip_target(job, command)
        else:
            raise DomainValidationError("Unsupported workflow command")
        decision = replace(decision, actor_id=command.actor_id)
        committed = self._store.commit(decision, command.expected_revision)
        return project_job(committed)

    def _approve(self, job: VideoJob, command: Approve) -> WorkflowDecision:
        if job.status is not JobStatus.AWAITING_REVIEW:
            raise ApprovalPreconditionFailed("Job is not awaiting review")
        if not has_current_preview(job):
            raise ApprovalPreconditionFailed("Current content revision has no preview")
        if not command.metadata.title.strip():
            raise ApprovalPreconditionFailed("Approved metadata requires a title")
        if not command.target_platforms:
            raise ApprovalPreconditionFailed("At least one target platform is required")
        if len(command.target_platforms) != len(set(command.target_platforms)):
            raise ApprovalPreconditionFailed("Target platforms must be unique")
        unavailable = set(command.target_platforms) - set(job.available_targets)
        if unavailable:
            raise ApprovalPreconditionFailed(
                "Selected target is missing a channel credential reference"
            )

        updated = transition(
            job,
            JobStatus.RENDERING_MASTER,
            JobPhase.MASTER_RENDER,
            self._clock.now(),
        )
        snapshot = ApprovalSnapshot(
            content_revision=job.content_revision,
            channel_revision=job.channel_revision,
            metadata=command.metadata,
            target_platforms=command.target_platforms,
            approved_at=self._clock.now(),
        )
        updated = replace(
            updated,
            approval_snapshot=snapshot,
            publish_targets=tuple(
                PublishTarget(platform=platform)
                for platform in command.target_platforms
            ),
            progress=65,
        )
        work = WorkIntent(
            job_id=job.job_id,
            kind=WorkKind.RENDER_MASTER,
            content_revision=job.content_revision,
        )
        return WorkflowDecision(
            job=updated,
            work_intents=(work,),
            command_id=command.command_id,
        )

    def _update_metadata(
        self,
        job: VideoJob,
        command: UpdateMetadata,
    ) -> WorkflowDecision:
        if job.status is not JobStatus.AWAITING_REVIEW:
            raise DomainValidationError("Metadata can only change during review")
        if not command.metadata.title.strip():
            raise DomainValidationError("Metadata title is required")
        updated = replace(
            job,
            metadata_draft=command.metadata,
            revision=job.revision + 1,
            updated_at=self._clock.now(),
        )
        return WorkflowDecision(job=updated, command_id=command.command_id)

    def _regenerate(
        self,
        job: VideoJob,
        command: Regenerate,
    ) -> WorkflowDecision:
        if job.status is not JobStatus.AWAITING_REVIEW:
            raise DomainValidationError("Only a reviewable job can regenerate")
        if not command.changes.strip():
            raise DomainValidationError("Regeneration changes are required")
        updated = transition(
            job,
            JobStatus.QUEUED,
            JobPhase.SUBMIT,
            self._clock.now(),
        )
        updated = replace(
            updated,
            content_revision=job.content_revision + 1,
            artifacts=(),
            approval_snapshot=None,
            publish_targets=(),
            failure=None,
            prepared_story=None,
            regeneration_instructions=job.regeneration_instructions
            + (command.changes,),
        )
        kind = (
            WorkKind.PREPARE_STORY
            if job.job_type is JobType.STORY
            else WorkKind.PREPARE_REMIX
        )
        work = WorkIntent(job.job_id, kind, updated.content_revision)
        return WorkflowDecision(updated, (work,), command.command_id)

    def _cancel(self, job: VideoJob, command: Cancel) -> WorkflowDecision:
        if job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED, JobStatus.PURGING}:
            raise DomainValidationError("Job cannot be cancelled in its current state")
        if not command.reason.strip():
            raise DomainValidationError("Cancellation reason is required")
        updated = transition(
            job,
            JobStatus.PURGING,
            JobPhase.PURGE,
            self._clock.now(),
        )
        updated = replace(updated, terminal_after_purge=JobStatus.CANCELLED)
        work = WorkIntent(job.job_id, WorkKind.PURGE_JOB, job.content_revision)
        return WorkflowDecision(updated, (work,), command.command_id)

    def _retry(self, job: VideoJob, command: Retry) -> WorkflowDecision:
        if job.status is not JobStatus.FAILED or job.failure is None:
            raise DomainValidationError("Only a failed job can retry")
        if not job.failure.retryable:
            raise DomainValidationError("Failure is not retryable")
        expected_scope = RetryScope(job.failure.resume_action.value)
        if command.scope is not expected_scope:
            raise DomainValidationError(
                "Retry scope does not match the safe resume action"
            )

        if command.scope is RetryScope.PUBLISH:
            updated = transition(
                job,
                JobStatus.PUBLISHING,
                JobPhase.PUBLISH,
                self._clock.now(),
            )
            updated = replace(updated, failure=None)
            work = tuple(
                WorkIntent(
                    job.job_id,
                    WorkKind.RECONCILE_TARGET
                    if target.status is TargetStatus.UNKNOWN
                    else WorkKind.PUBLISH_TARGET,
                    job.content_revision,
                    platform=target.platform,
                )
                for target in job.publish_targets
                if target.status
                in {TargetStatus.UNKNOWN, TargetStatus.FAILED, TargetStatus.PENDING}
            )
        else:
            target_status, phase, kind = self._retry_destination(job, command.scope)
            updated = transition(job, target_status, phase, self._clock.now())
            updated = replace(updated, failure=None)
            work = (WorkIntent(job.job_id, kind, job.content_revision),)
        return WorkflowDecision(updated, work, command.command_id)

    def _retry_destination(
        self,
        job: VideoJob,
        scope: RetryScope,
    ) -> tuple[JobStatus, JobPhase, WorkKind]:
        if scope is RetryScope.PREPARE:
            kind = (
                WorkKind.PREPARE_STORY
                if job.job_type is JobType.STORY
                else WorkKind.PREPARE_REMIX
            )
            return JobStatus.QUEUED, JobPhase.SUBMIT, kind
        if scope is RetryScope.PREVIEW:
            return (
                JobStatus.RENDERING_PREVIEW,
                JobPhase.PREVIEW_RENDER,
                WorkKind.RENDER_PREVIEW,
            )
        if scope is RetryScope.MASTER:
            return (
                JobStatus.RENDERING_MASTER,
                JobPhase.MASTER_RENDER,
                WorkKind.RENDER_MASTER,
            )
        if scope is RetryScope.PURGE:
            return JobStatus.PURGING, JobPhase.PURGE, WorkKind.PURGE_JOB
        raise DomainValidationError("Unsupported retry scope")

    def _skip_target(
        self,
        job: VideoJob,
        command: SkipTarget,
    ) -> WorkflowDecision:
        if job.status not in {JobStatus.PUBLISHING, JobStatus.FAILED}:
            raise DomainValidationError("Targets can only be skipped during publishing")
        if not command.reason.strip():
            raise DomainValidationError("Skip reason is required")

        found = False
        targets: list[PublishTarget] = []
        for target in job.publish_targets:
            if target.platform is command.platform:
                found = True
                if target.status is TargetStatus.SUCCEEDED:
                    raise DomainValidationError("A successful target cannot be skipped")
                target = replace(
                    target,
                    status=TargetStatus.SKIPPED,
                    skip_reason=command.reason,
                )
            targets.append(target)
        if not found:
            raise DomainValidationError("Publish target is not part of this job")

        all_terminal = all_publish_targets_terminal(tuple(targets))
        work: tuple[WorkIntent, ...]
        if all_terminal:
            updated = transition(
                job,
                JobStatus.PURGING,
                JobPhase.PURGE,
                self._clock.now(),
            )
            work = (WorkIntent(job.job_id, WorkKind.PURGE_JOB, job.content_revision),)
        else:
            updated = replace(
                job,
                revision=job.revision + 1,
                updated_at=self._clock.now(),
            )
            work = ()
        updated = replace(updated, publish_targets=tuple(targets), failure=None)
        return WorkflowDecision(updated, work, command.command_id)


class DefaultWorkflowProcessor:
    """Apply trusted worker events without exposing infrastructure to callers."""

    def __init__(self, store: WorkflowStore, clock: Clock) -> None:
        self._store = store
        self._clock = clock

    def apply(self, job_id: str, event: WorkflowEvent) -> JobView:
        """Validate and atomically commit one worker event."""
        job = self._store.get(job_id)
        if job is None:
            raise JobNotFound(job_id)
        if job.revision != event.expected_revision:
            raise RevisionConflict(job_id)
        if (
            isinstance(
                event,
                (
                    TargetPublishStarted,
                    TargetPublishSucceeded,
                    TargetPublishFailed,
                    TargetPublishUnknown,
                ),
            )
            and job.status is not JobStatus.PUBLISHING
        ):
            raise InvalidTransition("Publish events require a PUBLISHING job")

        work: tuple[WorkIntent, ...] = ()
        if isinstance(event, JobClaimed):
            updated = transition(
                job,
                JobStatus.INGESTING,
                JobPhase.INGEST,
                self._clock.now(),
            )
            updated = replace(updated, progress=5)
        elif isinstance(event, StoryPrepared):
            if job.job_type is not JobType.STORY:
                raise DomainValidationError("Story content requires a story job")
            if event.content_revision != job.content_revision:
                raise DomainValidationError("Prepared story content revision is stale")
            if job.status is JobStatus.QUEUED:
                updated = transition(
                    job,
                    JobStatus.INGESTING,
                    JobPhase.STORY_PREPARATION,
                    self._clock.now(),
                )
            elif job.status is JobStatus.INGESTING:
                updated = job
            else:
                raise InvalidTransition("Story preparation requires queued ingestion")
            updated = transition(
                updated,
                JobStatus.RENDERING_PREVIEW,
                JobPhase.PREVIEW_RENDER,
                self._clock.now(),
            )
            updated = replace(
                updated,
                prepared_story=event.script_draft,
                progress=45,
            )
            work = (
                WorkIntent(
                    job_id=job.job_id,
                    kind=WorkKind.RENDER_PREVIEW,
                    content_revision=job.content_revision,
                ),
            )
        elif isinstance(event, IngestionCompleted):
            if (
                event.content_revision is not None
                and event.content_revision != job.content_revision
            ):
                raise DomainValidationError("Ingested content revision is stale")
            if job.status is JobStatus.QUEUED:
                updated = transition(
                    job,
                    JobStatus.INGESTING,
                    JobPhase.REMIX_PREPARATION,
                    self._clock.now(),
                )
            elif job.status is JobStatus.INGESTING:
                updated = job
            else:
                raise InvalidTransition(
                    "Ingestion completion requires queued ingestion"
                )
            updated = transition(
                updated,
                JobStatus.RENDERING_PREVIEW,
                JobPhase.PREVIEW_RENDER,
                self._clock.now(),
            )
            updated = replace(updated, progress=45)
            work = (
                WorkIntent(
                    job_id=job.job_id,
                    kind=WorkKind.RENDER_PREVIEW,
                    content_revision=job.content_revision,
                ),
            )
        elif isinstance(event, PreviewRendered):
            if event.content_revision != job.content_revision:
                raise DomainValidationError("Preview content revision is stale")
            if any(
                artifact.content_revision != job.content_revision
                or artifact.kind in {ArtifactKind.PREVIEW, ArtifactKind.MASTER}
                for artifact in event.supporting_artifacts
            ):
                raise DomainValidationError("Preview supporting artifact is invalid")
            artifact_ids = [
                event.artifact_id,
                *(item.artifact_id for item in event.supporting_artifacts),
            ]
            if len(artifact_ids) != len(set(artifact_ids)):
                raise DomainValidationError("Preview artifact IDs must be unique")
            updated = transition(
                job,
                JobStatus.AWAITING_REVIEW,
                JobPhase.PREVIEW_RENDER,
                self._clock.now(),
            )
            updated = replace(
                updated,
                artifacts=updated.artifacts
                + (
                    ArtifactRef(
                        artifact_id=event.artifact_id,
                        kind=ArtifactKind.PREVIEW,
                        content_revision=event.content_revision,
                    ),
                )
                + event.supporting_artifacts,
                progress=60,
            )
        elif isinstance(event, MasterRendered):
            if event.content_revision != job.content_revision:
                raise DomainValidationError("Master content revision is stale")
            approval = job.approval_snapshot
            if (
                approval is None
                or approval.content_revision != job.content_revision
                or approval.channel_revision != job.channel_revision
            ):
                raise DomainValidationError("Master approval snapshot is invalid")
            if any(
                artifact.artifact_id == event.artifact_id for artifact in job.artifacts
            ):
                raise DomainValidationError("Master artifact already exists")
            updated = transition(
                job,
                JobStatus.PUBLISHING,
                JobPhase.PUBLISH,
                self._clock.now(),
            )
            updated = replace(
                updated,
                artifacts=updated.artifacts
                + (
                    ArtifactRef(
                        artifact_id=event.artifact_id,
                        kind=ArtifactKind.MASTER,
                        content_revision=job.content_revision,
                    ),
                ),
                progress=85,
            )
            work = tuple(
                WorkIntent(
                    job.job_id,
                    WorkKind.PUBLISH_TARGET,
                    job.content_revision,
                    platform=target.platform,
                )
                for target in job.publish_targets
                if target.status is TargetStatus.PENDING
            )
        elif isinstance(event, TargetPublishStarted):
            targets = self._update_target(
                job,
                event.platform,
                lambda target: replace(target, status=TargetStatus.UPLOADING),
            )
            updated = self._mutate(job, publish_targets=targets)
        elif isinstance(event, TargetPublishSucceeded):
            targets = self._update_target(
                job,
                event.platform,
                lambda target: replace(
                    target,
                    status=TargetStatus.SUCCEEDED,
                    external_video_id=event.external_video_id,
                    public_url=event.public_url,
                    last_error_code=None,
                ),
            )
            all_terminal = all_publish_targets_terminal(targets)
            if all_terminal:
                updated = transition(
                    job,
                    JobStatus.PURGING,
                    JobPhase.PURGE,
                    self._clock.now(),
                )
                work = (
                    WorkIntent(
                        job.job_id,
                        WorkKind.PURGE_JOB,
                        job.content_revision,
                    ),
                )
                updated = replace(updated, progress=95)
            else:
                succeeded = sum(
                    target.status is TargetStatus.SUCCEEDED for target in targets
                )
                progress = 85 + int(9 * succeeded / max(1, len(targets)))
                updated = self._mutate(job, progress=progress)
            updated = replace(updated, publish_targets=targets, failure=None)
        elif isinstance(event, TargetPublishFailed):
            targets = self._update_target(
                job,
                event.platform,
                lambda target: replace(
                    target,
                    status=TargetStatus.FAILED,
                    last_error_code=event.failure.code,
                ),
            )
            updated = transition(
                job,
                JobStatus.FAILED,
                JobPhase.PUBLISH,
                self._clock.now(),
            )
            updated = replace(
                updated,
                publish_targets=targets,
                failure=event.failure,
            )
        elif isinstance(event, TargetPublishUnknown):
            targets = self._update_target(
                job,
                event.platform,
                lambda target: replace(
                    target,
                    status=TargetStatus.UNKNOWN,
                    last_error_code="PUBLISH_UNKNOWN",
                ),
            )
            failure = JobFailure(
                code="PUBLISH_UNKNOWN",
                phase=JobPhase.PUBLISH,
                message_safe="Publish result is unknown; reconcile before retry.",
                retryable=True,
                resume_action=ResumeAction.PUBLISH,
                target_platform=event.platform,
                diagnostic_ref=event.diagnostic_ref,
            )
            updated = transition(
                job,
                JobStatus.FAILED,
                JobPhase.PUBLISH,
                self._clock.now(),
            )
            updated = replace(updated, publish_targets=targets, failure=failure)
        elif isinstance(event, PurgeCompleted):
            if event.media_bytes < 0:
                raise DomainValidationError("Remaining media bytes cannot be negative")
            if event.media_bytes == 0:
                updated = transition(
                    job,
                    job.terminal_after_purge,
                    JobPhase.PURGE,
                    self._clock.now(),
                )
                updated = replace(updated, artifacts=(), failure=None)
                updated = replace(updated, progress=100)
            else:
                failure = JobFailure(
                    code="PURGE_INCOMPLETE",
                    phase=JobPhase.PURGE,
                    message_safe="Media artifacts remain after cleanup.",
                    retryable=True,
                    resume_action=ResumeAction.PURGE,
                )
                updated = transition(
                    job,
                    JobStatus.FAILED,
                    JobPhase.PURGE,
                    self._clock.now(),
                )
                updated = replace(updated, failure=failure)
        elif isinstance(event, StepFailed):
            updated = transition(
                job,
                JobStatus.FAILED,
                event.failure.phase,
                self._clock.now(),
            )
            updated = replace(updated, failure=event.failure)
        else:
            raise DomainValidationError("Unsupported workflow event")

        committed = self._store.commit(
            WorkflowDecision(job=updated, work_intents=work),
            event.expected_revision,
        )
        return project_job(committed)

    def _mutate(self, job: VideoJob, **changes: Any) -> VideoJob:
        return replace(
            job,
            revision=job.revision + 1,
            updated_at=self._clock.now(),
            **changes,
        )

    def _update_target(
        self,
        job: VideoJob,
        platform: Platform,
        update: Callable[[PublishTarget], PublishTarget],
    ) -> tuple[PublishTarget, ...]:
        found = False
        targets: list[PublishTarget] = []
        for target in job.publish_targets:
            if target.platform is platform:
                found = True
                if target.status is TargetStatus.SUCCEEDED:
                    raise DomainValidationError("Successful target is immutable")
                target = update(target)
            targets.append(target)
        if not found:
            raise DomainValidationError("Publish target is not part of this job")
        return tuple(targets)
