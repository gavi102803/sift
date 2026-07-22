"""Add durable operation keys for idempotent turn commits.

Revision ID: 20260719_0015
Revises: 20260719_0014
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260719_0015"
down_revision: str | None = "20260719_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("concept_turns") as batch_op:
        batch_op.add_column(sa.Column("operation_key", sa.String(255), nullable=True))
        batch_op.create_unique_constraint(
            "uq_concept_turn_operation_role", ["concept_id", "operation_key", "role"]
        )


def downgrade() -> None:
    with op.batch_alter_table("concept_turns") as batch_op:
        batch_op.drop_constraint("uq_concept_turn_operation_role", type_="unique")
        batch_op.drop_column("operation_key")
