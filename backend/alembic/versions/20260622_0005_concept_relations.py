"""Add concept relations.

Revision ID: 20260622_0005
Revises: 20260622_0004
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0005"
down_revision: str | None = "20260622_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "concept_relations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("source_concept_id", sa.String(length=36), nullable=False),
        sa.Column("target_concept_id", sa.String(length=36), nullable=False),
        sa.Column("relation_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["source_concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_concept_id",
            "target_concept_id",
            "relation_type",
            name="uq_concept_relations",
        ),
    )
    op.create_index(
        "ix_concept_relations_source_concept_id",
        "concept_relations",
        ["source_concept_id"],
    )
    op.create_index(
        "ix_concept_relations_target_concept_id",
        "concept_relations",
        ["target_concept_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_concept_relations_target_concept_id",
        table_name="concept_relations",
    )
    op.drop_index(
        "ix_concept_relations_source_concept_id",
        table_name="concept_relations",
    )
    op.drop_table("concept_relations")
