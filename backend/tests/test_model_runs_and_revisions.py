import asyncio
import json
import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker

from sift_backend.api.concepts import stream_create_concept
from sift_backend.concepts.service import (
    ConceptService,
    ConceptTurnStreamDelta,
    MockConceptModelService,
)
from sift_backend.config import Settings
from sift_backend.main import create_app
from sift_backend.model_runtime.model_runs import (
    ModelRunCoordinator,
    ModelRunLeaseLost,
    ModelRunRepository,
)
from sift_backend.persistence.concept_store import PersistentConceptStore
from sift_backend.persistence.database import initialize_database
from sift_backend.persistence.models import (
    CaptureAttemptRecord,
    ConceptContinuitySummaryRecord,
    ConceptMaintenanceStateRecord,
    ConceptRecord,
    ModelRunRecord,
    NoteRevisionRecord,
    TurnRecord,
    UpdateEventRecord,
    UpdateProposalRecord,
)
from sift_backend.schemas.concepts import (
    ConceptTurnRequest,
    CreateConceptRequest,
    UpdateConceptSummaryRequest,
)
from sift_backend.schemas.model_outputs import (
    ContinuitySummaryEntry,
    ContinuitySummaryResult,
    ModelUpdateProposal,
)
from sift_backend.schemas.model_runs import ModelRunKind
from sift_backend.schemas.patches import AppendPatchOperation


class CountingModelService(MockConceptModelService):
    def __init__(self) -> None:
        self.initial_stream_calls = 0
        self.turn_stream_calls = 0

    async def stream_initial_concept(self, title: str, locale: str):
        self.initial_stream_calls += 1
        async for event in super().stream_initial_concept(title, locale):
            yield event

    async def stream_turn_answer(self, concept, request, recent_turns=None, card_memory=""):
        self.turn_stream_calls += 1
        async for event in super().stream_turn_answer(
            concept, request, recent_turns, card_memory
        ):
            yield event


class ReviewProposalModelService(MockConceptModelService):
    async def answer_maintenance_review(self, concept, recent_turns, card_memory):
        result = await super().answer_maintenance_review(concept, recent_turns, card_memory)
        return result.model_copy(
            update={
                "proposal": ModelUpdateProposal(
                    baseNoteRevision=concept.note_revision,
                    patchOperations=[
                        AppendPatchOperation(
                            operation="append",
                            targetBlockId=concept.blocks[0].id,
                            content="Periodic durable insight",
                        )
                    ],
                    rationale="Repeated follow-ups support a durable clarification.",
                )
            }
        )


class SemanticSummaryModelService(MockConceptModelService):
    async def summarize_continuity(self, concept, source_turns):
        first_id = source_turns[0][0]
        last_id = source_turns[-1][0]
        return ContinuitySummaryResult(
            priorAnswers=[
                ContinuitySummaryEntry(
                    content="Earlier answers established the working definition.",
                    sourceTurnIds=[first_id],
                )
            ],
            userContext=[
                ContinuitySummaryEntry(
                    content="The user prefers concrete examples.",
                    sourceTurnIds=[last_id],
                )
            ],
        )


class InvalidSummarySourceModelService(MockConceptModelService):
    async def summarize_continuity(self, concept, source_turns):
        return ContinuitySummaryResult(
            openQuestions=[
                ContinuitySummaryEntry(
                    content="Unsupported source reference.",
                    sourceTurnIds=[999999],
                )
            ]
        )


