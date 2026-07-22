import asyncio
import json
import multiprocessing
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts.recovery_dogfood import LEGACY_QUESTIONS_HASH, DogfoodError, DogfoodSession

from sift_backend.concepts.service import ConceptService, MockConceptModelService
from sift_backend.config import Settings
from sift_backend.main import create_app
from sift_backend.persistence.concept_store import PersistentConceptStore
from sift_backend.persistence.database import create_session_factory
from sift_backend.persistence.models import CaptureAttemptRecord, ModelRunRecord, TurnRecord

ROOT = Path(__file__).resolve().parents[2]


class _SlowMockConceptModelService(MockConceptModelService):
    async def stream_turn_answer(self, concept, request, recent_turns=None, card_memory=""):
        await asyncio.sleep(0.1)
        async for event in super().stream_turn_answer(
            concept, request, recent_turns, card_memory
        ):
            yield event


def _run_mock_server(database_url: str, port: int) -> None:
    import uvicorn

    sessions = create_session_factory(database_url)
    service = ConceptService(
        store=PersistentConceptStore(sessions),
        model_service=_SlowMockConceptModelService(),
    )
    app = create_app(
        Settings(database_url=database_url, runtime_provider="mock"),
        concept_service=service,
        session_factory=sessions,
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_for_health(base_url: str) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(base_url + "/health", timeout=1) as response:
                if json.loads(response.read())["status"] == "ok":
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.05)
    raise AssertionError("mock backend did not become healthy")


def _wait_for_follow_ups(sessions, minimum: int) -> None:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        with sessions() as session:
            count = session.query(ModelRunRecord).filter_by(kind="followUp").count()
        if count >= minimum:
            return
        time.sleep(0.05)
    raise AssertionError(f"runner did not create {minimum} follow-up runs")


def test_recovery_dogfood_runs_twenty_turns_and_resumes_without_duplicates(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'sift.db'}"
    sessions = create_session_factory(database_url)
    state_path = tmp_path / "dogfood-state.json"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    context = multiprocessing.get_context("spawn")
    process = context.Process(
        target=_run_mock_server,
        args=(database_url, port),
    )
    process.start()
    command = [
        sys.executable,
        str(ROOT / "scripts" / "recovery_dogfood.py"),
        "--backend-url",
        base_url,
        "--state-file",
        str(state_path),
        "--recovery-timeout-seconds",
        "20",
        "--request-timeout-seconds",
        "0.5",
    ]
    try:
        _wait_for_health(base_url)
        runner = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        _wait_for_follow_ups(sessions, 5)
        process.kill()
        process.join(timeout=5)
        with sessions() as session:
            for run in session.query(ModelRunRecord).filter_by(status="running"):
                run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        time.sleep(2)
        process = context.Process(target=_run_mock_server, args=(database_url, port))
        process.start()
        _wait_for_health(base_url)
        first_stdout, first_stderr = runner.communicate(timeout=30)
        second = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
    finally:
        if process.is_alive():
            process.kill()
        process.join(timeout=5)

    assert runner.returncode == 0, first_stderr
    assert second.returncode == 0, second.stderr
    summary = json.loads(first_stdout)
    assert summary["passed"] is True
    assert summary["provider"] == "mock"
    assert summary["followUpsSucceeded"] == 20
    assert summary["persistedTurns"] == summary["expectedTurns"] == 42
    assert summary["idempotentReplayPassed"] is True
    assert summary["eventIntegrityPassed"] is True
    assert summary["maintenancePassed"] is True
    assert summary["maintenanceRuns"]["continuitySummary"]["succeeded"] > 0
    assert summary["earlyContextRecallPassed"] is None
    assert summary["transientNetworkFailures"] > 0
    assert json.loads(second.stdout)["passed"] is True

    stored_state = state_path.read_text()
    assert "answer" not in stored_state
    assert "SIFT-CONTINUITY-ANCHOR" not in stored_state
    assert "请用一句话" not in stored_state
    with sessions() as session:
        assert session.query(CaptureAttemptRecord).count() == 1
        assert session.query(TurnRecord).count() == 42
        assert session.query(ModelRunRecord).filter_by(kind="initialConcept").count() == 1
        assert session.query(ModelRunRecord).filter_by(kind="followUp").count() == 20


def test_recovery_dogfood_requires_explicit_live_cost_confirmation(tmp_path) -> None:
    session = DogfoodSession(
        backend_url="http://127.0.0.1:9",
        state_path=tmp_path / "state.json",
        request_timeout=0.1,
        recovery_timeout=0.1,
    )
    session.request = lambda *_args, **_kwargs: {"modelProvider": "deepseek"}  # type: ignore[method-assign]

    with pytest.raises(DogfoodError, match="--confirm-live-cost"):
        session.run(confirm_live_cost=False)


def test_recovery_dogfood_can_retry_one_failed_turn_without_replaying_progress(tmp_path) -> None:
    session = DogfoodSession(
        backend_url="http://127.0.0.1:9",
        state_path=tmp_path / "state.json",
        request_timeout=0.1,
        recovery_timeout=0.1,
    )
    session.state["turnRunIds"] = ["failed-run"]
    session.state["pendingTurnIndex"] = 0
    session.state["pendingRunId"] = "failed-run"
    posted_headers = None

    def request(method, path, *, body=None, headers=None):
        nonlocal posted_headers
        if method == "POST":
            posted_headers = headers
            return {"id": "retry-run", "status": "queued"}
        if path.endswith("failed-run"):
            return {"id": "failed-run", "status": "failed"}
        return {"id": "retry-run", "status": "succeeded"}

    session.request = request  # type: ignore[method-assign]

    run = session._ensure_follow_up(  # noqa: SLF001
        0,
        "concept-id",
        retry_failed_runs=True,
    )

    assert run["id"] == "retry-run"
    assert posted_headers == {
        "Idempotency-Key": f"{session.state['sessionId']}-turn-0-retry-1"
    }
    assert session.state["turnRunIds"] == ["retry-run"]
    assert session.state["completedFollowUps"] == 0


def test_recovery_dogfood_migrates_protocol_before_changed_recall_turn(tmp_path) -> None:
    state_path = tmp_path / "state.json"
    original = DogfoodSession(
        backend_url="http://127.0.0.1:9",
        state_path=state_path,
        request_timeout=0.1,
        recovery_timeout=0.1,
    )
    original.state["questionsHash"] = LEGACY_QUESTIONS_HASH
    original.state["completedFollowUps"] = 11
    original._save_state()  # noqa: SLF001

    migrated = DogfoodSession(
        backend_url="http://127.0.0.1:9",
        state_path=state_path,
        request_timeout=0.1,
        recovery_timeout=0.1,
    )

    assert migrated.state["version"] == 2
    assert migrated.state["questionsHash"] != LEGACY_QUESTIONS_HASH
    assert migrated.state["completedFollowUps"] == 11
