#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import http.client
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from sift_backend.config import load_settings  # noqa: E402


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str


def main() -> int:
    parser = argparse.ArgumentParser(description="Check Sift local-first MVP readiness.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--no-network",
        action="store_true",
        help="Skip backend HTTP checks; useful for credential leakage tests.",
    )
    args = parser.parse_args()

    settings = load_settings()
    checks = [
        backend_check(args.backend_url, skip=args.no_network),
        sqlite_check(settings.database_url),
        migration_check(settings.database_url),
        provider_check(settings),
    ]
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


def backend_check(base_url: str, *, skip: bool) -> Check:
    display_url = safe_display_url(base_url)
    if skip:
        return Check("backend", True, "skipped network check")
    health_url = base_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(health_url, timeout=2) as response:
            if response.status == 200:
                return Check("backend", True, f"reachable at {display_url}{tailnet_hint(base_url)}")
            return Check(
                "backend",
                False,
                f"unexpected HTTP {response.status} at {safe_display_url(health_url)}",
            )
    except (urllib.error.URLError, ValueError, http.client.InvalidURL):
        return Check(
            "backend",
            False,
            f"could not connect to {display_url}; start scripts/run_local_companion.sh"
            f"{tailnet_start_hint(base_url)}",
        )


def sqlite_check(database_url: str) -> Check:
    if not database_url.startswith("sqlite:///"):
        return Check("sqlite", True, f"non-sqlite database configured: {redact_database_url(database_url)}")

    raw_path = database_url.removeprefix("sqlite:///")
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = (ROOT / "backend" / db_path).resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with sqlite3.connect(db_path) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS _sift_doctor_write_check (id INTEGER)")
            connection.execute("DELETE FROM _sift_doctor_write_check")
            connection.execute("INSERT INTO _sift_doctor_write_check (id) VALUES (1)")
            connection.execute("DELETE FROM _sift_doctor_write_check")
            connection.commit()
    except sqlite3.Error as error:
        return Check("sqlite", False, f"not writable at {db_path}: {error}")
    return Check("sqlite", True, f"writable at {db_path}")


def migration_check(database_url: str) -> Check:
    if not database_url.startswith("sqlite:///"):
        return Check("migration", True, "managed database migration is checked by deployment")

    db_path = sqlite_path(database_url)
    if not db_path.exists():
        return Check("migration", False, f"database does not exist at {db_path}")

    expected = expected_migration_head()
    try:
        with sqlite3.connect(db_path) as connection:
            row = connection.execute("SELECT version_num FROM alembic_version").fetchone()
    except sqlite3.Error as error:
        return Check("migration", False, f"could not read Alembic version: {error}")

    current = row[0] if row else None
    if current != expected:
        return Check(
            "migration",
            False,
            f"database revision={current or '(none)'}, expected={expected}; run Alembic upgrade",
        )
    return Check("migration", True, f"database revision={current}")


def expected_migration_head() -> str:
    revisions: set[str] = set()
    parents: set[str] = set()
    versions = ROOT / "backend" / "alembic" / "versions"
    for path in versions.glob("*.py"):
        values: dict[str, str | None] = {}
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, (str, type(None))):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id in {"revision", "down_revision"}:
                    values[target.id] = value.value
        revision = values.get("revision")
        parent = values.get("down_revision")
        if revision:
            revisions.add(revision)
        if parent:
            parents.add(parent)
    heads = revisions - parents
    if len(heads) != 1:
        raise RuntimeError(f"expected one migration head, found {sorted(heads)}")
    return heads.pop()


def sqlite_path(database_url: str) -> Path:
    raw_path = database_url.removeprefix("sqlite:///")
    db_path = Path(raw_path)
    if not db_path.is_absolute():
        db_path = (ROOT / "backend" / db_path).resolve()
    return db_path


def provider_check(settings) -> Check:
    provider = settings.runtime_provider if settings.runtime_api_key else "mock"
    key_state = "configured" if settings.runtime_api_key else "missing"
    web_state = "enabled" if settings.runtime_web_search_enabled else "disabled"
    detail = (
        f"provider={provider}, model={settings.runtime_model or '(unset)'}, "
        f"baseURL={settings.runtime_base_url or '(unset)'}, apiKey={key_state}, "
        f"webSearch={web_state}, webProvider={settings.web_search_provider}"
    )
    if provider == "mock":
        return Check("provider", False, detail + "; real provider is not configured")
    return Check("provider", True, detail)


def safe_display_url(raw_url: str) -> str:
    """Return a diagnostic-safe URL string without credentials or secret query values."""
    try:
        parsed = urlsplit(raw_url)
    except ValueError:
        return "(invalid URL)"
    if not parsed.scheme or not parsed.netloc:
        return raw_url

    host = parsed.hostname or ""
    netloc = host
    if parsed.port is not None:
        netloc = f"{netloc}:{parsed.port}"

    safe_query = urlencode(
        [
            (key, _redacted_query_value(key, value))
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        ]
    )
    return urlunsplit((parsed.scheme, netloc, parsed.path, safe_query, parsed.fragment))


def tailnet_hint(raw_url: str) -> str:
    try:
        host = urlsplit(raw_url).hostname or ""
    except ValueError:
        return ""
    if host.endswith(".ts.net"):
        return " (Tailnet HTTPS)"
    return ""


def tailnet_start_hint(raw_url: str) -> str:
    try:
        host = urlsplit(raw_url).hostname or ""
    except ValueError:
        return ""
    if host.endswith(".ts.net"):
        return " --tailnet and verify Tailscale MagicDNS/HTTPS"
    return ""


def _redacted_query_value(key: str, value: str) -> str:
    lowered = key.lower()
    if any(marker in lowered for marker in ("key", "token", "secret", "password", "auth")):
        return "***"
    return value


def redact_database_url(database_url: str) -> str:
    lowered = database_url.lower()
    if "@" not in database_url or not any(prefix in lowered for prefix in ("://", "postgres")):
        return database_url
    scheme, rest = database_url.split("://", 1)
    host = rest.rsplit("@", 1)[-1]
    return f"{scheme}://***@{host}"


if __name__ == "__main__":
    raise SystemExit(main())
