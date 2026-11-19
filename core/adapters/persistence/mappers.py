"""Lossless serialization between immutable domain values and JSONB snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from core.adapters.persistence.story_mappers import story_from_dict, story_to_dict
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
    ResumeAction,
    StorySnapshot,
    TargetStatus,
    VideoJob,
    VideoMetadata,
)


def _dt(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _metadata(value: VideoMetadata) -> dict[str, Any]:
    return {
        "title": value.title,
        "description": value.description,
        "tags": list(value.tags),
        "category_id": value.category_id,
        "privacy": value.privacy,
    }


def _metadata_from(data: dict[str, Any]) -> VideoMetadata:
    return VideoMetadata(
        title=data["title"],
        description=data["description"],
        tags=tuple(data["tags"]),
        category_id=data["category_id"],
        privacy=data["privacy"],
    )


def job_to_dict(job: VideoJob) -> dict[str, Any]:
    request: dict[str, Any] | None = None
    if isinstance(job.request_snapshot, StorySnapshot):
        request = {
            "type": "STORY",
            "script": job.request_snapshot.script,
            "prompt": job.request_snapshot.prompt,
        }
    elif isinstance(job.request_snapshot, RemixSnapshot):
        request = {
            "type": "REMIX",
            "copyright_confirmed": job.request_snapshot.copyright_confirmed,
            "clips": [
                {
                    "url": clip.url,
                    "start_seconds": clip.start_seconds,
                    "end_seconds": clip.end_seconds,
                    "order": clip.order,
                    "speed": clip.speed,
                }
                for clip in job.request_snapshot.clips
            ],
        }
    approval = None
    if job.approval_snapshot:
        approval = {
            "content_revision": job.approval_snapshot.content_revision,
            "channel_revision": job.approval_snapshot.channel_revision,
            "metadata": _metadata(job.approval_snapshot.metadata),
            "target_platforms": [
                p.value for p in job.approval_snapshot.target_platforms
            ],
            "approved_at": _dt(job.approval_snapshot.approved_at),
        }
    failure = None
    if job.failure:
        failure = {
            "code": job.failure.code,
            "phase": job.failure.phase.value,
            "message_safe": job.failure.message_safe,
            "retryable": job.failure.retryable,
            "resume_action": job.failure.resume_action.value,
            "retry_after": _dt(job.failure.retry_after),
            "target_platform": (
                job.failure.target_platform.value
                if job.failure.target_platform
                else None
            ),
            "diagnostic_ref": job.failure.diagnostic_ref,
        }
    return {
        "job_id": job.job_id,
        "request_id": job.request_id,
        "channel_id": job.channel_id,
        "job_type": job.job_type.value,
        "status": job.status.value,
        "phase": job.phase.value,
        "revision": job.revision,
        "content_revision": job.content_revision,
        "metadata_draft": _metadata(job.metadata_draft),
        "created_at": _dt(job.created_at),
        "updated_at": _dt(job.updated_at),
        "artifacts": [
            {
                "artifact_id": item.artifact_id,
                "kind": item.kind.value,
                "content_revision": item.content_revision,
            }
            for item in job.artifacts
        ],
        "channel_revision": job.channel_revision,
        "approval_snapshot": approval,
        "publish_targets": [
            {
                "platform": item.platform.value,
                "status": item.status.value,
                "external_video_id": item.external_video_id,
                "public_url": item.public_url,
                "last_error_code": item.last_error_code,
                "skip_reason": item.skip_reason,
            }
            for item in job.publish_targets
        ],
        "failure": failure,
        "terminal_after_purge": job.terminal_after_purge.value,
        "request_snapshot": request,
        "progress": job.progress,
        "available_targets": [p.value for p in job.available_targets],
        "regeneration_instructions": list(job.regeneration_instructions),
        "prepared_story": (
            story_to_dict(job.prepared_story) if job.prepared_story else None
        ),
    }


def job_from_dict(data: dict[str, Any]) -> VideoJob:
    request_data = data.get("request_snapshot")
    request = None
    if request_data and request_data["type"] == "STORY":
        request = StorySnapshot(request_data.get("script"), request_data.get("prompt"))
    elif request_data:
        request = RemixSnapshot(
            clips=tuple(RemixClipSnapshot(**clip) for clip in request_data["clips"]),
            copyright_confirmed=request_data["copyright_confirmed"],
        )
    approval_data = data.get("approval_snapshot")
    approval = None
    if approval_data:
        approval = ApprovalSnapshot(
            content_revision=approval_data["content_revision"],
            channel_revision=approval_data["channel_revision"],
            metadata=_metadata_from(approval_data["metadata"]),
            target_platforms=tuple(
                Platform(value) for value in approval_data["target_platforms"]
            ),
            approved_at=datetime.fromisoformat(approval_data["approved_at"]),
        )
    failure_data = data.get("failure")
    failure = None
    if failure_data:
        failure = JobFailure(
            code=failure_data["code"],
            phase=JobPhase(failure_data["phase"]),
            message_safe=failure_data["message_safe"],
            retryable=failure_data["retryable"],
            resume_action=ResumeAction(failure_data["resume_action"]),
            retry_after=(
                datetime.fromisoformat(failure_data["retry_after"])
                if failure_data.get("retry_after")
                else None
            ),
            target_platform=(
                Platform(failure_data["target_platform"])
                if failure_data.get("target_platform")
                else None
            ),
            diagnostic_ref=failure_data.get("diagnostic_ref"),
        )
    return VideoJob(
        job_id=data["job_id"],
        request_id=data["request_id"],
        channel_id=data["channel_id"],
        job_type=JobType(data["job_type"]),
        status=JobStatus(data["status"]),
        phase=JobPhase(data["phase"]),
        revision=data["revision"],
        content_revision=data["content_revision"],
        metadata_draft=_metadata_from(data["metadata_draft"]),
        created_at=datetime.fromisoformat(data["created_at"]),
        updated_at=datetime.fromisoformat(data["updated_at"]),
        artifacts=tuple(
            ArtifactRef(
                item["artifact_id"],
                ArtifactKind(item["kind"]),
                item["content_revision"],
            )
            for item in data["artifacts"]
        ),
        channel_revision=data["channel_revision"],
        approval_snapshot=approval,
        publish_targets=tuple(
            PublishTarget(
                platform=Platform(item["platform"]),
                status=TargetStatus(item["status"]),
                external_video_id=item.get("external_video_id"),
                public_url=item.get("public_url"),
                last_error_code=item.get("last_error_code"),
                skip_reason=item.get("skip_reason"),
            )
            for item in data["publish_targets"]
        ),
        failure=failure,
        terminal_after_purge=JobStatus(data["terminal_after_purge"]),
        request_snapshot=request,
        progress=data["progress"],
        available_targets=tuple(Platform(value) for value in data["available_targets"]),
        regeneration_instructions=tuple(data["regeneration_instructions"]),
        prepared_story=(
            story_from_dict(data["prepared_story"])
            if data.get("prepared_story")
            else None
        ),
    )
