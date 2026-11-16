"""Typed events emitted by trusted infrastructure workers."""

from __future__ import annotations

from dataclasses import dataclass

from core.domain.models import JobFailure, Platform


@dataclass(frozen=True, slots=True)
class JobClaimed:
    expected_revision: int


@dataclass(frozen=True, slots=True)
class IngestionCompleted:
    expected_revision: int


@dataclass(frozen=True, slots=True)
class PreviewRendered:
    expected_revision: int
    artifact_id: str
    content_revision: int


@dataclass(frozen=True, slots=True)
class MasterRendered:
    expected_revision: int
    artifact_id: str


@dataclass(frozen=True, slots=True)
class TargetPublishStarted:
    expected_revision: int
    platform: Platform


@dataclass(frozen=True, slots=True)
class TargetPublishSucceeded:
    expected_revision: int
    platform: Platform
    external_video_id: str
    public_url: str


@dataclass(frozen=True, slots=True)
class TargetPublishFailed:
    expected_revision: int
    platform: Platform
    failure: JobFailure


@dataclass(frozen=True, slots=True)
class TargetPublishUnknown:
    expected_revision: int
    platform: Platform
    diagnostic_ref: str


@dataclass(frozen=True, slots=True)
class PurgeCompleted:
    expected_revision: int
    media_bytes: int


@dataclass(frozen=True, slots=True)
class StepFailed:
    expected_revision: int
    failure: JobFailure


WorkflowEvent = (
    JobClaimed
    | IngestionCompleted
    | PreviewRendered
    | MasterRendered
    | TargetPublishStarted
    | TargetPublishSucceeded
    | TargetPublishFailed
    | TargetPublishUnknown
    | PurgeCompleted
    | StepFailed
)
