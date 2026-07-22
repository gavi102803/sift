from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Register identity tables on the shared metadata before create_all is used in local/test mode.
from sift_backend.identity_access import persistence as _identity_persistence  # noqa: F401, E402
from sift_backend.persistence.models import Base
from sift_backend.runtime import managed_connections as _managed_connections  # noqa: F401, E402


def create_session_factory(
    database_url: str,
    *,
    initialize_schema: bool = True,
) -> sessionmaker[Session]:
    connect_args: dict[str, Any] = {}
    if database_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False
        _ensure_sqlite_parent_dir(database_url)

    engine_options: dict[str, Any] = {"connect_args": connect_args}
    if database_url in {"sqlite://", "sqlite:///:memory:"}:
        engine_options["poolclass"] = StaticPool
    engine = create_engine(database_url, **engine_options)
    if initialize_schema:
        initialize_database(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        _ensure_sqlite_schema(engine)


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    if not database_url.startswith("sqlite:///"):
        return

    path = database_url.removeprefix("sqlite:///")
    if path in {":memory:", ""}:
        return

    Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)


def _ensure_sqlite_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "concept_turns" not in table_names:
        return

    columns = {column["name"] for column in inspector.get_columns("concept_turns")}
    if "answer_source_json" not in columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE concept_turns ADD COLUMN answer_source_json TEXT"))
    if "operation_key" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE concept_turns ADD COLUMN operation_key VARCHAR(255)")
            )
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_concept_turn_operation_role "
                "ON concept_turns (concept_id, operation_key, role)"
            )
        )

    if "concepts" not in table_names:
        return

    concept_columns = {column["name"] for column in inspector.get_columns("concepts")}
    if "answer_source_json" not in concept_columns:
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE concepts ADD COLUMN answer_source_json TEXT"))
    if "archived_from_status" not in concept_columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE concepts ADD COLUMN archived_from_status VARCHAR(32)")
            )

    if "note_blocks" not in table_names:
        return

    block_columns = {column["name"] for column in inspector.get_columns("note_blocks")}
    with engine.begin() as connection:
        if "revision" not in block_columns:
            connection.execute(
                text("ALTER TABLE note_blocks ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
            )
        if "supported_claim_ids_json" not in block_columns:
            connection.execute(
                text(
                    "ALTER TABLE note_blocks "
                    "ADD COLUMN supported_claim_ids_json TEXT NOT NULL DEFAULT '[]'"
                )
            )
        if "created_at" not in block_columns:
            connection.execute(text("ALTER TABLE note_blocks ADD COLUMN created_at DATETIME"))
        if "updated_at" not in block_columns:
            connection.execute(text("ALTER TABLE note_blocks ADD COLUMN updated_at DATETIME"))
