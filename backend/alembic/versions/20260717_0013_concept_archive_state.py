"""Preserve concept status across soft-delete restore.

Revision ID: 20260717_0013
Revises: 20260715_0012
Create Date: 2026-07-17
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260717_0013"
down_revision: str | None = "20260715_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_column("concepts", "archived_from_status"):
        op.add_column(
            "concepts",
            sa.Column("archived_from_status", sa.String(length=32), nullable=True),
        )


def downgrade() -> None:
    if _has_column("concepts", "archived_from_status"):
        op.drop_column("concepts", "archived_from_status")


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))
