"""Add managed beta identity tables.

Revision ID: 20260715_0011
Revises: 20260629_0010
Create Date: 2026-07-15
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260715_0011"
down_revision: str | None = "20260629_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "beta_owners",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "beta_invites",
        sa.Column("code_hash", sa.String(length=64), primary_key=True),
        sa.Column("owner_id", sa.String(length=36), nullable=True),
        sa.Column("installation_id", sa.String(length=128), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_beta_invites_owner_id", "beta_invites", ["owner_id"])
    op.create_table(
        "beta_sessions",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("owner_id", sa.String(length=36), nullable=False),
        sa.Column("installation_id", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_beta_sessions_token_hash"),
    )
    op.create_index("ix_beta_sessions_token_hash", "beta_sessions", ["token_hash"])
    op.create_index("ix_beta_sessions_owner_id", "beta_sessions", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_beta_sessions_owner_id", table_name="beta_sessions")
    op.drop_index("ix_beta_sessions_token_hash", table_name="beta_sessions")
    op.drop_table("beta_sessions")
    op.drop_index("ix_beta_invites_owner_id", table_name="beta_invites")
    op.drop_table("beta_invites")
    op.drop_table("beta_owners")
