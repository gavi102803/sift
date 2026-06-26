"""Persist answer source on assistant turns.

Revision ID: 20260622_0002
Revises: 20260622_0001
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0002"
down_revision: str | None = "20260622_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if not _has_column("concept_turns", "answer_source_json"):
        op.add_column("concept_turns", sa.Column("answer_source_json", sa.Text(), nullable=True))


def downgrade() -> None:
    if _has_column("concept_turns", "answer_source_json"):
        op.drop_column("concept_turns", "answer_source_json")


def _has_column(table_name: str, column_name: str) -> bool:
    inspector = sa.inspect(op.get_bind())
    return any(column["name"] == column_name for column in inspector.get_columns(table_name))
