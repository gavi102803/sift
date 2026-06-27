#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path


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
        provider_check(settings),
    ]
    for check in checks:
        marker = "OK" if check.ok else "FAIL"
        print(f"[{marker}] {check.name}: {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


def backend_check(base_url: str, *, skip: bool) -> Check:
    if skip:
        return Check("backend", True, "skipped network check")
    health_url = base_url.rstrip("/") + "/health"
    try:
        with urllib.request.urlopen(health_url, timeout=2) as response:
            if response.status == 200:
                return Check("backend", True, f"reachable at {base_url}")
            return Check("backend", False, f"unexpected HTTP {response.status} at {health_url}")
    except urllib.error.URLError as error:
        return Check(
            "backend",
            False,
            f"could not connect to {base_url}; start scripts/run_local_companion.sh",
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


def redact_database_url(database_url: str) -> str:
    lowered = database_url.lower()
    if "@" not in database_url or not any(prefix in lowered for prefix in ("://", "postgres")):
        return database_url
    scheme, rest = database_url.split("://", 1)
    host = rest.rsplit("@", 1)[-1]
    return f"{scheme}://***@{host}"


if __name__ == "__main__":
    raise SystemExit(main())
