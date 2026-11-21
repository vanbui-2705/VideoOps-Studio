"""Durable logical publish-operation values and persistence seam."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Protocol

from core.domain.errors import DomainValidationError
from core.domain.models import Platform

_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class PublishAttemptStatus(str, Enum):
    STARTED = "STARTED"
    PROCESSING = "PROCESSING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True, slots=True)
class PublishAttempt:
    job_id: str
    platform: Platform
    attempt_number: int
    status: PublishAttemptStatus
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    provider_operation_id: str | None = None
    external_id: str | None = None
    public_url: str | None = None
    error_code: str | None = None
    retry_after: datetime | None = None
    completed_at: datetime | None = None

    def __post_init__(self) -> None:
        timestamps = (
            self.created_at,
            self.updated_at,
            self.retry_after,
            self.completed_at,
        )
        if (
            not self.job_id
            or self.attempt_number < 1
            or not _SHA256.fullmatch(self.idempotency_key)
            or any(value is not None and value.tzinfo is None for value in timestamps)
        ):
            raise DomainValidationError("Publish attempt is invalid")


class PublishAttemptStore(Protocol):
    def get(self, idempotency_key: str) -> PublishAttempt | None: ...

    def begin_or_get(
        self,
        job_id: str,
        platform: Platform,
        idempotency_key: str,
        now: datetime,
        *,
        restart: bool = False,
    ) -> PublishAttempt: ...

    def update(
        self,
        idempotency_key: str,
        status: PublishAttemptStatus,
        now: datetime,
        *,
        provider_operation_id: str | None = None,
        external_id: str | None = None,
        public_url: str | None = None,
        error_code: str | None = None,
        retry_after: datetime | None = None,
    ) -> PublishAttempt: ...
