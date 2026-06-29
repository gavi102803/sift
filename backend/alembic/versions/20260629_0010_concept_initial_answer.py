"""Persist initial conversational answer on concepts.

Revision ID: 20260629_0010
Revises: 20260627_0009
Create Date: 2026-06-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260629_0010"
down_revision: str | None = "20260627_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_column("concepts", "initial_answer"):
        op.add_column("concepts", sa.Column("initial_answer", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("concepts", "initial_answer"):
        op.drop_column("concepts", "initial_answer")


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))
