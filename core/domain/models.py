"""Typed domain state for the video workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from core.domain.story_models import ScriptDraft


class JobType(str, Enum):
    """Supported production paths."""

    STORY = "STORY"
    REMIX = "REMIX"


class JobStatus(str, Enum):
    """Persisted lifecycle states for a video job."""

    QUEUED = "QUEUED"
    INGESTING = "INGESTING"
    RENDERING_PREVIEW = "RENDERING_PREVIEW"
    AWAITING_REVIEW = "AWAITING_REVIEW"
    RENDERING_MASTER = "RENDERING_MASTER"
    PUBLISHING = "PUBLISHING"
    PURGING = "PURGING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class JobPhase(str, Enum):
    """The operational phase associated with a status or failure."""

    SUBMIT = "SUBMIT"
    INGEST = "INGEST"
    STORY_PREPARATION = "STORY_PREPARATION"
    REMIX_PREPARATION = "REMIX_PREPARATION"
    PREVIEW_RENDER = "PREVIEW_RENDER"
    MASTER_RENDER = "MASTER_RENDER"
    PUBLISH = "PUBLISH"
    PURGE = "PURGE"


class WorkKind(str, Enum):
    """Typed work scheduled for an infrastructure worker."""

    PREPARE_STORY = "PREPARE_STORY"
    PREPARE_REMIX = "PREPARE_REMIX"
    RENDER_PREVIEW = "RENDER_PREVIEW"
    RENDER_MASTER = "RENDER_MASTER"
    PUBLISH_TARGET = "PUBLISH_TARGET"
    RECONCILE_TARGET = "RECONCILE_TARGET"
    PURGE_JOB = "PURGE_JOB"


class ArtifactKind(str, Enum):
    """Artifact roles used by workflow policies."""

    VOICE = "VOICE"
    SUBTITLE = "SUBTITLE"
    VISUAL_SOURCE = "VISUAL_SOURCE"
    PREVIEW = "PREVIEW"
    MASTER = "MASTER"


class Platform(str, Enum):
    """Supported publishing destinations."""

    YOUTUBE = "YOUTUBE"
    TIKTOK = "TIKTOK"


class TargetStatus(str, Enum):
    """Lifecycle of one platform publication."""

    PENDING = "PENDING"
    UPLOADING = "UPLOADING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"
    SKIPPED = "SKIPPED"


class ResumeAction(str, Enum):
    """Safe recovery point selected after a failure."""

    PREPARE = "PREPARE"
    PREVIEW = "PREVIEW"
    MASTER = "MASTER"
    PUBLISH = "PUBLISH"
    PURGE = "PURGE"


@dataclass(frozen=True, slots=True)
class VideoMetadata:
    """Metadata edited before approval and frozen for publication."""

    title: str = ""
    description: str = ""
    tags: tuple[str, ...] = ()
    category_id: str = "28"
    privacy: str = "private"


@dataclass(frozen=True, slots=True)
class WorkIntent:
    """A durable request for infrastructure work."""

    job_id: str
    kind: WorkKind
    content_revision: int
    platform: Platform | None = None


@dataclass(frozen=True, slots=True)
class ArtifactRef:
    """Safe manifest reference without an absolute filesystem path."""

    artifact_id: str
    kind: ArtifactKind
    content_revision: int


@dataclass(frozen=True, slots=True)
class ApprovalSnapshot:
    """Immutable content and metadata selected at the review gate."""

    content_revision: int
    channel_revision: int
    metadata: VideoMetadata
    target_platforms: tuple[Platform, ...]
    approved_at: datetime


@dataclass(frozen=True, slots=True)
class PublishTarget:
    """State for one logical publication destination."""

    platform: Platform
    status: TargetStatus = TargetStatus.PENDING
    external_video_id: str | None = None
    public_url: str | None = None
    last_error_code: str | None = None
    skip_reason: str | None = None


@dataclass(frozen=True, slots=True)
class JobFailure:
    """Sanitized failure and its recovery policy."""

    code: str
    phase: JobPhase
    message_safe: str
    retryable: bool
    resume_action: ResumeAction
    retry_after: datetime | None = None
    target_platform: Platform | None = None
    diagnostic_ref: str | None = None


@dataclass(frozen=True, slots=True)
class StorySnapshot:
    """Durable story input consumed later by a worker."""

    script: str | None
    prompt: str | None


@dataclass(frozen=True, slots=True)
class RemixClipSnapshot:
    """Durable normalized clip input for a remix job."""

    url: str
    start_seconds: float
    end_seconds: float
    order: int
    speed: float
    crop_mode: str = "fill"
    mirror: bool = False


@dataclass(frozen=True, slots=True)
class RemixSnapshot:
    """Durable ordered inputs consumed later by a remix worker."""

    clips: tuple[RemixClipSnapshot, ...]
    copyright_confirmed: bool


RequestSnapshot = StorySnapshot | RemixSnapshot


@dataclass(frozen=True, slots=True)
class VideoJob:
    """Immutable aggregate persisted by the workflow store."""

    job_id: str
    request_id: str
    channel_id: str
    job_type: JobType
    status: JobStatus
    phase: JobPhase
    revision: int
    content_revision: int
    metadata_draft: VideoMetadata
    created_at: datetime
    updated_at: datetime
    artifacts: tuple[ArtifactRef, ...] = ()
    channel_revision: int = 0
    approval_snapshot: ApprovalSnapshot | None = None
    publish_targets: tuple[PublishTarget, ...] = ()
    failure: JobFailure | None = None
    terminal_after_purge: JobStatus = JobStatus.COMPLETED
    request_snapshot: RequestSnapshot | None = None
    progress: int = 0
    available_targets: tuple[Platform, ...] = ()
    regeneration_instructions: tuple[str, ...] = ()
    prepared_story: ScriptDraft | None = None


@dataclass(frozen=True, slots=True)
class WorkflowDecision:
    """State and work committed atomically by a persistence adapter."""

    job: VideoJob
    work_intents: tuple[WorkIntent, ...] = ()
    command_id: str | None = None
