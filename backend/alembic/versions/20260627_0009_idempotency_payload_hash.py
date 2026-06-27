"""Add idempotency payload fingerprints.

Revision ID: 20260627_0009
Revises: 20260627_0008
Create Date: 2026-06-27
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260627_0009"
down_revision: str | None = "20260627_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "capture_attempts",
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "idempotency_records",
        sa.Column("payload_hash", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("idempotency_records", "payload_hash")
    op.drop_column("capture_attempts", "payload_hash")
