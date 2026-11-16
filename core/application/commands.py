"""Typed commands accepted by VideoWorkflow.command."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from core.domain.models import Platform, VideoMetadata


@dataclass(frozen=True, slots=True)
class Approve:
    """Freeze a reviewed revision and schedule its master render."""

    command_id: str
    expected_revision: int
    metadata: VideoMetadata
    target_platforms: tuple[Platform, ...]


@dataclass(frozen=True, slots=True)
class UpdateMetadata:
    command_id: str
    expected_revision: int
    metadata: VideoMetadata


@dataclass(frozen=True, slots=True)
class Regenerate:
    command_id: str
    expected_revision: int
    changes: str


@dataclass(frozen=True, slots=True)
class Cancel:
    command_id: str
    expected_revision: int
    reason: str


class RetryScope(str, Enum):
    PREPARE = "PREPARE"
    PREVIEW = "PREVIEW"
    MASTER = "MASTER"
    PUBLISH = "PUBLISH"
    PURGE = "PURGE"


@dataclass(frozen=True, slots=True)
class Retry:
    command_id: str
    expected_revision: int
    scope: RetryScope


@dataclass(frozen=True, slots=True)
class SkipTarget:
    command_id: str
    expected_revision: int
    platform: Platform
    reason: str


JobCommand = Approve | UpdateMetadata | Regenerate | Cancel | Retry | SkipTarget
