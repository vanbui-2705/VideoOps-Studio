"""Add idempotent structured story generation cache."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261117_0003"
down_revision = "20261116_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "story_generations",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "job_id",
            sa.String(128),
            sa.ForeignKey("jobs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("content_revision", sa.Integer(), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("result_snapshot", JSONB(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "job_id", "content_revision", name="uq_story_generation_revision"
        ),
    )
    op.create_index("ix_story_generations_job_id", "story_generations", ["job_id"])


def downgrade() -> None:
    op.drop_table("story_generations")
