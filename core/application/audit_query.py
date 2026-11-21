"""Authorized, bounded audit query interface."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from core.application.security import Action, AuthorizationPolicy, Principal


@dataclass(frozen=True, slots=True)
class AuditRecord:
    job_id: str | None
    actor_type: str
    actor_id: str | None
    action: str
    metadata: dict
    created_at: datetime


@dataclass(frozen=True, slots=True)
class AuditQuery:
    job_id: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    channel_id: str | None = None
    platform: str | None = None
    action: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    page: int = 1
    page_size: int = 50

    def __post_init__(self) -> None:
        if self.page < 1 or not 1 <= self.page_size <= 100:
            raise ValueError("Audit pagination is invalid")


class AuditReader(Protocol):
    def search(self, query: AuditQuery) -> tuple[AuditRecord, ...]: ...


class AuditQueryService:
    def __init__(
        self,
        reader: AuditReader,
        principal: Principal,
        authorization: AuthorizationPolicy,
    ) -> None:
        self._reader = reader
        self._principal = principal
        self._authorization = authorization

    def search(self, query: AuditQuery) -> tuple[AuditRecord, ...]:
        self._authorization.require(self._principal, Action.READ_AUDIT)
        return self._reader.search(query)
