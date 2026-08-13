from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

from sift_worker.d1 import D1WorkerStore


class SQLiteD1Statement:
    def __init__(self, database: SQLiteD1, sql: str) -> None:
        self.database = database
        self.sql = sql
        self.bindings: tuple[Any, ...] = ()

    def bind(self, *bindings: Any) -> SQLiteD1Statement:
        self.bindings = bindings
        return self

    async def run(self) -> dict[str, Any]:
        cursor = self.database.connection.execute(self.sql, self.bindings)
        return {
            "results": [dict(row) for row in cursor.fetchall()],
            "meta": {"changes": max(cursor.rowcount, 0)},
        }

    async def first(self) -> dict[str, Any] | None:
        row = self.database.connection.execute(self.sql, self.bindings).fetchone()
        return dict(row) if row is not None else None


class SQLiteD1:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        migrations = Path(__file__).parents[1] / "migrations"
        for migration in sorted(migrations.glob("*.sql")):
            self.connection.executescript(migration.read_text(encoding="utf-8"))

    def prepare(self, sql: str) -> SQLiteD1Statement:
        return SQLiteD1Statement(self, sql)

    async def batch(
        self,
        statements: list[SQLiteD1Statement],
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        with self.connection:
            for statement in statements:
                results.append(await statement.run())
        return results


def insert_running_run(
    database: SQLiteD1,
    run_id: str,
    kind: str,
    *,
    concept_id: str | None = None,
    worker_id: str = "worker-1",
) -> None:
    database.connection.execute(
        """
        INSERT INTO model_runs (
            id, owner_id, kind, status, concept_id, idempotency_key, payload_hash,
            payload_json, provider_snapshot_json, agent_spec,
            agent_spec_version, prompt_version, budget_json,
            created_at, updated_at, lease_owner, lease_expires_at
        ) VALUES (?, 'owner-1', ?, 'running', ?, ?, 'hash', '{}', '{}',
                  'agent', '1.0', 'prompt-v1', '{}',
                  '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z', ?,
                  '2026-08-01T00:01:00Z')
        """,
        (run_id, kind, concept_id, f"operation-{run_id}", worker_id),
    )
    database.connection.execute(
        """
        INSERT INTO model_run_events (
            run_id, sequence, event_type, data_json, created_at
        ) VALUES (?, 1, 'started', '{}', '2026-08-01T00:00:00Z')
        """,
        (run_id,),
    )


def test_create_initial_run_atomically_persists_pending_concept_and_input_turn() -> None:
    async def scenario() -> None:
        database = SQLiteD1()
        store = D1WorkerStore(database)
        run = {
            "id": "run-pending",
            "owner_id": "owner-1",
            "kind": "initialConcept",
            "status": "queued",
            "concept_id": "run-pending",
            "client_draft_id": "draft-1",
            "idempotency_key": "operation-pending",
            "payload_hash": "hash",
            "payload_json": "{}",
            "provider_snapshot_json": "{}",
            "agent_spec": "sift.initial-concept",
            "agent_spec_version": "1.0",
            "prompt_version": "initial-concept-v1",
            "budget_json": "{}",
            "tool_contract_hash": "",
            "current_step": None,
            "model_call_count": 0,
            "tool_call_count": 0,
            "termination_reason": None,
            "dependency_run_id": None,
            "checkpoint": None,
            "checkpoint_json": None,
            "result_json": None,
            "result_ref": None,
            "error_code": None,
            "error_message": None,
            "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-01T00:00:00Z",
        }
        event = {
            "run_id": "run-pending",
            "sequence": 1,
            "event_type": "checkpoint",
            "data_json": '{"status":"queued"}',
            "created_at": "2026-08-01T00:00:00Z",
        }
        pending_concept = {
            "id": "run-pending",
            "canonical_title": "Original input",
            "display_title": "Original input",
            "one_line_explanation": "",
            "initial_answer": None,
            "maturity": "initial",
            "capture_status": "pendingGeneration",
            "note_revision": 0,
            "answer_source_json": None,
            "document_json": '{"id":"run-pending","captureStatus":"pendingGeneration"}',
            "created_at": "2026-08-01T00:00:00Z",
            "updated_at": "2026-08-01T00:00:00Z",
        }
        input_turn = {
            "id": "turn-pending-user",
            "concept_id": "run-pending",
            "operation_key": "operation-pending",
            "role": "user",
            "content": "Original input",
            "answer_source_json": None,
            "created_at": "2026-08-01T00:00:00Z",
        }

        stored, created = await store.create_model_run(
            run=run,
            event=event,
            pending_concept=pending_concept,
            input_turn=input_turn,
        )
        assert created is True
        assert stored["concept_id"] == "run-pending"
        assert database.connection.execute(
            "SELECT capture_status FROM concepts WHERE id = 'run-pending'"
        ).fetchone()[0] == "pendingGeneration"
        assert database.connection.execute(
            "SELECT content FROM concept_turns WHERE concept_id = 'run-pending'"
        ).fetchone()[0] == "Original input"

        duplicate = {**run, "id": "run-losing-race", "concept_id": "run-losing-race"}
        duplicate_event = {**event, "run_id": "run-losing-race"}
        existing, duplicate_created = await store.create_model_run(
            run=duplicate,
            event=duplicate_event,
            pending_concept={**pending_concept, "id": "run-losing-race"},
            input_turn={
                **input_turn,
                "id": "turn-losing-race",
                "concept_id": "run-losing-race",
            },
        )
        assert duplicate_created is False
        assert existing["id"] == "run-pending"
        assert database.connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 1
        assert database.connection.execute("SELECT COUNT(*) FROM concept_turns").fetchone()[0] == 1

        claimed, did_claim = await store.claim_model_run(
            "run-pending",
            "owner-1",
            now="2026-08-01T00:00:01Z",
            worker_id="worker-1",
            lease_expires_at="2026-08-01T00:01:01Z",
        )
        assert claimed is not None and did_claim is True
        failed = await store.fail_model_run(
            "run-pending",
            "owner-1",
            worker_id="worker-1",
            code="provider_unreachable",
            message="Provider failed.",
            now="2026-08-01T00:00:02Z",
        )
        assert failed is not None and failed["status"] == "failed"
        assert database.connection.execute(
            "SELECT capture_status FROM concepts WHERE id = 'run-pending'"
        ).fetchone()[0] == "generationFailed"

    asyncio.run(scenario())


def test_initial_commit_is_atomically_guarded_by_execution_lease() -> None:
    async def scenario() -> None:
        database = SQLiteD1()
        database.connection.execute(
            """
            INSERT INTO model_runs (
                id, owner_id, kind, status, idempotency_key, payload_hash,
                payload_json, provider_snapshot_json, agent_spec,
                agent_spec_version, prompt_version, budget_json,
                created_at, updated_at, lease_owner, lease_expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "run-1",
                "owner-1",
                "initialConcept",
                "running",
                "operation-1",
                "hash",
                "{}",
                "{}",
                "sift.initial-concept",
                "1.0",
                "initial-concept-v1",
                "{}",
                "2026-08-01T00:00:00Z",
                "2026-08-01T00:00:00Z",
                "worker-new",
                "2026-08-01T00:01:00Z",
            ),
        )
        database.connection.execute(
            """
            INSERT INTO model_run_events (
                run_id, sequence, event_type, data_json, created_at
            ) VALUES ('run-1', 1, 'started', '{}', '2026-08-01T00:00:00Z')
            """
        )
        store = D1WorkerStore(database)
        concept = {
            "id": "concept-1",
            "canonical_title": "Lease safety",
            "display_title": "Lease safety",
            "one_line_explanation": "Only the lease owner may commit.",
            "initial_answer": "A complete answer.",
            "maturity": "captured",
            "capture_status": "completed",
            "note_revision": 1,
            "answer_source_json": "{}",
            "document_json": "{}",
            "created_at": "2026-08-01T00:00:01Z",
            "updated_at": "2026-08-01T00:00:01Z",
        }
        revision = {
            "revision": 1,
            "snapshot_json": "{}",
            "actor": "model",
            "event_type": "initialGeneration",
            "created_at": "2026-08-01T00:00:01Z",
        }
        common = {
            "run_id": "run-1",
            "owner_id": "owner-1",
            "concept": concept,
            "blocks": [],
            "tags": [],
            "topics": [],
            "revision": revision,
            "turns": [],
            "sources": [],
            "provider_snapshot_json": "{}",
            "result_json": '{"concept":{}}',
            "now": "2026-08-01T00:00:02Z",
        }

        stale = await store.complete_initial_run(worker_id="worker-old", **common)
        assert stale is not None and stale["status"] == "running"
        assert database.connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 0
        assert await store.append_model_run_event(
            "run-1",
            "owner-1",
            event_type="delta",
            data_json='{"content":"stale"}',
            now="2026-08-01T00:00:02Z",
            worker_id="worker-old",
        ) is None
        assert await store.append_model_run_event(
            "run-1",
            "owner-1",
            event_type="delta",
            data_json='{"content":"current"}',
            now="2026-08-01T00:00:02Z",
            worker_id="worker-new",
        ) == 2

        completed = await store.complete_initial_run(worker_id="worker-new", **common)
        assert completed is not None and completed["status"] == "succeeded"
        assert completed["lease_owner"] is None
        assert database.connection.execute("SELECT COUNT(*) FROM concepts").fetchone()[0] == 1
        assert database.connection.execute(
            "SELECT COUNT(*) FROM model_run_events WHERE event_type = 'completed'"
        ).fetchone()[0] == 1

    asyncio.run(scenario())


def test_provider_snapshot_is_written_once_by_the_active_lease_owner() -> None:
    async def scenario() -> None:
        database = SQLiteD1()
        store = D1WorkerStore(database)
        insert_running_run(database, "run-provider-snapshot", "initialConcept")
        snapshot = (
            '{"provider":"deepseek","model":"deepseek-chat",'
            '"baseURL":"https://api.deepseek.com/v1"}'
        )

        assert await store.snapshot_model_run_provider(
            "run-provider-snapshot",
            "owner-1",
            worker_id="worker-1",
            provider_snapshot_json=snapshot,
            now="2026-08-01T00:00:01Z",
        ) is True
        assert await store.snapshot_model_run_provider(
            "run-provider-snapshot",
            "owner-1",
            worker_id="worker-1",
            provider_snapshot_json='{"provider":"openai"}',
            now="2026-08-01T00:00:02Z",
        ) is False
        assert database.connection.execute(
            "SELECT provider_snapshot_json FROM model_runs WHERE id = ?",
            ("run-provider-snapshot",),
        ).fetchone()[0] == snapshot

    asyncio.run(scenario())


def test_agent_model_call_metrics_are_atomically_aggregated_with_event() -> None:
    async def scenario() -> None:
        database = SQLiteD1()
        store = D1WorkerStore(database)
        insert_running_run(database, "run-metrics", "initialConcept")

        sequence = await store.record_agent_event(
            "run-metrics",
            "owner-1",
            worker_id="worker-1",
            event_type="modelCallCompleted",
            data_json='{"callIndex":1,"latencyMs":120}',
            now="2026-08-01T00:00:01Z",
            model_latency_ms=120,
            input_token_count=30,
            output_token_count=12,
        )

        assert sequence is not None
        row = database.connection.execute(
            """
            SELECT model_latency_ms, input_token_count, output_token_count
            FROM model_runs WHERE id = 'run-metrics'
            """
        ).fetchone()
        assert tuple(row) == (120, 30, 12)
        assert database.connection.execute(
            """
            SELECT COUNT(*) FROM model_run_events
            WHERE run_id = 'run-metrics' AND event_type = 'modelCallCompleted'
            """
        ).fetchone()[0] == 1

    asyncio.run(scenario())


def test_all_d1_agent_commits_execute_with_lease_guarded_sql() -> None:
    async def scenario() -> None:
        database = SQLiteD1()
        database.connection.execute(
            """
            INSERT INTO concepts (
                id, owner_id, canonical_title, display_title,
                one_line_explanation, initial_answer, maturity, capture_status,
                note_revision, answer_source_json, document_json, created_at, updated_at
            ) VALUES (
                'concept-1', 'owner-1', 'Runtime', 'Runtime', 'A runtime.', 'Answer',
                'captured', 'completed', 1, '{}', '{}',
                '2026-08-01T00:00:00Z', '2026-08-01T00:00:00Z'
            )
            """
        )
        store = D1WorkerStore(database)

        insert_running_run(
            database, "run-follow", "followUp", concept_id="concept-1"
        )
        follow_up = await store.complete_follow_up_run(
            run_id="run-follow",
            owner_id="owner-1",
            worker_id="worker-1",
            concept_id="concept-1",
            replacing_turn_index=None,
            turns=[
                {
                    "id": "turn-user",
                    "operation_key": "operation-run-follow",
                    "role": "user",
                    "content": "Question",
                    "answer_source_json": None,
                    "created_at": "2026-08-01T00:00:01Z",
                },
                {
                    "id": "turn-assistant",
                    "operation_key": "operation-run-follow",
                    "role": "assistant",
                    "content": "Answer",
                    "answer_source_json": "{}",
                    "created_at": "2026-08-01T00:00:02Z",
                },
            ],
            proposal=None,
            sources=[],
            provider_snapshot_json="{}",
            result_json='{"response":{}}',
            now="2026-08-01T00:00:02Z",
        )
        assert follow_up is not None and follow_up["status"] == "succeeded"

        insert_running_run(
            database,
            "run-regenerate",
            "followUp",
            concept_id="concept-1",
        )
        regenerated = await store.complete_regenerated_follow_up_run(
            run_id="run-regenerate",
            owner_id="owner-1",
            worker_id="worker-1",
            expected_revision=1,
            concept={
                "id": "concept-1",
                "canonical_title": "Runtime v2",
                "display_title": "Runtime v2",
                "one_line_explanation": "A safer runtime.",
                "initial_answer": "New answer",
                "maturity": "captured",
                "capture_status": "completed",
                "note_revision": 2,
                "answer_source_json": "{}",
                "document_json": "{}",
                "updated_at": "2026-08-01T00:00:03Z",
            },
            blocks=[],
            tags=[],
            topics=[],
            revision={
                "revision": 2,
                "snapshot_json": "{}",
                "actor": "model",
                "event_type": "retryGeneration",
                "created_at": "2026-08-01T00:00:03Z",
                "snapshot_schema_version": 1,
            },
            turns=[],
            provider_snapshot_json="{}",
            result_json='{"response":{}}',
            now="2026-08-01T00:00:03Z",
        )
        assert regenerated is not None and regenerated["status"] == "succeeded"
        assert database.connection.execute(
            "SELECT note_revision FROM concepts WHERE id = 'concept-1'"
        ).fetchone()[0] == 2

        insert_running_run(
            database,
            "run-continuity",
            "continuitySummary",
            concept_id="concept-1",
        )
        continuity = await store.complete_continuity_summary_run(
            run_id="run-continuity",
            owner_id="owner-1",
            worker_id="worker-1",
            concept_id="concept-1",
            summary="Durable summary",
            through_turn_count=2,
            source_turns_hash="sha256",
            provider_snapshot_json="{}",
            result_json='{"summary":"Durable summary"}',
            now="2026-08-01T00:00:04Z",
        )
        assert continuity is not None and continuity["status"] == "succeeded"

        insert_running_run(
            database,
            "run-review",
            "knowledgeReview",
            concept_id="concept-1",
        )
        review = await store.complete_knowledge_review_run(
            run_id="run-review",
            owner_id="owner-1",
            worker_id="worker-1",
            concept_id="concept-1",
            reviewed_user_turn_count=2,
            proposal={
                "id": "proposal-1",
                "base_note_revision": 2,
                "patch_operations_json": "[]",
                "rationale": "New learning",
                "confidence": 0.8,
            },
            claims=[
                {
                    "id": "claim-1",
                    "statement": "The runtime is bounded.",
                    "claim_type": "fact",
                    "evidence_status": "modelExplanation",
                    "time_sensitivity": "stable",
                    "source_ids_json": "[]",
                    "verified_at": None,
                    "created_at": "2026-08-01T00:00:05Z",
                }
            ],
            learning_state_updates=[
                {
                    "id": "learning-1",
                    "field": "takeaway",
                    "content": "Bound execution.",
                    "origin": "conversation",
                    "created_at": "2026-08-01T00:00:05Z",
                }
            ],
            provider_snapshot_json="{}",
            result_json='{"claims":[]}',
            now="2026-08-01T00:00:05Z",
        )
        assert review is not None and review["status"] == "succeeded"
        assert database.connection.execute(
            "SELECT COUNT(*) FROM concept_claims"
        ).fetchone()[0] == 1
        assert database.connection.execute(
            "SELECT COUNT(*) FROM learning_state_entries"
        ).fetchone()[0] == 1

    asyncio.run(scenario())


def test_d1_cancel_is_terminal_and_emits_one_event() -> None:
    async def scenario() -> None:
        database = SQLiteD1()
        insert_running_run(database, "run-cancel", "initialConcept")
        store = D1WorkerStore(database)

        first = await store.cancel_model_run(
            "run-cancel", "owner-1", now="2026-08-01T00:00:01Z"
        )
        second = await store.cancel_model_run(
            "run-cancel", "owner-1", now="2026-08-01T00:00:02Z"
        )

        assert first is not None and first["status"] == "cancelled"
        assert second is not None and second["status"] == "cancelled"
        assert second["lease_owner"] is None
        assert database.connection.execute(
            "SELECT COUNT(*) FROM model_run_events WHERE event_type = 'cancelled'"
        ).fetchone()[0] == 1

    asyncio.run(scenario())
