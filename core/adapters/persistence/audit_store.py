"""Append-only, sanitized operational audit persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from core.adapters.persistence.models import AuditEntryRow
from core.application.audit_query import AuditQuery, AuditRecord
from core.domain.models import VideoJob


class PostgresAuditStore:
    def __init__(self, engine: Engine) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def ensure_purge_snapshot(self, job: VideoJob, now: datetime) -> None:
        with self._sessions.begin() as session:
            existing = session.scalar(
                select(AuditEntryRow).where(
                    AuditEntryRow.job_id == job.job_id,
                    AuditEntryRow.action == "PURGE_SNAPSHOT",
                )
            )
            if existing is not None:
                return
            approved = job.approval_snapshot
            metadata = approved.metadata if approved else job.metadata_draft
            session.add(
                AuditEntryRow(
                    job_id=job.job_id,
                    actor_type="SYSTEM",
                    action="PURGE_SNAPSHOT",
                    audit_metadata={
                        "channel_id": job.channel_id,
                        "title": metadata.title,
                        "terminal_status": job.terminal_after_purge.value,
                        "targets": [
                            {
                                "platform": target.platform.value,
                                "status": target.status.value,
                                "external_id": target.external_video_id,
                                "public_url": target.public_url,
                                "skip_reason": target.skip_reason,
                            }
                            for target in job.publish_targets
                        ],
                    },
                    created_at=now,
                )
            )

    def list_for_job(self, job_id: str) -> tuple[AuditRecord, ...]:
        with self._sessions() as session:
            rows = session.scalars(
                select(AuditEntryRow)
                .where(AuditEntryRow.job_id == job_id)
                .order_by(AuditEntryRow.created_at, AuditEntryRow.id)
            ).all()
            return tuple(
                AuditRecord(
                    job_id=row.job_id,
                    actor_type=row.actor_type,
                    actor_id=row.actor_id,
                    action=row.action,
                    metadata=dict(row.audit_metadata),
                    created_at=row.created_at,
                )
                for row in rows
            )

    def search(self, query: AuditQuery) -> tuple[AuditRecord, ...]:
        statement = select(AuditEntryRow)
        if query.job_id:
            statement = statement.where(AuditEntryRow.job_id == query.job_id)
        if query.actor_type:
            statement = statement.where(AuditEntryRow.actor_type == query.actor_type)
        if query.actor_id:
            statement = statement.where(AuditEntryRow.actor_id == query.actor_id)
        if query.action:
            statement = statement.where(AuditEntryRow.action == query.action)
        if query.channel_id:
            statement = statement.where(
                AuditEntryRow.audit_metadata["channel_id"].astext == query.channel_id
            )
        if query.platform:
            statement = statement.where(
                AuditEntryRow.audit_metadata.contains(
                    {"targets": [{"platform": query.platform}]}
                )
            )
        if query.created_from:
            statement = statement.where(AuditEntryRow.created_at >= query.created_from)
        if query.created_to:
            statement = statement.where(AuditEntryRow.created_at <= query.created_to)
        statement = (
            statement.order_by(AuditEntryRow.created_at.desc(), AuditEntryRow.id.desc())
            .offset((query.page - 1) * query.page_size)
            .limit(query.page_size)
        )
        with self._sessions() as session:
            rows = session.scalars(statement).all()
            return tuple(
                AuditRecord(
                    row.job_id,
                    row.actor_type,
                    row.actor_id,
                    row.action,
                    dict(row.audit_metadata),
                    row.created_at,
                )
                for row in rows
            )
