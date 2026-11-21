"""Transactional PostgreSQL implementation of the Module 2 workflow store."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from core.adapters.persistence.mappers import job_from_dict, job_to_dict
from core.adapters.persistence.models import (
    ArtifactRow,
    AuditEntryRow,
    JobCommandRow,
    JobRow,
    JobTransitionRow,
    PublishTargetRow,
    WorkItemRow,
)
from core.application.ports import QueueStatus
from core.domain.errors import DomainValidationError, JobNotFound, RevisionConflict
from core.domain.models import JobStatus, VideoJob, WorkflowDecision, WorkIntent


class PostgresWorkflowStore:
    """Persist one aggregate change and all resulting work in one transaction."""

    def __init__(self, engine: Engine, *, default_max_attempts: int = 3) -> None:
        self._sessions = sessionmaker(engine, expire_on_commit=False)
        self._default_max_attempts = default_max_attempts

    def get_request_result(self, request_id: str) -> VideoJob | None:
        with self._sessions() as session:
            row = session.scalar(select(JobRow).where(JobRow.request_id == request_id))
            return job_from_dict(row.aggregate_snapshot) if row else None

    def get(self, job_id: str) -> VideoJob | None:
        with self._sessions() as session:
            row = session.get(JobRow, job_id)
            return job_from_dict(row.aggregate_snapshot) if row else None

    def list_retention_candidates(
        self,
        draft_before: datetime,
        publish_before: datetime,
        limit: int,
    ) -> tuple[VideoJob, ...]:
        draft_statuses = {
            JobStatus.QUEUED.value,
            JobStatus.INGESTING.value,
            JobStatus.RENDERING_PREVIEW.value,
            JobStatus.AWAITING_REVIEW.value,
        }
        with self._sessions() as session:
            rows = session.scalars(
                select(JobRow)
                .where(
                    or_(
                        (JobRow.status.in_(draft_statuses))
                        & (JobRow.updated_at <= draft_before),
                        (JobRow.status == JobStatus.FAILED.value)
                        & (JobRow.phase == "PUBLISH")
                        & (JobRow.updated_at <= publish_before),
                    )
                )
                .order_by(JobRow.updated_at, JobRow.id)
                .limit(limit)
            ).all()
            return tuple(job_from_dict(row.aggregate_snapshot) for row in rows)

    def get_command_result(self, command_id: str) -> VideoJob | None:
        with self._sessions() as session:
            row = session.scalar(
                select(JobCommandRow).where(JobCommandRow.command_id == command_id)
            )
            return job_from_dict(row.result_snapshot) if row else None

    def create(self, job: VideoJob, initial_work: WorkIntent) -> VideoJob:
        snapshot = job_to_dict(job)
        try:
            with self._sessions.begin() as session:
                session.add(
                    JobRow(
                        id=job.job_id,
                        request_id=job.request_id,
                        channel_id=job.channel_id,
                        workflow_type=job.job_type.value,
                        status=job.status.value,
                        phase=job.phase.value,
                        revision=job.revision,
                        content_revision=job.content_revision,
                        request_snapshot=snapshot["request_snapshot"],
                        approval_snapshot=snapshot["approval_snapshot"],
                        failure_snapshot=snapshot["failure"],
                        aggregate_snapshot=snapshot,
                        created_at=job.created_at,
                        updated_at=job.updated_at,
                    )
                )
                session.flush()
                self._replace_children(session, job)
                self._append_work(session, initial_work, job.created_at)
                session.add(
                    JobTransitionRow(
                        job_id=job.job_id,
                        from_state=None,
                        to_state=job.status.value,
                        event_type="JOB_SUBMITTED",
                        revision=job.revision,
                        transition_metadata={},
                        created_at=job.created_at,
                    )
                )
                session.add(
                    AuditEntryRow(
                        job_id=job.job_id,
                        actor_type="USER",
                        action="JOB_CREATED",
                        audit_metadata={"request_id": job.request_id},
                        created_at=job.created_at,
                    )
                )
        except IntegrityError:
            existing = self.get_request_result(job.request_id)
            if existing is not None:
                return existing
            raise
        return job

    def commit(
        self,
        decision: WorkflowDecision,
        expected_revision: int,
    ) -> VideoJob:
        job = decision.job
        snapshot = job_to_dict(job)
        with self._sessions.begin() as session:
            if decision.command_id:
                prior = session.scalar(
                    select(JobCommandRow).where(
                        JobCommandRow.command_id == decision.command_id
                    )
                )
                if prior:
                    return self._validated_command_result(prior, job.job_id)

            row = session.scalar(
                select(JobRow).where(JobRow.id == job.job_id).with_for_update()
            )
            if row is None:
                raise JobNotFound(job.job_id)

            # A same-job concurrent command waits on the row lock. Check its key again.
            if decision.command_id:
                prior = session.scalar(
                    select(JobCommandRow).where(
                        JobCommandRow.command_id == decision.command_id
                    )
                )
                if prior:
                    return self._validated_command_result(prior, job.job_id)

            if row.revision != expected_revision:
                raise RevisionConflict(job.job_id)

            previous_status = row.status
            row.status = job.status.value
            row.phase = job.phase.value
            row.revision = job.revision
            row.content_revision = job.content_revision
            row.request_snapshot = snapshot["request_snapshot"]
            row.approval_snapshot = snapshot["approval_snapshot"]
            row.failure_snapshot = snapshot["failure"]
            row.aggregate_snapshot = snapshot
            row.updated_at = job.updated_at
            if job.status in {JobStatus.COMPLETED, JobStatus.CANCELLED}:
                row.completed_at = job.updated_at

            self._replace_children(session, job)
            for intent in decision.work_intents:
                self._append_work(session, intent, job.updated_at)

            session.add(
                JobTransitionRow(
                    job_id=job.job_id,
                    from_state=previous_status,
                    to_state=job.status.value,
                    event_type=(
                        "COMMAND_COMMITTED"
                        if decision.command_id
                        else "WORKFLOW_EVENT_COMMITTED"
                    ),
                    revision=job.revision,
                    transition_metadata={"command_id": decision.command_id}
                    if decision.command_id
                    else {},
                    created_at=job.updated_at,
                )
            )
            session.add(
                AuditEntryRow(
                    job_id=job.job_id,
                    actor_type="USER" if decision.command_id else "WORKER",
                    actor_id=decision.actor_id,
                    action="WORKFLOW_COMMITTED",
                    audit_metadata={"revision": job.revision},
                    created_at=job.updated_at,
                )
            )
            if decision.command_id:
                session.add(
                    JobCommandRow(
                        job_id=job.job_id,
                        command_id=decision.command_id,
                        command_type="WORKFLOW_COMMAND",
                        expected_revision=expected_revision,
                        result_revision=job.revision,
                        result_snapshot=snapshot,
                        created_at=job.updated_at,
                    )
                )
        return job

    @staticmethod
    def _validated_command_result(row: JobCommandRow, job_id: str) -> VideoJob:
        result = job_from_dict(row.result_snapshot)
        if result.job_id != job_id:
            raise DomainValidationError("Command ID belongs to another job")
        return result

    def _append_work(
        self, session: Session, intent: WorkIntent, created_at: datetime
    ) -> None:
        session.execute(
            pg_insert(WorkItemRow)
            .values(
                id=str(uuid4()),
                job_id=intent.job_id,
                kind=intent.kind.value,
                platform=intent.platform.value if intent.platform else "",
                content_revision=intent.content_revision,
                status=QueueStatus.READY.value,
                attempts=0,
                max_attempts=self._default_max_attempts,
                available_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
            .on_conflict_do_nothing(constraint="uq_work_logical")
        )

    @staticmethod
    def _replace_children(session: Session, job: VideoJob) -> None:
        # Historical media rows remain until purge verifies physical deletion.
        # Removing them on regeneration would orphan files on disk.
        existing = {
            row.artifact_id: row
            for row in session.scalars(
                select(ArtifactRow).where(ArtifactRow.job_id == job.job_id)
            ).all()
        }
        for artifact in job.artifacts:
            row = existing.get(artifact.artifact_id)
            if row is None:
                session.add(
                    ArtifactRow(
                        job_id=job.job_id,
                        artifact_id=artifact.artifact_id,
                        artifact_type=artifact.kind.value,
                        byte_size=0,
                        content_revision=artifact.content_revision,
                        artifact_metadata={},
                        created_at=job.updated_at,
                    )
                )
            else:
                row.artifact_type = artifact.kind.value
                row.content_revision = artifact.content_revision
        session.execute(
            delete(PublishTargetRow).where(PublishTargetRow.job_id == job.job_id)
        )
        for target in job.publish_targets:
            session.add(
                PublishTargetRow(
                    job_id=job.job_id,
                    platform=target.platform.value,
                    status=target.status.value,
                    external_id=target.external_video_id,
                    external_url=target.public_url,
                    failure_snapshot={"code": target.last_error_code}
                    if target.last_error_code
                    else None,
                    updated_at=job.updated_at,
                )
            )
