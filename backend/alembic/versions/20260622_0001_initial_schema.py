"""Initial concept persistence schema.

Revision ID: 20260622_0001
Revises:
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "concepts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("canonical_title", sa.String(length=255), nullable=False),
        sa.Column("display_title", sa.String(length=255), nullable=False),
        sa.Column("one_line_explanation", sa.Text(), nullable=False),
        sa.Column("maturity", sa.String(length=32), nullable=False),
        sa.Column("capture_status", sa.String(length=32), nullable=False),
        sa.Column("note_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "note_blocks",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("block_type", sa.String(length=64), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("is_user_locked", sa.Boolean(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_note_blocks_concept_id", "note_blocks", ["concept_id"])
    op.create_table(
        "update_proposals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("base_note_revision", sa.Integer(), nullable=False),
        sa.Column("patch_operations_json", sa.Text(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_update_proposals_concept_id", "update_proposals", ["concept_id"])
    op.create_table(
        "concept_turns",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("answer_source_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_concept_turns_concept_id", "concept_turns", ["concept_id"])


def downgrade() -> None:
    op.drop_index("ix_concept_turns_concept_id", table_name="concept_turns")
    op.drop_table("concept_turns")
    op.drop_index("ix_update_proposals_concept_id", table_name="update_proposals")
    op.drop_table("update_proposals")
    op.drop_index("ix_note_blocks_concept_id", table_name="note_blocks")
    op.drop_table("note_blocks")
    op.drop_table("concepts")
