"""Add safe provider checkpoints to publish attempts."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "20261120_0004"
down_revision = "20261117_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "publish_attempts", sa.Column("provider_operation_id", sa.String(256))
    )
    op.add_column("publish_attempts", sa.Column("public_url", sa.Text()))
    op.add_column("publish_attempts", sa.Column("error_code", sa.String(128)))
    op.add_column(
        "publish_attempts", sa.Column("retry_after", sa.DateTime(timezone=True))
    )
    op.add_column(
        "publish_attempts", sa.Column("updated_at", sa.DateTime(timezone=True))
    )
    op.execute("UPDATE publish_attempts SET updated_at = created_at")
    op.alter_column("publish_attempts", "updated_at", nullable=False)


def downgrade() -> None:
    op.drop_column("publish_attempts", "updated_at")
    op.drop_column("publish_attempts", "retry_after")
    op.drop_column("publish_attempts", "error_code")
    op.execute("ALTER TABLE publish_attempts DROP COLUMN IF EXISTS public_url")
    op.drop_column("publish_attempts", "provider_operation_id")
