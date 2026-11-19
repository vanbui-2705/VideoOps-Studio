"""Create Module 3 workflow persistence and durable queue schema."""

from __future__ import annotations

from alembic import op
from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261116_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata = MetaData()
    jobs = Table(
        "jobs",
        metadata,
        Column("id", String(128), primary_key=True),
        Column("request_id", String(128), nullable=False, unique=True),
        Column("channel_id", String(128), nullable=False),
        Column("workflow_type", String(32), nullable=False),
        Column("status", String(32), nullable=False),
        Column("phase", String(32), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("content_revision", Integer, nullable=False),
        Column("request_snapshot", JSONB),
        Column("approval_snapshot", JSONB),
        Column("failure_snapshot", JSONB),
        Column("aggregate_snapshot", JSONB, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("completed_at", DateTime(timezone=True)),
    )
    jobs.create(op.get_bind())
    op.create_index("ix_jobs_status", "jobs", ["status"])

    _create_child_tables(metadata, jobs)


def _create_child_tables(metadata: MetaData, jobs: Table) -> None:
    fk = ForeignKey(jobs.c.id, ondelete="CASCADE")
    Table(
        "job_commands",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("job_id", String(128), fk, nullable=False),
        Column("command_id", String(128), nullable=False, unique=True),
        Column("command_type", String(64), nullable=False),
        Column("expected_revision", Integer, nullable=False),
        Column("result_revision", Integer, nullable=False),
        Column("result_snapshot", JSONB, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    ).create(op.get_bind())
    op.create_index("ix_job_commands_job_id", "job_commands", ["job_id"])

    Table(
        "job_transitions",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column(
            "job_id",
            String(128),
            ForeignKey(jobs.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        Column("from_state", String(32)),
        Column("to_state", String(32), nullable=False),
        Column("event_type", String(64), nullable=False),
        Column("revision", Integer, nullable=False),
        Column("transition_metadata", JSONB, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    ).create(op.get_bind())
    op.create_index("ix_job_transitions_job_id", "job_transitions", ["job_id"])

    Table(
        "work_items",
        metadata,
        Column("id", String(36), primary_key=True),
        Column(
            "job_id",
            String(128),
            ForeignKey(jobs.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        Column("kind", String(64), nullable=False),
        Column("platform", String(32), nullable=False),
        Column("content_revision", Integer, nullable=False),
        Column("status", String(32), nullable=False),
        Column("attempts", Integer, nullable=False),
        Column("max_attempts", Integer, nullable=False),
        Column("available_at", DateTime(timezone=True), nullable=False),
        Column("lease_owner", String(128)),
        Column("lease_until", DateTime(timezone=True)),
        Column("last_error_code", String(128)),
        Column("last_error_snapshot", JSONB),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        Column("completed_at", DateTime(timezone=True)),
        UniqueConstraint(
            "job_id", "kind", "content_revision", "platform", name="uq_work_logical"
        ),
    ).create(op.get_bind())
    op.create_index("ix_work_items_job_id", "work_items", ["job_id"])
    op.create_index(
        "ix_work_claim", "work_items", ["status", "available_at", "created_at"]
    )

    Table(
        "artifacts",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column(
            "job_id",
            String(128),
            ForeignKey(jobs.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        Column("artifact_id", String(256), nullable=False),
        Column("artifact_type", String(32), nullable=False),
        Column("uri", Text),
        Column("checksum", String(128)),
        Column("byte_size", BigInteger, nullable=False),
        Column("content_revision", Integer, nullable=False),
        Column("artifact_metadata", JSONB, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("job_id", "artifact_id"),
    ).create(op.get_bind())
    op.create_index("ix_artifacts_job_id", "artifacts", ["job_id"])

    Table(
        "publish_targets",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column(
            "job_id",
            String(128),
            ForeignKey(jobs.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        Column("platform", String(32), nullable=False),
        Column("status", String(32), nullable=False),
        Column("external_id", String(256)),
        Column("external_url", Text),
        Column("failure_snapshot", JSONB),
        Column("updated_at", DateTime(timezone=True), nullable=False),
        UniqueConstraint("job_id", "platform"),
    ).create(op.get_bind())
    op.create_index("ix_publish_targets_job_id", "publish_targets", ["job_id"])

    Table(
        "publish_attempts",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column(
            "job_id",
            String(128),
            ForeignKey(jobs.c.id, ondelete="CASCADE"),
            nullable=False,
        ),
        Column("platform", String(32), nullable=False),
        Column("attempt_number", Integer, nullable=False),
        Column("status", String(32), nullable=False),
        Column("idempotency_key", String(256), nullable=False, unique=True),
        Column("external_id", String(256)),
        Column("response_snapshot", JSONB),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("completed_at", DateTime(timezone=True)),
        UniqueConstraint("job_id", "platform", "attempt_number"),
    ).create(op.get_bind())
    op.create_index("ix_publish_attempts_job_id", "publish_attempts", ["job_id"])

    Table(
        "audit_entries",
        metadata,
        Column("id", BigInteger, primary_key=True, autoincrement=True),
        Column("job_id", String(128), ForeignKey(jobs.c.id, ondelete="CASCADE")),
        Column("actor_type", String(32), nullable=False),
        Column("actor_id", String(128)),
        Column("action", String(128), nullable=False),
        Column("audit_metadata", JSONB, nullable=False),
        Column("created_at", DateTime(timezone=True), nullable=False),
    ).create(op.get_bind())
    op.create_index("ix_audit_entries_job_id", "audit_entries", ["job_id"])


def downgrade() -> None:
    for table in (
        "audit_entries",
        "publish_attempts",
        "publish_targets",
        "artifacts",
        "work_items",
        "job_transitions",
        "job_commands",
        "jobs",
    ):
        op.drop_table(table)
