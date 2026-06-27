from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect

from alembic import command


def test_alembic_upgrade_head_creates_owner_and_idempotency_tables(
    tmp_path,
    monkeypatch,
) -> None:
    database_url = f"sqlite:///{tmp_path / 'migration-smoke.db'}"
    monkeypatch.setenv("SIFT_DATABASE_URL", database_url)
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(tmp_path / "provider.json"))

    config = Config(str(Path("backend/alembic.ini").resolve()))
    config.set_main_option("script_location", str(Path("backend/alembic").resolve()))

    command.upgrade(config, "head")

    engine = create_engine(database_url)
    inspector = inspect(engine)

    assert "capture_attempts" in inspector.get_table_names()
    assert "idempotency_records" in inspector.get_table_names()
    assert "owner_id" in {column["name"] for column in inspector.get_columns("concepts")}