def _sessions(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'sift.db'}", connect_args={"check_same_thread": False}
    )
    initialize_database(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _client(tmp_path, *, model_service=None):
    sessions = _sessions(tmp_path)
    service = ConceptService(
        store=PersistentConceptStore(sessions), model_service=model_service
    )
    app = create_app(
        Settings(runtime_api_key="", database_url=f"sqlite:///{tmp_path / 'sift.db'}"),
        concept_service=service,
        session_factory=sessions,
    )
    return TestClient(app), sessions


def _terminal(client: TestClient, run_id: str) -> dict:
    for _ in range(100):
        body = client.get(f"/v1/model-runs/{run_id}").json()
        if body["status"] in {"succeeded", "failed"}:
            return body
        time.sleep(0.01)
    raise AssertionError("model run did not finish")


def test_model_run_is_idempotent_and_survives_stream_consumer(tmp_path) -> None:
    client, sessions = _client(tmp_path)
    with client:
        first = client.post(
            "/v1/concept-runs",
            headers={"Idempotency-Key": "capture-1"},
            json={"capture": {"rawCapture": "RAG", "locale": "en"}, "clientDraftId": "draft-1"},
        )
        duplicate = client.post(
            "/v1/concept-runs",
            headers={"Idempotency-Key": "capture-1"},
            json={"capture": {"rawCapture": "RAG", "locale": "en"}, "clientDraftId": "draft-1"},
        )
        assert first.status_code == 200
        assert first.json()["createdAt"].endswith("Z")
        assert first.json()["updatedAt"].endswith("Z")
        assert duplicate.json()["id"] == first.json()["id"]
        completed = _terminal(client, first.json()["id"])
        assert completed["status"] == "succeeded"
        assert completed["agentSpec"] == "sift.initial-concept"
        assert completed["agentSpecVersion"] == "1.0"
        assert completed["promptVersion"] == "initial-concept-v1"
        assert completed["budget"]["maxSteps"] == 4
        assert completed["currentStep"] == "validate"
        assert completed["terminationReason"] == "completed"
        assert completed["result"]["concept"]["displayTitle"] == "RAG"
        events = client.get(f"/v1/model-runs/{completed['id']}/events?afterSequence=0").json()
        assert events[-1]["type"] == "completed"
        assert any(event["type"] == "stepStarted" for event in events)
        assert any(event["type"] == "stepCompleted" for event in events)
        assert all(event["createdAt"].endswith("Z") for event in events)
    with sessions() as session:
        assert session.query(ModelRunRecord).count() == 1


def test_legacy_create_and_turn_routes_commit_through_model_runs(tmp_path) -> None:
    client, sessions = _client(tmp_path)
    with client:
        concept = client.post(
            "/v1/concepts",
            headers={"Idempotency-Key": "legacy-capture"},
            json={"rawCapture": "Legacy bridge", "locale": "en"},
        )
        assert concept.status_code == 200
        turn = client.post(
            f"/v1/concepts/{concept.json()['id']}/turns",
            headers={"Idempotency-Key": "legacy-turn"},
            json={"question": "Does this survive disconnects?"},
        )
        assert turn.status_code == 200

    with sessions() as session:
        runs = session.query(ModelRunRecord).order_by(ModelRunRecord.created_at).all()
        assert [(run.kind, run.status) for run in runs] == [
            ("initialConcept", "succeeded"),
            ("followUp", "succeeded"),
        ]
        assert session.query(ConceptRecord).count() == 1
        assert session.query(TurnRecord).count() == 4


def test_legacy_stream_disconnect_leaves_model_run_running_to_completion(tmp_path) -> None:
    model = CountingModelService()
    client, sessions = _client(tmp_path, model_service=model)
    app = client.app

    async def disconnect_after_started() -> None:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/v1/concepts/stream",
                "headers": [(b"idempotency-key", b"legacy-disconnect")],
                "app": app,
            }
        )
        request.state.principal = app.state.concept_service.principal
        response = await stream_create_concept(
            request,
            CreateConceptRequest(rawCapture="Disconnect-safe", locale="en"),
        )
        iterator = response.body_iterator
        first = await anext(iterator)
        assert '"type":"started"' in str(first)
        await iterator.aclose()

        for _ in range(100):
            runs = app.state.model_run_repository.list("local-dev", active=False)
            if runs and runs[0].status.value in {"succeeded", "failed"}:
                break
            await asyncio.sleep(0.01)
        else:
            raise AssertionError("legacy model run did not finish after stream disconnect")
        assert runs[0].status.value == "succeeded"

    asyncio.run(disconnect_after_started())
    assert model.initial_stream_calls == 1
    with sessions() as session:
        assert session.query(ModelRunRecord).count() == 1
        assert session.query(ConceptRecord).count() == 1
        assert session.query(TurnRecord).count() == 2


