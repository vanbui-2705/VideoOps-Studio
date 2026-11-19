"""Create versioned channel profiles without storing credential values."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261116_0002"
down_revision = "20261116_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "channel_profiles",
        sa.Column("channel_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("niche", sa.String(120), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("profile_snapshot", JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_channel_revision"),
    )
    op.create_index("ix_channel_profiles_name", "channel_profiles", ["name"])
    op.create_table(
        "channel_profile_revisions",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "channel_id",
            sa.String(64),
            sa.ForeignKey("channel_profiles.channel_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("profile_snapshot", JSONB(), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor_id", sa.String(128)),
        sa.Column("change_reason", sa.String(256)),
        sa.UniqueConstraint(
            "channel_id", "revision", name="uq_channel_profile_revision"
        ),
    )
    op.create_index(
        "ix_channel_profile_revisions_channel_id",
        "channel_profile_revisions",
        ["channel_id"],
    )


def downgrade() -> None:
    op.drop_table("channel_profile_revisions")
    op.drop_table("channel_profiles")
