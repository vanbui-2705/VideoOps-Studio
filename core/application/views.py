"""Safe projections returned to external callers."""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.models import (
    JobPhase,
    JobStatus,
    JobType,
    Platform,
    TargetStatus,
    VideoJob,
    VideoMetadata,
)
from core.domain.policies import allowed_actions


@dataclass(frozen=True, slots=True)
class PublishTargetView:
    platform: Platform
    status: TargetStatus
    external_video_id: str | None
    public_url: str | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class FailureView:
    code: str
    phase: JobPhase
    message: str
    retryable: bool
    target_platform: Platform | None


@dataclass(frozen=True, slots=True)
class JobView:
    """Browser-safe view of a workflow aggregate."""

    job_id: str
    channel_id: str
    job_type: JobType
    status: JobStatus
    phase: JobPhase
    revision: int
    content_revision: int
    metadata: VideoMetadata
    allowed_actions: tuple[str, ...]
    preview_artifact_id: str | None
    available_targets: tuple[Platform, ...]
    publish_targets: tuple[PublishTargetView, ...]
    failure: FailureView | None
    progress: int


def project_job(job: VideoJob) -> JobView:
    """Project internal state without paths, credentials, or provider payloads."""
    visible_metadata = (
        job.approval_snapshot.metadata
        if job.approval_snapshot is not None
        else job.metadata_draft
    )
    preview_artifact_id = next(
        (
            artifact.artifact_id
            for artifact in job.artifacts
            if artifact.kind.value == "PREVIEW"
            and artifact.content_revision == job.content_revision
        ),
        None,
    )
    job_actions = allowed_actions(job)
    targets = tuple(
        PublishTargetView(
            platform=target.platform,
            status=target.status,
            external_video_id=target.external_video_id,
            public_url=target.public_url,
            last_error_code=target.last_error_code,
        )
        for target in job.publish_targets
    )
    failure = (
        FailureView(
            code=job.failure.code,
            phase=job.failure.phase,
            message=job.failure.message_safe,
            retryable=job.failure.retryable,
            target_platform=job.failure.target_platform,
        )
        if job.failure
        else None
    )
    return JobView(
        job_id=job.job_id,
        channel_id=job.channel_id,
        job_type=job.job_type,
        status=job.status,
        phase=job.phase,
        revision=job.revision,
        content_revision=job.content_revision,
        metadata=visible_metadata,
        allowed_actions=job_actions,
        preview_artifact_id=preview_artifact_id,
        available_targets=job.available_targets,
        publish_targets=targets,
        failure=failure,
        progress=job.progress,
    )