def test_model_run_owner_isolation_returns_not_found(tmp_path) -> None:
    client, _ = _client(tmp_path)
    with client:
        run = client.post(
            "/v1/concept-runs",
            headers={"Idempotency-Key": "capture-owner"},
            json={"capture": {"rawCapture": "Owner", "locale": "en"}},
        ).json()
        client.app.state.model_run_repository.get(run["id"], "local-dev")
        try:
            client.app.state.model_run_repository.get(run["id"], "other-owner")
        except Exception as error:
            assert getattr(error, "status_code", None) == 404
        else:
            raise AssertionError("cross-owner run read should fail")


def test_model_run_lease_serializes_same_concept_and_recovers_after_expiry(tmp_path) -> None:
    sessions = _sessions(tmp_path)
    service = ConceptService(store=PersistentConceptStore(sessions))
    concept = service.create_concept(CreateConceptRequest(rawCapture="Serialized concept"))
    repository = ModelRunRepository(sessions)
    first, _ = repository.create(
        owner_id=service.owner_id,
        kind=ModelRunKind.follow_up,
        idempotency_key="serial-1",
        payload={"turn": {"question": "First"}},
        concept_id=concept.id,
    )
    second, _ = repository.create(
        owner_id=service.owner_id,
        kind=ModelRunKind.follow_up,
        idempotency_key="serial-2",
        payload={"turn": {"question": "Second"}},
        concept_id=concept.id,
    )

    assert repository.begin(first.id, "worker-one") is True
    assert repository.begin(second.id, "worker-two") is False

    with sessions() as session:
        active = session.get(ModelRunRecord, str(first.id))
        assert active is not None
        active.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()

    assert repository.begin(second.id, "worker-two") is True
    with sessions() as session:
        expired = session.get(ModelRunRecord, str(first.id))
        replacement = session.get(ModelRunRecord, str(second.id))
        assert expired is not None and expired.status == "queued"
        assert replacement is not None and replacement.status == "running"


def test_model_run_heartbeat_renews_only_the_lease_owner(tmp_path) -> None:
    sessions = _sessions(tmp_path)
    repository = ModelRunRepository(sessions)
    run, _ = repository.create(
        owner_id="local-dev",
        kind=ModelRunKind.initial_concept,
        idempotency_key="heartbeat",
        payload={"capture": {"rawCapture": "Heartbeat", "locale": "en"}},
    )
    assert repository.begin(run.id, "lease-owner") is True
    with sessions() as session:
        record = session.get(ModelRunRecord, str(run.id))
        assert record is not None
        before = record.lease_expires_at

    assert repository.renew_lease(run.id, "other-worker") is False
    assert repository.renew_lease(run.id, "lease-owner") is True
    with sessions() as session:
        record = session.get(ModelRunRecord, str(run.id))
        assert record is not None and before is not None
        assert record.lease_expires_at >= before


def test_stale_worker_is_fenced_from_events_checkpoint_and_terminal_write(tmp_path) -> None:
    sessions = _sessions(tmp_path)
    repository = ModelRunRepository(sessions)
    run, _ = repository.create(
        owner_id="local-dev",
        kind=ModelRunKind.initial_concept,
        idempotency_key="fenced-worker",
        payload={"capture": {"rawCapture": "Fencing", "locale": "en"}},
    )
    assert repository.begin(run.id, "worker-one") is True
    with sessions() as session:
        record = session.get(ModelRunRecord, str(run.id))
        assert record is not None
        record.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.commit()
    assert repository.begin(run.id, "worker-two") is True

    with pytest.raises(ModelRunLeaseLost):
        repository.delta(run.id, "stale delta", worker_id="worker-one")
    with pytest.raises(ModelRunLeaseLost):
        repository.checkpoint(
            run.id,
            "modelCompleted",
            {"concept": {}},
            worker_id="worker-one",
        )
    with pytest.raises(ModelRunLeaseLost):
        repository.succeed(
            run.id,
            {"concept": {}},
            worker_id="worker-one",
        )

    current = repository.get(run.id, "local-dev")
    assert current.status.value == "running"
    assert current.checkpoint is None
    assert all(event.data != {"content": "stale delta"} for event in repository.events(
        run.id, "local-dev", 0
    ))


