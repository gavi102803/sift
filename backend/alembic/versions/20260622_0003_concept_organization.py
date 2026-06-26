"""Add concept tag and topic assignments.

Revision ID: 20260622_0003
Revises: 20260622_0002
Create Date: 2026-06-22
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260622_0003"
down_revision: str | None = "20260622_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "concept_tags",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("tag_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["tag_id"], ["tags.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concept_id", "tag_id", name="uq_concept_tags"),
    )
    op.create_index("ix_concept_tags_concept_id", "concept_tags", ["concept_id"])
    op.create_index("ix_concept_tags_tag_id", "concept_tags", ["tag_id"])
    op.create_table(
        "concept_topics",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("concept_id", sa.String(length=36), nullable=False),
        sa.Column("topic_id", sa.Integer(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["topic_id"], ["topics.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("concept_id", "topic_id", name="uq_concept_topics"),
    )
    op.create_index("ix_concept_topics_concept_id", "concept_topics", ["concept_id"])
    op.create_index("ix_concept_topics_topic_id", "concept_topics", ["topic_id"])


def downgrade() -> None:
    op.drop_index("ix_concept_topics_topic_id", table_name="concept_topics")
    op.drop_index("ix_concept_topics_concept_id", table_name="concept_topics")
    op.drop_table("concept_topics")
    op.drop_index("ix_concept_tags_tag_id", table_name="concept_tags")
    op.drop_index("ix_concept_tags_concept_id", table_name="concept_tags")
    op.drop_table("concept_tags")
    op.drop_table("topics")
    op.drop_table("tags")
