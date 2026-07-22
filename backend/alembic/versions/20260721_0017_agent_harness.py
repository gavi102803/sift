"""Persist Sift Agent Harness execution metadata.

Revision ID: 20260721_0017
Revises: 20260719_0016
Create Date: 2026-07-21
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260721_0017"
down_revision: str | None = "20260719_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_runs",
        sa.Column("agent_spec", sa.String(length=64), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "model_runs",
        sa.Column("agent_spec_version", sa.String(length=32), nullable=False, server_default="1"),
    )
    op.add_column(
        "model_runs",
        sa.Column("prompt_version", sa.String(length=64), nullable=False, server_default="legacy"),
    )
    op.add_column(
        "model_runs",
        sa.Column("budget_json", sa.Text(), nullable=False, server_default="{}"),
    )
    op.add_column("model_runs", sa.Column("current_step", sa.String(length=64), nullable=True))
    op.add_column(
        "model_runs",
        sa.Column("model_call_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "model_runs",
        sa.Column("tool_call_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "model_runs",
        sa.Column("termination_reason", sa.String(length=64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("model_runs", "termination_reason")
    op.drop_column("model_runs", "tool_call_count")
    op.drop_column("model_runs", "model_call_count")
    op.drop_column("model_runs", "current_step")
    op.drop_column("model_runs", "budget_json")
    op.drop_column("model_runs", "prompt_version")
    op.drop_column("model_runs", "agent_spec_version")
    op.drop_column("model_runs", "agent_spec")