def test_initial_domain_commit_rolls_back_if_terminal_event_fails(tmp_path, monkeypatch) -> None:
    sessions = _sessions(tmp_path)
    store = PersistentConceptStore(sessions)
    service = ConceptService(store=store)
    repository = ModelRunRepository(sessions)
    request = CreateConceptRequest(rawCapture="Atomic capture", locale="en")
    run, _ = repository.create(
        owner_id=service.owner_id,
        kind=ModelRunKind.initial_concept,
        idempotency_key="atomic-capture",
        payload={"capture": request.model_dump(mode="json", by_alias=True)},
    )

    async def prepare():
        concept = None
        async for event in service.prepare_initial_concept_stream(request):
            if not isinstance(event, ConceptTurnStreamDelta):
                concept = event
        return concept

    concept = asyncio.run(prepare())
    assert concept is not None
    assert repository.begin(run.id, "worker") is True
    repository.checkpoint(
        run.id,
        "modelCompleted",
        {"concept": concept.model_dump(mode="json", by_alias=True)},
        worker_id="worker",
    )
    append_event = repository._append_event

    def fail_completed_event(session, run_id, event_type, data):
        if event_type == "completed":
            raise RuntimeError("simulated terminal write failure")
        append_event(session, run_id, event_type, data)

    monkeypatch.setattr(repository, "_append_event", fail_completed_event)

    def commit_initial(_session):
        result = service.commit_prepared_initial_concept(
            request,
            concept,
            run.idempotency_key,
        )
        final_data = {"concept": result.model_dump(mode="json", by_alias=True)}
        return result, final_data, str(result.id)

    with pytest.raises(RuntimeError, match="terminal write failure"):
        repository.commit_domain_and_succeed(
            run.id,
            worker_id="worker",
            transaction=store.transaction,
            action=commit_initial,
        )

    with sessions() as session:
        assert session.query(ConceptRecord).count() == 0
        assert session.query(CaptureAttemptRecord).count() == 0
        assert session.query(TurnRecord).count() == 0
        assert session.query(NoteRevisionRecord).count() == 0
        current = session.get(ModelRunRecord, str(run.id))
        assert current is not None
        assert current.status == "running"
        assert current.checkpoint == "modelCompleted"


def test_terminal_model_run_compacts_stream_deltas(tmp_path) -> None:
    sessions = _sessions(tmp_path)
    repository = ModelRunRepository(sessions)
    run, _ = repository.create(
        owner_id="local-dev",
        kind=ModelRunKind.initial_concept,
        idempotency_key="compact-events",
        payload={"capture": {"rawCapture": "Compact", "locale": "en"}},
    )
    assert repository.begin(run.id, "worker") is True
    repository.delta(run.id, "first")
    repository.delta(run.id, "second")
    repository.succeed(run.id, {"concept": {"id": "result"}})

    events = repository.events(run.id, "local-dev", 0)
    assert [event.type for event in events] == ["checkpoint", "started", "completed"]


def test_checkpointed_initial_run_restarts_without_provider_or_duplicate_domain_writes(
    tmp_path,
) -> None:
    sessions = _sessions(tmp_path)
    model = CountingModelService()
    service = ConceptService(
        store=PersistentConceptStore(sessions),
        model_service=model,
    )
    repository = ModelRunRepository(sessions)
    request = CreateConceptRequest(rawCapture="Restart-safe capture", locale="en")
    run, _ = repository.create(
        owner_id=service.owner_id,
        kind=ModelRunKind.initial_concept,
        idempotency_key="restart-capture",
        payload={"capture": request.model_dump(mode="json", by_alias=True)},
    )

    async def checkpoint_then_restart() -> None:
        concept = None
        async for event in service.prepare_initial_concept_stream(request):
            if not isinstance(event, ConceptTurnStreamDelta):
                concept = event
        assert concept is not None
        repository.checkpoint(
            run.id,
            "modelCompleted",
            {"concept": concept.model_dump(mode="json", by_alias=True)},
        )
        # Simulate a crash after the domain commit but before the run terminal write.
        service.commit_prepared_initial_concept(request, concept, run.idempotency_key)
        with sessions() as session:
            crashed = session.get(ModelRunRecord, str(run.id))
            assert crashed is not None
            crashed.status = "running"
            crashed.lease_owner = "crashed-worker"
            crashed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.commit()
        coordinator = ModelRunCoordinator(repository, service, managed=False)
        coordinator.start()
        try:
            for _ in range(100):
                if repository.get(run.id, service.owner_id).status.value == "succeeded":
                    return
                await asyncio.sleep(0.01)
            raise AssertionError("restarted run did not finish")
        finally:
            await coordinator.stop()

    asyncio.run(checkpoint_then_restart())

    assert model.initial_stream_calls == 1
    with sessions() as session:
        assert session.query(ModelRunRecord).count() == 1
        assert session.query(TurnRecord).count() == 2
        assert session.query(TurnRecord.operation_key).distinct().count() == 1


