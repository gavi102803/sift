"""Add owner and idempotency foundations.

Revision ID: 20260627_0008
Revises: 20260622_0007
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0008"
down_revision: str | None = "20260622_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "concepts",
        sa.Column(
            "owner_id",
            sa.String(length=128),
            nullable=False,
            server_default="local-dev",
        ),
    )

    op.create_table(
        "capture_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("raw_capture", sa.Text(), nullable=False),
        sa.Column("locale", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=True),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("owner_id", "idempotency_key", name="uq_capture_attempt_owner_key"),
    )
    op.create_index("ix_capture_attempts_owner_id", "capture_attempts", ["owner_id"])

    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_id", sa.String(length=128), nullable=False),
        sa.Column("endpoint", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "owner_id",
            "endpoint",
            "idempotency_key",
            name="uq_idempotency_owner_endpoint_key",
        ),
    )
    op.create_index("ix_idempotency_records_owner_id", "idempotency_records", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_idempotency_records_owner_id", table_name="idempotency_records")
    op.drop_table("idempotency_records")
    op.drop_index("ix_capture_attempts_owner_id", table_name="capture_attempts")
    op.drop_table("capture_attempts")
    op.drop_column("concepts", "owner_id")
