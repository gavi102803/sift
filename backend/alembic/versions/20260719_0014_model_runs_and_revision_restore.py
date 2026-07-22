"""Add resumable model runs, maintenance state, and revision restore metadata.

Revision ID: 20260719_0014
Revises: 20260717_0013
Create Date: 2026-07-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260719_0014"
down_revision: str | None = "20260717_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "note_revisions",
        sa.Column("snapshot_schema_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "note_revisions", sa.Column("restored_from_revision", sa.Integer(), nullable=True)
    )
    op.add_column(
        "update_proposals",
        sa.Column("origin", sa.String(32), nullable=False, server_default="followUp"),
    )
    op.add_column("update_proposals", sa.Column("source_run_id", sa.String(36), nullable=True))
    op.create_table(
        "model_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("concept_id", sa.String(36), nullable=True),
        sa.Column("client_draft_id", sa.String(128), nullable=True),
        sa.Column("idempotency_key", sa.String(255), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("provider_snapshot_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("dependency_run_id", sa.String(36), nullable=True),
        sa.Column("checkpoint", sa.String(64), nullable=True),
        sa.Column("checkpoint_json", sa.Text(), nullable=True),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("result_ref", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("lease_owner", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "owner_id", "kind", "idempotency_key", name="uq_model_runs_owner_kind_key"
        ),
    )
    op.create_index("ix_model_runs_owner_id", "model_runs", ["owner_id"])
    op.create_index("ix_model_runs_status", "model_runs", ["status"])
    op.create_index("ix_model_runs_concept_id", "model_runs", ["concept_id"])
    op.create_table(
        "model_run_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(36),
            sa.ForeignKey("model_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("data_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "sequence", name="uq_model_run_events_sequence"),
    )
    op.create_index("ix_model_run_events_run_id", "model_run_events", ["run_id"])
    op.create_table(
        "concept_continuity_summaries",
        sa.Column(
            "concept_id",
            sa.String(36),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("summary_json", sa.Text(), nullable=False),
        sa.Column("through_turn_id", sa.Integer(), nullable=False),
        sa.Column("source_turns_hash", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_continuity_owner", "concept_continuity_summaries", ["owner_id"])
    op.create_table(
        "concept_maintenance_states",
        sa.Column(
            "concept_id",
            sa.String(36),
            sa.ForeignKey("concepts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("owner_id", sa.String(128), nullable=False),
        sa.Column("last_reviewed_turn_id", sa.Integer(), nullable=True),
        sa.Column("review_due", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_maintenance_owner", "concept_maintenance_states", ["owner_id"])


def downgrade() -> None:
    op.drop_index("ix_maintenance_owner", table_name="concept_maintenance_states")
    op.drop_table("concept_maintenance_states")
    op.drop_index("ix_continuity_owner", table_name="concept_continuity_summaries")
    op.drop_table("concept_continuity_summaries")
    op.drop_index("ix_model_run_events_run_id", table_name="model_run_events")
    op.drop_table("model_run_events")
    op.drop_index("ix_model_runs_concept_id", table_name="model_runs")
    op.drop_index("ix_model_runs_status", table_name="model_runs")
    op.drop_index("ix_model_runs_owner_id", table_name="model_runs")
    op.drop_table("model_runs")
    op.drop_column("update_proposals", "source_run_id")
    op.drop_column("update_proposals", "origin")
    op.drop_column("note_revisions", "restored_from_revision")
    op.drop_column("note_revisions", "snapshot_schema_version")
