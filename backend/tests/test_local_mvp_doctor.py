from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

from sift_backend.config import Settings


def _load_doctor_module():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "local_mvp_doctor.py"
    spec = importlib.util.spec_from_file_location("local_mvp_doctor", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


doctor = _load_doctor_module()


def test_safe_display_url_redacts_userinfo_and_secret_query_values() -> None:
    assert doctor.safe_display_url(
        "https://user:password@mac.tailnet.ts.net:8443/status?api_key=secret&ok=1"
    ) == "https://mac.tailnet.ts.net:8443/status?api_key=%2A%2A%2A&ok=1"


def test_backend_check_tailnet_failure_uses_safe_url_and_tailnet_hint() -> None:
    check = doctor.backend_check(
        "https://user:password@mac.tailnet.ts.net/health?token=secret",
        skip=False,
    )

    assert check.ok is False
    assert "mac.tailnet.ts.net" in check.detail
    assert "--tailnet" in check.detail
    assert "password" not in check.detail
    assert "secret" not in check.detail
    assert "token=%2A%2A%2A" in check.detail


def test_provider_check_does_not_leak_credentials() -> None:
    settings = Settings(
        runtime_provider="deepseek",
        runtime_api_key="deepseek-secret",
        runtime_model="deepseek-chat",
        web_search_provider="tavily",
        web_search_api_key="tavily-secret",
    )

    check = doctor.provider_check(settings)

    assert check.ok is True
    assert "deepseek-secret" not in check.detail
    assert "tavily-secret" not in check.detail
    assert "apiKey=configured" in check.detail


def test_migration_check_rejects_stale_sqlite_revision(tmp_path) -> None:
    database = tmp_path / "stale.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('20260629_0010')")

    check = doctor.migration_check(f"sqlite:///{database}")

    assert check.ok is False
    assert "revision=20260629_0010" in check.detail
    assert "expected=20260721_0017" in check.detail


def test_migration_check_accepts_current_sqlite_revision(tmp_path) -> None:
    database = tmp_path / "current.db"
    with sqlite3.connect(database) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('20260721_0017')")

    check = doctor.migration_check(f"sqlite:///{database}")

    assert check.ok is True
    assert check.detail == "database revision=20260721_0017"
