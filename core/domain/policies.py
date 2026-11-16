"""Reusable workflow policies derived from immutable job state."""

from __future__ import annotations

from core.domain.models import (
    ArtifactKind,
    JobStatus,
    PublishTarget,
    TargetStatus,
    VideoJob,
)


def has_current_preview(job: VideoJob) -> bool:
    """Return whether the active content revision has a reviewable preview."""
    return any(
        artifact.kind is ArtifactKind.PREVIEW
        and artifact.content_revision == job.content_revision
        for artifact in job.artifacts
    )


def all_publish_targets_terminal(targets: tuple[PublishTarget, ...]) -> bool:
    """Return whether every selected target is successful or explicitly skipped."""
    return bool(targets) and all(
        target.status in {TargetStatus.SUCCEEDED, TargetStatus.SKIPPED}
        for target in targets
    )


def allowed_actions(job: VideoJob) -> tuple[str, ...]:
    """Derive the commands an external caller may currently offer."""
    if job.status in {
        JobStatus.QUEUED,
        JobStatus.INGESTING,
        JobStatus.RENDERING_PREVIEW,
    }:
        return ("cancel",)
    if job.status is JobStatus.AWAITING_REVIEW:
        return ("update_metadata", "approve", "regenerate", "cancel")
    if job.status is JobStatus.FAILED:
        actions: list[str] = ["cancel"]
        if job.failure and job.failure.retryable:
            actions.insert(0, "retry")
        if any(
            target.status in {TargetStatus.FAILED, TargetStatus.UNKNOWN}
            for target in job.publish_targets
        ):
            actions.append("skip_target")
        return tuple(actions)
    return ()
