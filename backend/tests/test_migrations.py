import os
from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def test_alembic_upgrade_head_creates_owner_and_idempotency_tables(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration-smoke.db'}"
    monkeypatch.setenv("SIFT_DATABASE_URL", database_url)
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(tmp_path / "provider.json"))

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert "capture_attempts" in inspector.get_table_names()
    assert "idempotency_records" in inspector.get_table_names()
    assert "beta_invites" in inspector.get_table_names()
    assert "beta_sessions" in inspector.get_table_names()
    assert "managed_provider_connections" in inspector.get_table_names()
    assert "model_runs" in inspector.get_table_names()
    assert "model_run_events" in inspector.get_table_names()
    assert "concept_continuity_summaries" in inspector.get_table_names()
    assert "concept_maintenance_states" in inspector.get_table_names()
    assert "owner_id" in {column["name"] for column in inspector.get_columns("concepts")}
    assert "operation_key" in {
        column["name"] for column in inspector.get_columns("concept_turns")
    }
    model_run_columns = {
        column["name"] for column in inspector.get_columns("model_runs")
    }
    assert {
        "agent_spec",
        "agent_spec_version",
        "prompt_version",
        "budget_json",
        "current_step",
        "model_call_count",
        "tool_call_count",
        "termination_reason",
    }.issubset(model_run_columns)
    running_indexes = {
        index["name"]: index for index in inspector.get_indexes("model_runs")
    }
    assert running_indexes["uq_model_runs_running_concept"]["unique"] == 1

    command.downgrade(config, "20260717_0013")
    downgraded = inspect(create_engine(database_url))
    assert "model_runs" not in downgraded.get_table_names()
    assert "operation_key" not in {
        column["name"] for column in downgraded.get_columns("concept_turns")
    }
    command.upgrade(config, "head")


@pytest.mark.skipif(
    not os.environ.get("SIFT_TEST_POSTGRES_URL"),
    reason="SIFT_TEST_POSTGRES_URL is required for the PostgreSQL migration smoke test",
)
def test_alembic_upgrade_head_on_postgres(monkeypatch) -> None:
    database_url = os.environ["SIFT_TEST_POSTGRES_URL"]
    monkeypatch.setenv("SIFT_DATABASE_URL", database_url)

    config = Config(str(BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    command.upgrade(config, "head")

    inspector = inspect(create_engine(database_url))
    assert "concepts" in inspector.get_table_names()
    assert "beta_sessions" in inspector.get_table_names()
    assert "managed_provider_connections" in inspector.get_table_names()
    assert "model_runs" in inspector.get_table_names()
    assert "operation_key" in {
        column["name"] for column in inspector.get_columns("concept_turns")
    }
