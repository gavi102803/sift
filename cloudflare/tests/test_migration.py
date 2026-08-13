import sqlite3
from pathlib import Path


def test_initial_migration_builds_required_schema() -> None:
    migrations = Path(__file__).parents[1] / "migrations"
    database = sqlite3.connect(":memory:")

    for migration in sorted(migrations.glob("*.sql")):
        database.executescript(migration.read_text(encoding="utf-8"))

    tables = {
        row[0]
        for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    indexes = {
        row[0]
        for row in database.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    assert {
        "beta_invites",
        "beta_sessions",
        "owner_revocations",
        "model_runs",
        "model_run_events",
        "managed_provider_connections",
        "concepts",
        "note_blocks",
        "concept_tags",
        "concept_topics",
        "note_revisions",
        "concept_turns",
        "concept_relations",
        "update_proposals",
        "concept_sources",
        "concept_continuity_summaries",
        "concept_maintenance_state",
        "managed_web_provider_settings",
        "concept_claims",
        "learning_state_entries",
    } <= tables
    assert {
        "idx_beta_sessions_owner_id",
        "idx_model_runs_owner_created",
        "idx_model_runs_owner_status",
        "idx_model_runs_recoverable",
        "idx_model_run_events_run_sequence",
        "idx_concepts_owner_created",
        "idx_note_blocks_concept_position",
        "idx_concept_turns_concept_created",
        "idx_concept_relations_source",
        "idx_update_proposals_concept_status",
        "idx_concept_sources_concept",
        "idx_concept_claims_concept",
        "idx_learning_state_concept_field",
    } <= indexes
    revision_columns = {
        row[1]
        for row in database.execute("PRAGMA table_info(note_revisions)").fetchall()
    }
    assert {"snapshot_schema_version", "restored_from_revision"} <= revision_columns
    run_columns = {
        row[1]
        for row in database.execute("PRAGMA table_info(model_runs)").fetchall()
    }
    assert {
        "lease_owner",
        "lease_expires_at",
        "cancel_requested_at",
        "tool_contract_hash",
        "started_at",
        "completed_at",
        "step_count",
        "model_latency_ms",
        "input_token_count",
        "output_token_count",
    } <= run_columns