def test_checkpointed_follow_up_restarts_without_provider_or_duplicate_turns(tmp_path) -> None:
    sessions = _sessions(tmp_path)
    model = CountingModelService()
    service = ConceptService(
        store=PersistentConceptStore(sessions),
        model_service=model,
    )
    concept = service.create_concept(CreateConceptRequest(rawCapture="Follow-up restart"))
    repository = ModelRunRepository(sessions)
    request = {"question": "Keep this exactly once"}
    run, _ = repository.create(
        owner_id=service.owner_id,
        kind=ModelRunKind.follow_up,
        idempotency_key="restart-follow-up",
        payload={"turn": request},
        concept_id=concept.id,
    )

    async def checkpoint_then_restart() -> None:
        prepared = None
        turn_request = ConceptTurnRequest.model_validate(request)
        async for event in service.prepare_turn_stream(concept.id, turn_request):
            if not isinstance(event, ConceptTurnStreamDelta):
                prepared = event
        assert prepared is not None and prepared.turn_result is not None
        repository.checkpoint(
            run.id,
            "modelCompleted",
            {
                "mode": "turn",
                "baseNoteRevision": prepared.base_note_revision,
                "result": prepared.turn_result.model_dump(mode="json", by_alias=True),
            },
        )
        service.commit_prepared_turn(
            concept.id,
            turn_request,
            prepared,
            run.idempotency_key,
        )
        coordinator = ModelRunCoordinator(repository, service, managed=False)
        coordinator.enqueue(repository.get(run.id, service.owner_id), service)
        for _ in range(100):
            if repository.get(run.id, service.owner_id).status.value == "succeeded":
                return
            await asyncio.sleep(0.01)
        raise AssertionError("restarted follow-up did not finish")

    asyncio.run(checkpoint_then_restart())

    assert model.turn_stream_calls == 1
    with sessions() as session:
        assert session.query(TurnRecord).filter_by(concept_id=str(concept.id)).count() == 4


def test_revision_restore_creates_new_revision_and_stales_proposals(tmp_path) -> None:
    sessions = _sessions(tmp_path)
    service = ConceptService(store=PersistentConceptStore(sessions))
    concept = service.create_concept(CreateConceptRequest(rawCapture="Original"))
    service.update_concept_summary(
        concept.id, UpdateConceptSummaryRequest(displayTitle="Edited", oneLineExplanation="new")
    )
    with sessions() as session:
        session.add(
            UpdateProposalRecord(
                id="00000000-0000-0000-0000-000000000123",
                concept_id=str(concept.id),
                base_note_revision=2,
                patch_operations_json="[]",
                rationale="test",
                confidence=1,
                status="proposed",
                origin="followUp",
            )
        )
        session.commit()

    restored = service.restore_revision(concept.id, 1)

    assert restored.note_revision == 3
    assert restored.display_title == "Original"
    with sessions() as session:
        proposal = session.get(UpdateProposalRecord, "00000000-0000-0000-0000-000000000123")
        assert proposal.status == "stale"
        event = (
            session.query(UpdateEventRecord)
            .filter_by(concept_id=str(concept.id), note_revision=3)
            .one()
        )
        assert event.event_type == "revisionRestore"


