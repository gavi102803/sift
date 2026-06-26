"""Store answer source metadata on concepts.

Revision ID: 20260622_0004
Revises: 20260622_0003
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0004"
down_revision: str | None = "20260622_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("concepts", sa.Column("answer_source_json", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("concepts", "answer_source_json")
