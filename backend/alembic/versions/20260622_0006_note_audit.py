"""Add note audit records.

Revision ID: 20260622_0006
Revises: 20260622_0005
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0006"
down_revision: str | None = "20260622_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "note_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("merge_mode", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concept_id", "revision", name="uq_note_revisions_concept_revision"),
    )
    op.create_index("ix_note_revisions_concept_id", "note_revisions", ["concept_id"])

    op.create_table(
        "update_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("note_revision", sa.Integer(), nullable=False),
        sa.Column("source_message_id", sa.String(length=36), nullable=True),
        sa.Column("proposal_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("actor", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_update_events_concept_id", "update_events", ["concept_id"])


def downgrade() -> None:
    op.drop_index("ix_update_events_concept_id", table_name="update_events")
    op.drop_table("update_events")
    op.drop_index("ix_note_revisions_concept_id", table_name="note_revisions")
    op.drop_table("note_revisions")