def test_fifth_follow_up_schedules_summary_then_periodic_review(tmp_path) -> None:
    client, sessions = _client(tmp_path)
    with client:
        concept = client.post(
            "/v1/concepts",
            json={"rawCapture": "Maintenance", "locale": "en"},
        ).json()
        final_run = None
        for index in range(5):
            created = client.post(
                f"/v1/concepts/{concept['id']}/turn-runs",
                headers={"Idempotency-Key": f"turn-{index}"},
                json={"turn": {"question": f"Question {index}"}},
            ).json()
            final_run = _terminal(client, created["id"])
            assert final_run["status"] == "succeeded"
        assert final_run is not None
        for _ in range(100):
            children = [
                client.get(f"/v1/model-runs/{run_id}").json()
                for run_id in client.get(f"/v1/model-runs/{final_run['id']}").json()["childRunIds"]
            ]
            if len(children) == 2 and all(child["status"] == "succeeded" for child in children):
                break
            time.sleep(0.01)
        assert {child["kind"] for child in children} == {
            "continuitySummary",
            "knowledgeReview",
        }
        assert {child["agentSpec"] for child in children} == {
            "sift.continuity-summary",
            "sift.knowledge-review",
        }
        assert all(child["terminationReason"] == "completed" for child in children)
        assert all(child["currentStep"] == "validate" for child in children)
    with sessions() as session:
        assert session.get(ConceptContinuitySummaryRecord, concept["id"]) is not None
        state = session.get(ConceptMaintenanceStateRecord, concept["id"])
        assert state is not None
        assert state.last_reviewed_turn_id is not None
        assert state.review_due is False


def test_continuity_summary_persists_structured_semantic_memory(tmp_path) -> None:
    client, sessions = _client(tmp_path, model_service=SemanticSummaryModelService())
    with client:
        concept = client.post(
            "/v1/concepts",
            json={"rawCapture": "Semantic continuity", "locale": "en"},
        ).json()
        for index in range(5):
            run = client.post(
                f"/v1/concepts/{concept['id']}/turn-runs",
                headers={"Idempotency-Key": f"semantic-{index}"},
                json={"turn": {"question": f"Question {index}"}},
            ).json()
            assert _terminal(client, run["id"])["status"] == "succeeded"
        for _ in range(200):
            if not client.get("/v1/model-runs?active=true").json():
                break
            time.sleep(0.01)

    with sessions() as session:
        record = session.get(ConceptContinuitySummaryRecord, concept["id"])
        assert record is not None
        summary = json.loads(record.summary_json)
        assert summary["priorAnswers"][0]["content"].startswith("Earlier answers")
        assert summary["userContext"][0]["content"] == "The user prefers concrete examples."
        assert summary["userContext"][0]["sourceTurnIds"]


def test_invalid_summary_source_fails_summary_but_review_does_not_stall(tmp_path) -> None:
    client, _ = _client(tmp_path, model_service=InvalidSummarySourceModelService())
    with client:
        concept = client.post(
            "/v1/concepts",
            json={"rawCapture": "Invalid summary source", "locale": "en"},
        ).json()
        last_run = None
        for index in range(5):
            run = client.post(
                f"/v1/concepts/{concept['id']}/turn-runs",
                headers={"Idempotency-Key": f"invalid-summary-{index}"},
                json={"turn": {"question": f"Question {index}"}},
            ).json()
            last_run = _terminal(client, run["id"])
        assert last_run is not None
        for _ in range(200):
            children = [
                client.get(f"/v1/model-runs/{child_id}").json()
                for child_id in client.get(
                    f"/v1/model-runs/{last_run['id']}"
                ).json()["childRunIds"]
            ]
            if len(children) == 2 and all(
                child["status"] in {"succeeded", "failed"} for child in children
            ):
                break
            time.sleep(0.01)
        assert {child["kind"]: child["status"] for child in children} == {
            "continuitySummary": "failed",
            "knowledgeReview": "succeeded",
        }
        assert client.get("/v1/model-runs?active=true").json() == []


