"""PostgreSQL persistence for one logical publication per target."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from core.adapters.persistence.models import PublishAttemptRow
from core.application.publish_attempts import PublishAttempt, PublishAttemptStatus
from core.domain.errors import DomainValidationError
from core.domain.models import Platform


class PostgresPublishAttemptStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def get(self, idempotency_key: str) -> PublishAttempt | None:
        with self._sessions() as session:
            row = session.scalar(
                select(PublishAttemptRow).where(
                    PublishAttemptRow.idempotency_key == idempotency_key
                )
            )
            return self._project(row) if row else None

    def begin_or_get(
        self,
        job_id: str,
        platform: Platform,
        idempotency_key: str,
        now: datetime,
        *,
        restart: bool = False,
    ) -> PublishAttempt:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(PublishAttemptRow)
                .where(PublishAttemptRow.idempotency_key == idempotency_key)
                .with_for_update()
            )
            if row is None:
                row = PublishAttemptRow(
                    job_id=job_id,
                    platform=platform.value,
                    attempt_number=1,
                    status=PublishAttemptStatus.STARTED.value,
                    idempotency_key=idempotency_key,
                    response_snapshot=None,
                    created_at=now,
                    updated_at=now,
                )
                session.add(row)
            else:
                if row.job_id != job_id or row.platform != platform.value:
                    raise DomainValidationError("Publish key belongs to another target")
                if restart and row.status == PublishAttemptStatus.FAILED.value:
                    row.attempt_number += 1
                    row.status = PublishAttemptStatus.STARTED.value
                    row.provider_operation_id = None
                    row.external_id = None
                    row.public_url = None
                    row.error_code = None
                    row.retry_after = None
                    row.completed_at = None
                    row.updated_at = now
            session.flush()
            return self._project(row)

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
    ) -> PublishAttempt:
        with self._sessions.begin() as session:
            row = session.scalar(
                select(PublishAttemptRow)
                .where(PublishAttemptRow.idempotency_key == idempotency_key)
                .with_for_update()
            )
            if row is None:
                raise DomainValidationError("Publish attempt does not exist")
            row.status = status.value
            row.updated_at = now
            row.provider_operation_id = provider_operation_id
            row.external_id = external_id
            row.public_url = public_url
            row.error_code = error_code
            row.retry_after = retry_after
            row.completed_at = (
                now
                if status
                in {PublishAttemptStatus.SUCCEEDED, PublishAttemptStatus.FAILED}
                else None
            )
            session.flush()
            return self._project(row)

    @staticmethod
    def _project(row: PublishAttemptRow) -> PublishAttempt:
        return PublishAttempt(
            job_id=row.job_id,
            platform=Platform(row.platform),
            attempt_number=row.attempt_number,
            status=PublishAttemptStatus(row.status),
            idempotency_key=row.idempotency_key,
            created_at=row.created_at,
            updated_at=row.updated_at,
            provider_operation_id=row.provider_operation_id,
            external_id=row.external_id,
            public_url=row.public_url,
            error_code=row.error_code,
            retry_after=row.retry_after,
            completed_at=row.completed_at,
        )
