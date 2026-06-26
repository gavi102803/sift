"""Add knowledge sedimentation layers.

Revision ID: 20260622_0007
Revises: 20260622_0006
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0007"
down_revision: str | None = "20260622_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "note_blocks",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "note_blocks",
        sa.Column("supported_claim_ids_json", sa.Text(), nullable=False, server_default="[]"),
    )
    op.add_column("note_blocks", sa.Column("created_at", sa.DateTime(timezone=True)))
    op.add_column("note_blocks", sa.Column("updated_at", sa.DateTime(timezone=True)))

    op.create_table(
        "sources",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sources_concept_id", "sources", ["concept_id"])

    op.create_table(
        "claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(length=32), nullable=False),
        sa.Column("evidence_status", sa.String(length=32), nullable=False),
        sa.Column("time_sensitivity", sa.String(length=32), nullable=False),
        sa.Column("source_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_by_claim_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_claims_concept_id", "claims", ["concept_id"])

    op.create_table(
        "learning_state_entries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_state_entries_concept_id",
        "learning_state_entries",
        ["concept_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_learning_state_entries_concept_id", table_name="learning_state_entries")
    op.drop_table("learning_state_entries")
    op.drop_index("ix_claims_concept_id", table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_sources_concept_id", table_name="sources")
    op.drop_table("sources")
    op.drop_column("note_blocks", "updated_at")
    op.drop_column("note_blocks", "created_at")
    op.drop_column("note_blocks", "supported_claim_ids_json")
    op.drop_column("note_blocks", "revision")