def test_twenty_follow_ups_preserve_early_context_and_write_each_turn_once(tmp_path) -> None:
    client, sessions = _client(tmp_path)
    with client:
        concept = client.post(
            "/v1/concepts",
            json={"rawCapture": "Continuity FIRST-MARKER", "locale": "en"},
        ).json()
        for index in range(20):
            key = f"long-turn-{index}"
            body = {"turn": {"question": f"Question {index}"}}
            created = client.post(
                f"/v1/concepts/{concept['id']}/turn-runs",
                headers={"Idempotency-Key": key},
                json=body,
            ).json()
            duplicate = client.post(
                f"/v1/concepts/{concept['id']}/turn-runs",
                headers={"Idempotency-Key": key},
                json=body,
            ).json()
            assert duplicate["id"] == created["id"]
            assert _terminal(client, created["id"])["status"] == "succeeded"

        for _ in range(200):
            active = client.get("/v1/model-runs?active=true").json()
            if not active:
                break
            time.sleep(0.01)
        else:
            raise AssertionError("maintenance runs did not settle")

    with sessions() as session:
        turns = session.query(TurnRecord).filter_by(concept_id=concept["id"]).all()
        assert len(turns) == 42
        assert len({(row.operation_key, row.role) for row in turns}) == 42
        summary = session.get(ConceptContinuitySummaryRecord, concept["id"])
        assert summary is not None
        assert "FIRST-MARKER" in summary.summary_json
        maintenance_counts = dict(
            session.query(ModelRunRecord.kind, func.count(ModelRunRecord.id))
            .filter(
                ModelRunRecord.concept_id == concept["id"],
                ModelRunRecord.kind.in_(["continuitySummary", "knowledgeReview"]),
            )
            .group_by(ModelRunRecord.kind)
            .all()
        )
        assert maintenance_counts == {"continuitySummary": 6, "knowledgeReview": 4}


def test_periodic_review_is_rejectable_then_merge_can_be_restored(tmp_path) -> None:
    client, _ = _client(tmp_path, model_service=ReviewProposalModelService())

    def submit_batch(concept_id: str, start: int) -> None:
        for index in range(start, start + 5):
            run = client.post(
                f"/v1/concepts/{concept_id}/turn-runs",
                headers={"Idempotency-Key": f"review-turn-{index}"},
                json={"turn": {"question": f"Review question {index}"}},
            ).json()
            assert _terminal(client, run["id"])["status"] == "succeeded"
        for _ in range(200):
            if not client.get("/v1/model-runs?active=true").json():
                return
            time.sleep(0.01)
        raise AssertionError("review run did not settle")

    with client:
        concept = client.post(
            "/v1/concepts",
            json={"rawCapture": "Review lifecycle", "locale": "en"},
        ).json()
        original_content = concept["blocks"][0]["content"]
        initial_revisions = client.get(
            f"/v1/concepts/{concept['id']}/revisions"
        ).json()
        assert len(initial_revisions) == 1
        assert initial_revisions[0]["source"] == "initialGeneration"
        assert initial_revisions[0]["createdAt"].endswith("Z")
        initial_revision = client.get(
            f"/v1/concepts/{concept['id']}/revisions/1"
        ).json()
        assert initial_revision["createdAt"].endswith("Z")

        submit_batch(concept["id"], 0)
        proposals = client.get(
            f"/v1/concepts/{concept['id']}/proposals?status=proposed"
        ).json()
        assert len(proposals) == 1
        assert proposals[0]["origin"] == "periodicReview"
        assert client.post(f"/v1/update-proposals/{proposals[0]['id']}/dismiss").status_code == 204
        assert client.get(
            f"/v1/concepts/{concept['id']}/proposals?status=proposed"
        ).json() == []

        submit_batch(concept["id"], 5)
        proposal = client.get(
            f"/v1/concepts/{concept['id']}/proposals?status=proposed"
        ).json()[0]
        merged = client.post(f"/v1/update-proposals/{proposal['id']}/merge").json()
        assert "Periodic durable insight" in merged["blocks"][0]["content"]

        restored = client.post(
            f"/v1/concepts/{concept['id']}/revisions/1/restore"
        ).json()
        assert restored["noteRevision"] == merged["noteRevision"] + 1
        assert restored["blocks"][0]["content"] == original_content
