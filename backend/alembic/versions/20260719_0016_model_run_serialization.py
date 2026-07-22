"""Enforce one running model task per concept.

Revision ID: 20260719_0016
Revises: 20260719_0015
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260719_0016"
down_revision: str | None = "20260719_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_model_runs_running_concept",
        "model_runs",
        ["concept_id"],
        unique=True,
        sqlite_where=sa.text("status = 'running' AND concept_id IS NOT NULL"),
        postgresql_where=sa.text("status = 'running' AND concept_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_model_runs_running_concept", table_name="model_runs")
