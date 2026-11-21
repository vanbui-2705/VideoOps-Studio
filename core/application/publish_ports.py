"""Provider-neutral publishing contracts."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

from core.domain.errors import DomainValidationError
from core.domain.models import Platform, VideoMetadata

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def logical_publish_key(
    job_id: str,
    platform: Platform,
    content_revision: int,
    channel_revision: int,
) -> str:
    if not job_id or content_revision < 1 or channel_revision < 1:
        raise DomainValidationError("Publish identity is invalid")
    value = f"{job_id}:{platform.value}:{content_revision}:{channel_revision}"
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class PublishRequest:
    job_id: str
    platform: Platform
    idempotency_key: str
    master_path: Path
    master_checksum: str
    master_size: int
    metadata: VideoMetadata
    credential: object
    duration_ms: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.job_id
            or not _SHA256.fullmatch(self.idempotency_key)
            or not _SHA256.fullmatch(self.master_checksum)
            or self.master_size <= 0
            or (self.duration_ms is not None and self.duration_ms <= 0)
            or not self.metadata.title.strip()
        ):
            raise DomainValidationError("Publish request is invalid")


@dataclass(frozen=True, slots=True)
class PublishReceipt:
    external_video_id: str
    public_url: str
    provider_operation_id: str | None
    confirmed_at: datetime

    def __post_init__(self) -> None:
        parsed = urlparse(self.public_url)
        if (
            not self.external_video_id.strip()
            or parsed.scheme != "https"
            or not parsed.hostname
            or self.confirmed_at.tzinfo is None
        ):
            raise DomainValidationError("Publish receipt is invalid")


@dataclass(frozen=True, slots=True)
class PublishSucceeded:
    receipt: PublishReceipt


@dataclass(frozen=True, slots=True)
class PublishFailed:
    code: str
    retryable: bool
    retry_after: datetime | None = None

    def __post_init__(self) -> None:
        if not self.code.strip() or (
            self.retry_after is not None and self.retry_after.tzinfo is None
        ):
            raise DomainValidationError("Publish failure is invalid")


@dataclass(frozen=True, slots=True)
class PublishUnknown:
    diagnostic_ref: str
    provider_operation_id: str | None = None

    def __post_init__(self) -> None:
        if not self.diagnostic_ref.strip():
            raise DomainValidationError("Publish diagnostic reference is required")


@dataclass(frozen=True, slots=True)
class PublishProcessing:
    provider_operation_id: str
    retry_at: datetime

    def __post_init__(self) -> None:
        if not self.provider_operation_id.strip() or self.retry_at.tzinfo is None:
            raise DomainValidationError("Publish processing checkpoint is invalid")


PublishOutcome = PublishSucceeded | PublishFailed | PublishUnknown | PublishProcessing


class Publisher(Protocol):
    platform: Platform

    def publish(
        self,
        request: PublishRequest,
        *,
        heartbeat: Callable[[], None] | None = None,
    ) -> PublishOutcome: ...

    def reconcile(
        self,
        request: PublishRequest,
        provider_operation_id: str | None,
        *,
        heartbeat: Callable[[], None] | None = None,
    ) -> PublishOutcome: ...
