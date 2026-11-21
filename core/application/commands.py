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
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class UpdateMetadata:
    command_id: str
    expected_revision: int
    metadata: VideoMetadata
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class Regenerate:
    command_id: str
    expected_revision: int
    changes: str
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class Cancel:
    command_id: str
    expected_revision: int
    reason: str
    actor_id: str | None = None


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
    actor_id: str | None = None


@dataclass(frozen=True, slots=True)
class SkipTarget:
    command_id: str
    expected_revision: int
    platform: Platform
    reason: str
    actor_id: str | None = None


JobCommand = Approve | UpdateMetadata | Regenerate | Cancel | Retry | SkipTarget
