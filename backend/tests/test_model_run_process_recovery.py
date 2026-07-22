import json
import multiprocessing
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session

from sift_backend.concepts.service import ConceptService, MockConceptModelService
from sift_backend.config import Settings
from sift_backend.main import create_app
from sift_backend.persistence.concept_store import PersistentConceptStore
from sift_backend.persistence.database import create_session_factory
from sift_backend.persistence.models import (
    ConceptRecord,
    ModelRunEventRecord,
    ModelRunRecord,
    NoteRevisionRecord,
    TurnRecord,
)


class _CountingModelService(MockConceptModelService):
    def __init__(self, counter_path: Path) -> None:
        self.counter_path = counter_path

    async def stream_initial_concept(self, title: str, locale: str):
        count = int(self.counter_path.read_text() or "0") if self.counter_path.exists() else 0
        self.counter_path.write_text(str(count + 1))
        async for event in super().stream_initial_concept(title, locale):
            yield event


class _PausingConceptStore(PersistentConceptStore):
    def __init__(self, session_factory, pause_marker: Path) -> None:
        super().__init__(session_factory)
        self.pause_marker = pause_marker

    @contextmanager
    def transaction(self, session: Session):
        with super().transaction(session):
            if not self.pause_marker.exists():
                self.pause_marker.write_text("paused after model checkpoint")
                time.sleep(30)
            yield


def _run_fault_server(database_url: str, counter: str, marker: str, port: int) -> None:
    import uvicorn

    sessions = create_session_factory(database_url)
    service = ConceptService(
        store=_PausingConceptStore(sessions, Path(marker)),
        model_service=_CountingModelService(Path(counter)),
    )
    app = create_app(
        Settings(runtime_api_key="", database_url=database_url),
        concept_service=service,
        session_factory=sessions,
    )
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _request_json(
    base_url: str,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    headers: dict[str, str] | None = None,
) -> dict:
    request = urllib.request.Request(
        base_url + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    with urllib.request.urlopen(request, timeout=2) as response:
        return json.loads(response.read())


def _wait_until(predicate, *, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if predicate():
                return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.05)
    raise AssertionError("condition did not become true before timeout")


def _stop(process: multiprocessing.Process) -> None:
    if process.is_alive():
        process.kill()
    process.join(timeout=5)
    assert not process.is_alive()


def test_backend_process_kill_after_checkpoint_recovers_without_reinvoking_model(tmp_path) -> None:
    database_url = f"sqlite:///{tmp_path / 'sift.db'}"
    sessions = create_session_factory(database_url)
    counter = tmp_path / "model-call-count"
    marker = tmp_path / "domain-commit-paused"
    port = _free_port()
    base_url = f"http://127.0.0.1:{port}"
    context = multiprocessing.get_context("spawn")

    first = context.Process(
        target=_run_fault_server,
        args=(database_url, str(counter), str(marker), port),
    )
    first.start()
    request_finished: dict[str, object] = {}

    def create_run() -> None:
        try:
            request_finished["result"] = _request_json(
                base_url,
                "/v1/concept-runs",
                method="POST",
                headers={"Idempotency-Key": "process-kill-capture"},
                body={
                    "capture": {"rawCapture": "Process recovery", "locale": "en"},
                    "clientDraftId": "process-recovery-draft",
                },
            )
        except OSError as error:
            request_finished["error"] = error

    request_thread = threading.Thread(target=create_run)
    try:
        _wait_until(lambda: _request_json(base_url, "/health")["status"] == "ok")
        request_thread.start()

        def checkpoint_reached() -> bool:
            with sessions() as session:
                record = session.query(ModelRunRecord).one_or_none()
                return bool(
                    marker.exists()
                    and record is not None
                    and record.checkpoint == "modelCompleted"
                )

        _wait_until(checkpoint_reached)
    finally:
        _stop(first)
        request_thread.join(timeout=5)

    with sessions() as session:
        run_record = session.query(ModelRunRecord).one()
        run_id = run_record.id

    with sessions() as session:
        assert session.query(ConceptRecord).count() == 0
        assert session.query(TurnRecord).count() == 0
        crashed = session.get(ModelRunRecord, run_id)
        assert crashed is not None
        assert crashed.status == "running"
        assert crashed.checkpoint == "modelCompleted"
        crashed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    second = context.Process(
        target=_run_fault_server,
        args=(database_url, str(counter), str(marker), port),
    )
    second.start()
    try:
        _wait_until(lambda: _request_json(base_url, "/health")["status"] == "ok")
        _wait_until(
            lambda: _request_json(base_url, f"/v1/model-runs/{run_id}")["status"]
            == "succeeded"
        )
    finally:
        _stop(second)

    assert counter.read_text() == "1"
    with sessions() as session:
        assert session.query(ConceptRecord).count() == 1
        assert session.query(TurnRecord).count() == 2
        assert session.query(NoteRevisionRecord).count() == 1
        completed = session.get(ModelRunRecord, run_id)
        assert completed is not None and completed.status == "succeeded"
        assert (
            session.query(ModelRunEventRecord)
            .filter_by(run_id=run_id, event_type="completed")
            .count()
            == 1
        )
