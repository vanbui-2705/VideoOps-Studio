"""PostgreSQL queue with atomic claims and expiring worker leases."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from core.adapters.persistence.models import WorkItemRow
from core.application.ports import QueuedWork, QueueStatus
from core.domain.errors import WorkQueueConflict
from core.domain.models import Platform, WorkIntent, WorkKind


class PostgresWorkQueue:
    """Lease work without allowing two concurrent workers to claim one row."""

    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def enqueue(self, intent: WorkIntent, max_attempts: int = 3) -> QueuedWork:
        now = datetime.now(UTC)
        work_id = str(uuid4())
        with self._sessions.begin() as session:
            inserted_id = session.scalar(
                pg_insert(WorkItemRow)
                .values(
                    id=work_id,
                    job_id=intent.job_id,
                    kind=intent.kind.value,
                    platform=intent.platform.value if intent.platform else "",
                    content_revision=intent.content_revision,
                    status=QueueStatus.READY.value,
                    attempts=0,
                    max_attempts=max_attempts,
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_nothing(constraint="uq_work_logical")
                .returning(WorkItemRow.id)
            )
            if inserted_id is None:
                row = session.scalar(self._logical_query(intent))
            else:
                row = session.get(WorkItemRow, inserted_id)
            assert row is not None
            return self._project(row)

    def get(self, work_id: str) -> QueuedWork | None:
        with self._sessions() as session:
            row = session.get(WorkItemRow, work_id)
            return self._project(row) if row else None

    def claim_next(
        self,
        worker_id: str,
        lease_seconds: int,
        supported_kinds: tuple[WorkKind, ...] | None = None,
    ) -> QueuedWork | None:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            query = select(WorkItemRow).where(
                WorkItemRow.status == QueueStatus.READY.value,
                WorkItemRow.available_at <= now,
            )
            if supported_kinds is not None:
                if not supported_kinds:
                    return None
                query = query.where(
                    WorkItemRow.kind.in_(kind.value for kind in supported_kinds)
                )
            row = session.scalar(
                query.order_by(WorkItemRow.available_at, WorkItemRow.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = QueueStatus.CLAIMED.value
            row.attempts += 1
            row.lease_owner = worker_id
            row.lease_until = now + timedelta(seconds=lease_seconds)
            row.updated_at = now
            session.flush()
            return self._project(row)

    def heartbeat(self, work_id: str, worker_id: str, lease_seconds: int) -> QueuedWork:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = self._leased_row(session, work_id, worker_id)
            row.lease_until = now + timedelta(seconds=lease_seconds)
            row.updated_at = now
            return self._project(row)

    def ack(self, work_id: str, worker_id: str) -> QueuedWork:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = self._leased_row(session, work_id, worker_id)
            row.status = QueueStatus.SUCCEEDED.value
            row.lease_owner = None
            row.lease_until = None
            row.completed_at = now
            row.updated_at = now
            return self._project(row)

    def retry(
        self,
        work_id: str,
        worker_id: str,
        error_code: str,
        available_at: datetime,
    ) -> QueuedWork:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = self._leased_row(session, work_id, worker_id)
            row.status = (
                QueueStatus.DEAD.value
                if row.attempts >= row.max_attempts
                else QueueStatus.READY.value
            )
            row.available_at = available_at
            row.last_error_code = error_code
            row.last_error_snapshot = {"code": error_code}
            row.lease_owner = None
            row.lease_until = None
            row.updated_at = now
            if row.status == QueueStatus.DEAD.value:
                row.completed_at = now
            return self._project(row)

    def mark_dead(self, work_id: str, worker_id: str, error_code: str) -> QueuedWork:
        now = datetime.now(UTC)
        with self._sessions.begin() as session:
            row = self._leased_row(session, work_id, worker_id)
            row.status = QueueStatus.DEAD.value
            row.last_error_code = error_code
            row.last_error_snapshot = {"code": error_code}
            row.lease_owner = None
            row.lease_until = None
            row.updated_at = now
            row.completed_at = now
            return self._project(row)

    def recover_expired_leases(self, now: datetime) -> int:
        recovered = 0
        with self._sessions.begin() as session:
            rows = session.scalars(
                select(WorkItemRow)
                .where(
                    WorkItemRow.status == QueueStatus.CLAIMED.value,
                    WorkItemRow.lease_until < now,
                )
                .with_for_update(skip_locked=True)
            ).all()
            for row in rows:
                row.status = (
                    QueueStatus.DEAD.value
                    if row.attempts >= row.max_attempts
                    else QueueStatus.READY.value
                )
                row.lease_owner = None
                row.lease_until = None
                row.updated_at = now
                if row.status == QueueStatus.DEAD.value:
                    row.completed_at = now
                recovered += 1
        return recovered

    @staticmethod
    def _logical_query(intent: WorkIntent):
        return select(WorkItemRow).where(
            WorkItemRow.job_id == intent.job_id,
            WorkItemRow.kind == intent.kind.value,
            WorkItemRow.content_revision == intent.content_revision,
            WorkItemRow.platform == (intent.platform.value if intent.platform else ""),
        )

    @staticmethod
    def _leased_row(session: Session, work_id: str, worker_id: str) -> WorkItemRow:
        row = session.scalar(
            select(WorkItemRow).where(WorkItemRow.id == work_id).with_for_update()
        )
        if (
            row is None
            or row.status != QueueStatus.CLAIMED.value
            or row.lease_owner != worker_id
        ):
            raise WorkQueueConflict(work_id)
        return row

    @staticmethod
    def _project(row: WorkItemRow) -> QueuedWork:
        return QueuedWork(
            work_id=row.id,
            intent=WorkIntent(
                job_id=row.job_id,
                kind=WorkKind(row.kind),
                content_revision=row.content_revision,
                platform=Platform(row.platform) if row.platform else None,
            ),
            status=QueueStatus(row.status),
            attempts=row.attempts,
            max_attempts=row.max_attempts,
            available_at=row.available_at,
            lease_owner=row.lease_owner,
            lease_until=row.lease_until,
            last_error_code=row.last_error_code,
        )
