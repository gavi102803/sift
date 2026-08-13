from __future__ import annotations

import asyncio
import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from sift_worker.agent_core import INITIAL_AGENT_SPEC, AgentControlError
from sift_worker.app import create_app
from sift_worker.errors import PublicError
from sift_worker.models import (
    ContinuitySummaryResult,
    CreateConceptRunRequest,
    CreateTurnRunRequest,
    CurrentPrincipal,
    FollowUpResult,
    InitialConceptResult,
    KnowledgeReviewResult,
)
from sift_worker.runtime import RuntimeToolCall, validate_provider_connection
from sift_worker.services import ModelRunService, _tool_evidence


def test_tool_evidence_is_allowlisted_and_bounded_before_checkpointing() -> None:
    evidence = _tool_evidence(
        {
            "id": "source-1",
            "title": "T" * 600,
            "url": "https://example.com/source",
            "snippet": "S" * 5_000,
            "publishedAt": "2026-08-11",
            "provenance": "search",
            "providerDebugPayload": "must-not-persist",
        }
    )

    assert len(evidence[0]["title"]) == 500
    assert len(evidence[0]["snippet"]) == 4_000
    assert "providerDebugPayload" not in evidence[0]

    with pytest.raises(AgentControlError) as unsafe_url:
        _tool_evidence(
            {
                "id": "source-2",
                "title": "Unsafe",
                "url": "http://127.0.0.1/private",
            }
        )
    assert unsafe_url.value.code == "tool_invalid_result"

    with pytest.raises(AgentControlError) as too_many:
        _tool_evidence(
            [
                {"id": str(index), "title": "Title", "url": f"https://example.com/{index}"}
                for index in range(6)
            ]
        )
    assert too_many.value.code == "tool_invalid_result"


def test_agent_user_inputs_are_bounded_before_persistence_or_model_calls() -> None:
    oversized = "x" * 20_001

    with pytest.raises(ValidationError):
        CreateConceptRunRequest.model_validate(
            {"capture": {"rawCapture": oversized, "locale": "en"}}
        )
    with pytest.raises(ValidationError):
        CreateTurnRunRequest.model_validate({"turn": {"question": oversized}})


def test_managed_initial_run_resumes_with_ephemeral_key_and_is_idempotent() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("stream-invite")
    client = TestClient(
        create_app(
            lambda _request: store,
            provider_client_factory=FakeProviderClient,
        )
    )
    session = activate(client, "stream-invite", "installation-a")
    headers = auth_headers(session, "installation-a")
    assert client.put(
        "/v1/provider-connection",
        headers={**headers, "X-Sift-Provider-Key": "request-only-key"},
        json={
            "providerId": "custom",
            "baseURL": "https://provider.example/v1",
            "model": "test-model",
        },
    ).status_code == 200
    submit_headers = {
        **headers,
        "Idempotency-Key": "stream-capture-operation",
    }
    payload = {
        "capture": {"rawCapture": "Cloudflare Workers", "locale": "en"},
        "clientDraftId": "2ba815bb-f936-4758-969c-293c9aab7241",
    }

    response = client.post(
        "/v1/concept-runs",
        headers=submit_headers,
        json=payload,
    )
    assert response.status_code == 202
    submitted = response.json()
    assert submitted["status"] == "waitingForCredential"
    assert submitted["conceptId"] == submitted["id"]
    pending = client.get(
        f"/v1/concepts/{submitted['conceptId']}",
        headers=headers,
    ).json()
    assert pending["captureStatus"] == "pendingGeneration"
    assert pending["initialAnswer"] is None
    assert [(turn["role"], turn["content"]) for turn in store.turns[pending["id"]]] == [
        ("user", "Cloudflare Workers")
    ]

    resumed = client.post(
        f"/v1/model-runs/{submitted['id'].upper()}/resume",
        headers={
            **headers,
            "X-Sift-Provider-Key": "request-only-key",
        },
        json={},
    )
    assert resumed.status_code == 200
    completed = resumed.json()
    assert completed["status"] == "succeeded"
    events = client.get(
        f"/v1/model-runs/{submitted['id'].upper()}/events",
        headers=headers,
    ).json()
    deltas = [
        event["data"]["content"]
        for event in events
        if event["type"] == "delta"
    ]
    assert len(deltas) == 1
    assert "**What it is**" in "".join(deltas)
    concept = completed["result"]["concept"]
    assert client.get(
        f"/v1/concepts/{concept['id'].upper()}",
        headers=headers,
    ).json()["id"] == concept["id"]
    assert "".join(deltas) == concept["initialAnswer"]
    assert [(turn["role"], turn["content"]) for turn in store.turns[concept["id"]]][0] == (
        "user",
        "Cloudflare Workers",
    )

    retry = client.post(
        "/v1/concept-runs",
        headers=submit_headers,
        json=payload,
    )
    assert retry.json()["id"] == submitted["id"]
    assert retry.json()["status"] == "succeeded"
    assert len(store.turns[concept["id"]]) == 2


def test_failed_initial_run_keeps_one_pending_card_and_reuses_it_on_retry() -> None:
    resumed_models: list[str] = []

    class TransientFailureProvider(FakeProviderClient):
        async def request_initial_tool_calls(
            self,
            raw_capture: str,
            locale: str,
            tool_observations: list[dict[str, Any]] | None = None,
        ) -> tuple[RuntimeToolCall, ...]:
            del raw_capture, locale, tool_observations
            await self._record_model_call()
            raise RuntimeError("transient provider failure")

    class SnapshotCheckingProvider(FakeProviderClient):
        def __init__(self, connection, api_key: str) -> None:
            super().__init__(connection, api_key)
            resumed_models.append(connection.model)

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        payload = CreateConceptRunRequest.model_validate(
            {"capture": {"rawCapture": "Recoverable input", "locale": "en"}}
        )
        submitted, _ = await service.submit_initial(
            principal,
            payload,
            idempotency_key="recoverable-input",
            has_provider_credential=True,
        )

        with pytest.raises(PublicError) as failed:
            await service.execute_initial(
                submitted.id,
                principal,
                "request-only-key",
                client_factory=TransientFailureProvider,
            )
        assert failed.value.code == "backend_unavailable"
        assert store.concepts[submitted.id]["captureStatus"] == "generationFailed"
        assert len(store.turns[submitted.id]) == 1
        assert '"model":"test-model"' in store.runs[submitted.id][
            "provider_snapshot_json"
        ]

        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "changed-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:01:00Z",
            }
        )

        retried, created = await service.submit_initial(
            principal,
            payload,
            idempotency_key="recoverable-input",
            has_provider_credential=True,
        )
        assert created is False
        assert retried.id == submitted.id
        assert len(store.turns[submitted.id]) == 1

        completed = await service.execute_initial(
            retried.id,
            principal,
            "request-only-key",
            client_factory=SnapshotCheckingProvider,
        )
        assert completed.status == "succeeded"
        assert resumed_models == ["test-model"]
        assert store.concepts[submitted.id]["captureStatus"] == "ready"
        assert [turn["role"] for turn in store.turns[submitted.id]] == [
            "user",
            "assistant",
        ]

    asyncio.run(scenario())


def test_initial_model_tool_call_dispatches_search_and_persists_cited_source() -> None:
    continued_contexts: list[dict[str, Any]] = []

    class ToolCallingProvider(FakeProviderClient):
        async def request_initial_tool_calls(
            self,
            raw_capture: str,
            locale: str,
            tool_observations: list[dict[str, Any]] | None = None,
        ) -> tuple[RuntimeToolCall, ...]:
            del raw_capture, locale
            await self._record_model_call()
            if tool_observations:
                continued_contexts.extend(tool_observations)
                return ()
            return (
                RuntimeToolCall(
                    id="call-search",
                    name="web_search",
                    arguments={"query": "Cloudflare Workers release notes"},
                    provider_context={
                        "assistantMessage": {
                            "role": "assistant",
                            "content": "I will search.",
                            "reasoning_content": "The request needs current facts.",
                            "tool_calls": [],
                        }
                    },
                ),
            )

    class FakeWebSearch:
        def __init__(self) -> None:
            self.queries: list[str] = []

        async def search(self, query: str) -> list[dict[str, str]]:
            self.queries.append(query)
            return [
                {
                    "id": "source-1",
                    "title": "Current release notes",
                    "url": "https://example.com/releases",
                    "snippet": "The latest release is documented here.",
                }
            ]

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        search = FakeWebSearch()
        service = ModelRunService(store, web_search_client=search)
        live_deltas: list[str] = []

        async def capture_delta(delta: str) -> None:
            live_deltas.append(delta)

        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {
                    "capture": {
                        "rawCapture": "Explain Cloudflare Workers changes.",
                        "locale": "en",
                    }
                }
            ),
            idempotency_key="current-query",
            has_provider_credential=True,
        )
        assert run.agent_spec_version == "1.4"
        assert run.tool_contract_hash == INITIAL_AGENT_SPEC.tool_contract_hash
        assert store.runs[run.id]["tool_contract_hash"] == run.tool_contract_hash
        completed = await service.execute_initial(
            run.id,
            principal,
            "request-only-key",
            client_factory=ToolCallingProvider,
            live_delta_sink=capture_delta,
        )

        concept = completed.result["concept"]
        assert completed.tool_call_count == 1
        assert continued_contexts[0]["providerContext"]["assistantMessage"][
            "reasoning_content"
        ] == "The request needs current facts."
        assert live_deltas == [
            "**What it is**\n\n",
            "An answer about Explain Cloudflare Workers changes.",
            ".\n\n**Why it matters**\n\nIt is useful enough to become a durable card.",
        ]
        assert search.queries == ["Cloudflare Workers release notes"]
        assert concept["answerSource"]["retrievalUsed"] is True
        assert concept["answerSource"]["citations"][0]["sourceId"] == "source-1"
        assert concept["sources"][0]["url"] == "https://example.com/releases"
        event_types = [event["event_type"] for event in store.events[run.id]]
        assert event_types.index("sourcesReady") < event_types.index("delta")
        source_event = next(
            event for event in store.events[run.id]
            if event["event_type"] == "sourcesReady"
        )
        assert json.loads(source_event["data_json"])["citations"] == [
            {
                "sourceId": "source-1",
                "title": "Current release notes",
                "url": "https://example.com/releases",
            }
        ]
        assert any(
            event["event_type"] == "toolStarted"
            and "web.search" in event["data_json"]
            for event in store.events[run.id]
        )

    asyncio.run(scenario())


def test_service_binds_model_lifecycle_and_returns_aggregated_metrics() -> None:
    class ObservableProvider(FakeProviderClient):
        def __init__(self, connection, api_key: str) -> None:
            super().__init__(connection, api_key)
            self.model_call_completion_observer = None

        def bind_model_call_completion_observer(self, observer) -> None:
            self.model_call_completion_observer = observer

        async def _record_model_call(self) -> None:
            call_index = None
            if self.model_call_observer is not None:
                call_index = await self.model_call_observer()
            self.model_call_count += 1
            if self.model_call_completion_observer is not None:
                await self.model_call_completion_observer(
                    call_index or self.model_call_count,
                    7,
                    3,
                    2,
                    True,
                )

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(
            owner_id="owner-a",
            installation_id="installation-a",
        )
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Durable execution", "locale": "en"}}
            ),
            idempotency_key="observable-runtime",
            has_provider_credential=True,
        )

        completed = await service.execute_initial(
            run.id,
            principal,
            "request-only-key",
            client_factory=ObservableProvider,
        )

        assert completed.model_call_count == 3
        assert completed.model_latency_ms == 21
        assert completed.input_token_count == 9
        assert completed.output_token_count == 6
        lifecycle = [
            event["event_type"]
            for event in store.events[run.id]
            if event["event_type"] in {"modelCallStarted", "modelCallCompleted"}
        ]
        assert lifecycle == [
            "modelCallStarted",
            "modelCallCompleted",
            "modelCallStarted",
            "modelCallCompleted",
            "modelCallStarted",
            "modelCallCompleted",
        ]

    asyncio.run(scenario())


def test_agent_tool_loop_can_search_then_extract_a_selected_source() -> None:
    class SearchThenExtractProvider(FakeProviderClient):
        async def request_initial_tool_calls(
            self,
            raw_capture: str,
            locale: str,
            tool_observations: list[dict[str, Any]] | None = None,
        ) -> tuple[RuntimeToolCall, ...]:
            del raw_capture, locale
            await self._record_model_call()
            if not tool_observations:
                return (
                    RuntimeToolCall(
                        id="call-search",
                        name="web_search",
                        arguments={"query": "Sift agent runtime architecture"},
                    ),
                )
            selected_url = tool_observations[0]["result"][0]["url"]
            return (
                RuntimeToolCall(
                    id="call-extract",
                    name="web_extract",
                    arguments={"url": selected_url},
                ),
            )

        async def generate_initial_concept(self, *args, **kwargs) -> InitialConceptResult:
            result = await super().generate_initial_concept(*args, **kwargs)
            evidence = kwargs["retrieval_evidence"]
            payload = result.model_dump(mode="json", by_alias=True)
            payload["answerSource"]["citations"] = [
                {
                    "sourceId": evidence[-1]["id"],
                    "title": evidence[-1]["title"],
                    "url": evidence[-1]["url"],
                }
            ]
            return InitialConceptResult.model_validate(payload)

    class SearchAndExtract:
        async def search(self, query: str) -> list[dict[str, str]]:
            assert query == "Sift agent runtime architecture"
            return [
                {
                    "id": "source-search",
                    "title": "Runtime overview",
                    "url": "https://example.com/runtime",
                    "snippet": "Search summary.",
                    "provenance": "search",
                }
            ]

        async def extract(self, url: str) -> dict[str, str]:
            assert url == "https://example.com/runtime"
            return {
                "id": "source-read",
                "title": "Runtime overview",
                "url": url,
                "snippet": "Full source content.",
                "publishedAt": "",
                "provenance": "extracted",
            }

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store, web_search_client=SearchAndExtract())
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {
                    "capture": {
                        "rawCapture": "Search the web for Sift agent runtime architecture",
                        "locale": "en",
                    }
                }
            ),
            idempotency_key="search-then-extract",
            has_provider_credential=True,
        )

        completed = await service.execute_initial(
            run.id,
            principal,
            "request-only-key",
            client_factory=SearchThenExtractProvider,
        )

        assert completed.status == "succeeded"
        assert completed.tool_call_count == 2
        assert completed.model_call_count == 4
        assert list(store.sources.values())[0]["source_type"] == "sourceRead"
        assert [
            __import__("json").loads(event["data_json"])["tool"]
            for event in store.events[run.id]
            if event["event_type"] == "toolStarted"
        ] == ["web.search", "web.extract"]
        loop_event = next(
            event
            for event in store.events[run.id]
            if event["event_type"] == "toolLoopCompleted"
        )
        assert __import__("json").loads(loop_event["data_json"])["reason"] == (
            "roundBudgetExhausted"
        )

    asyncio.run(scenario())


def test_retrieval_failure_is_returned_to_planner_without_discarding_evidence() -> None:
    class SearchThenFailingExtractProvider(FakeProviderClient):
        async def request_initial_tool_calls(
            self,
            raw_capture: str,
            locale: str,
            tool_observations: list[dict[str, Any]] | None = None,
        ) -> tuple[RuntimeToolCall, ...]:
            del raw_capture, locale
            await self._record_model_call()
            observations = tool_observations or []
            if not observations:
                return (
                    RuntimeToolCall(
                        id="call-search",
                        name="web_search",
                        arguments={"query": "Cloudflare Workers platform positioning"},
                    ),
                )
            if len(observations) == 1:
                return (
                    RuntimeToolCall(
                        id="call-extract",
                        name="web_extract",
                        arguments={"url": observations[0]["result"][0]["url"]},
                    ),
                )
            return ()

        async def generate_initial_concept(self, *args, **kwargs) -> InitialConceptResult:
            result = await super().generate_initial_concept(*args, **kwargs)
            evidence = kwargs["retrieval_evidence"]
            payload = result.model_dump(mode="json", by_alias=True)
            payload["answerSource"]["citations"] = [
                {
                    "sourceId": evidence[0]["id"],
                    "title": evidence[0]["title"],
                    "url": evidence[0]["url"],
                }
            ]
            return InitialConceptResult.model_validate(payload)

    class SearchWithUnavailableExtract:
        async def search(self, query: str) -> list[dict[str, str]]:
            assert query == "Cloudflare Workers platform positioning"
            return [
                {
                    "id": "source-search",
                    "title": "Cloudflare Workers",
                    "url": "https://developers.cloudflare.com/workers/",
                    "snippet": "Workers is Cloudflare's serverless application platform.",
                    "provenance": "search",
                }
            ]

        async def extract(self, _url: str) -> dict[str, str]:
            raise PublicError(
                "retrieval_required",
                "The requested source could not be retrieved.",
                502,
            )

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store, web_search_client=SearchWithUnavailableExtract())
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {
                    "capture": {
                        "rawCapture": "Use web search to explain Cloudflare Workers.",
                        "locale": "en",
                    }
                }
            ),
            idempotency_key="recover-retrieval-failure",
            has_provider_credential=True,
        )

        completed = await service.execute_initial(
            run.id,
            principal,
            "request-only-key",
            client_factory=SearchThenFailingExtractProvider,
        )

        assert completed.status == "succeeded"
        assert completed.tool_call_count == 2
        assert any(
            event["event_type"] == "toolFailed"
            for event in store.events[run.id]
        )
        assert list(store.sources.values())[0]["url"] == (
            "https://developers.cloudflare.com/workers/"
        )

    asyncio.run(scenario())


def test_web_search_timeout_fails_run_instead_of_leaving_it_running(monkeypatch) -> None:
    class SlowWebSearch:
        async def search(self, _query: str) -> list[dict[str, str]]:
            await asyncio.sleep(1)
            return []

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store, web_search_client=SlowWebSearch())
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {
                    "capture": {
                        "rawCapture": "What is the latest Workers release today?",
                        "locale": "en",
                    }
                }
            ),
            idempotency_key="search-timeout",
            has_provider_credential=True,
        )

        with pytest.raises(PublicError, match="exceeded its execution timeout"):
            await service.execute_initial(
                run.id,
                principal,
                "request-only-key",
                client_factory=FakeProviderClient,
            )

        assert store.runs[run.id]["status"] == "failed"
        assert store.runs[run.id]["error_code"] == "tool_timeout"
        assert store.events[run.id][-2]["event_type"] == "toolFailed"
        assert "tool_timeout" in store.events[run.id][-2]["data_json"]
        assert store.events[run.id][-1]["event_type"] == "failed"

    monkeypatch.setattr("sift_worker.services.WEB_SEARCH_TIMEOUT_SECONDS", 0.01)
    asyncio.run(scenario())


def test_expired_lease_is_reclaimed_and_old_worker_cannot_commit() -> None:
    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        service = ModelRunService(store)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Lease safety", "locale": "en"}}
            ),
            idempotency_key="lease-safety",
            has_provider_credential=True,
        )
        claimed, did_claim = await store.claim_model_run(
            run.id,
            principal.owner_id,
            now="2026-08-01T00:00:00Z",
            worker_id="worker-old",
            lease_expires_at="2026-08-01T00:01:00Z",
        )
        assert claimed is not None and did_claim is True
        _, active_claim = await store.claim_model_run(
            run.id,
            principal.owner_id,
            now="2026-08-01T00:00:30Z",
            worker_id="worker-new",
            lease_expires_at="2026-08-01T00:01:30Z",
        )
        assert active_claim is False
        reclaimed, stale_claim = await store.claim_model_run(
            run.id,
            principal.owner_id,
            now="2026-08-01T00:01:01Z",
            worker_id="worker-new",
            lease_expires_at="2026-08-01T00:02:01Z",
        )
        assert reclaimed is not None and stale_claim is True
        assert reclaimed["lease_owner"] == "worker-new"

        stale_commit = await store.complete_initial_run(
            run_id=run.id,
            owner_id=principal.owner_id,
            worker_id="worker-old",
            concept={},
            blocks=[],
            tags=[],
            topics=[],
            revision={},
            turns=[],
            sources=[],
            provider_snapshot_json="{}",
            result_json="{}",
            now="2026-08-01T00:01:02Z",
        )
        assert stale_commit is not None and stale_commit["status"] == "running"
        assert store.concepts[run.id]["captureStatus"] == "pendingGeneration"
        assert store.runs[run.id]["lease_owner"] == "worker-new"

    asyncio.run(scenario())


def test_model_completed_checkpoint_resumes_without_duplicate_provider_calls() -> None:
    class CrashAfterModelCheckpointStore(MemoryWorkerStore):
        crashed = False

        async def checkpoint_model_run(self, *args: Any, **kwargs: Any) -> bool:
            stored = await super().checkpoint_model_run(*args, **kwargs)
            if kwargs["checkpoint"] == "modelCompleted" and not self.crashed:
                self.crashed = True
                raise asyncio.CancelledError
            return stored

    class CountingProvider(FakeProviderClient):
        calls = 0

        async def _record_model_call(self) -> None:
            type(self).calls += 1
            await super()._record_model_call()

    async def scenario() -> None:
        store = CrashAfterModelCheckpointStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "custom",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Checkpoint recovery", "locale": "en"}}
            ),
            idempotency_key="checkpoint-recovery",
            has_provider_credential=True,
        )

        with pytest.raises(PublicError) as stopped:
            await service.execute_initial(
                run.id,
                principal,
                "request-only-key",
                client_factory=CountingProvider,
            )
        assert stopped.value.code == "agent_lease_lost"
        assert store.runs[run.id]["checkpoint"] == "modelCompleted"
        calls_before_resume = CountingProvider.calls
        store.runs[run.id]["lease_expires_at"] = "2000-01-01T00:00:00Z"

        completed = await service.execute_initial(
            run.id,
            principal,
            "request-only-key",
            client_factory=CountingProvider,
        )
        assert completed.status == "succeeded"
        assert CountingProvider.calls == calls_before_resume
        assert len(store.concepts) == 1
        concept_id = str(completed.concept_id)
        assert len(store.turns[concept_id]) == 2
        assert sum(
            event["event_type"] == "completed" for event in store.events[run.id]
        ) == 1

    asyncio.run(scenario())


def test_retrieval_checkpoint_resumes_without_repeating_completed_search() -> None:
    class CrashAfterSearchStore(MemoryWorkerStore):
        crashed = False

        async def checkpoint_model_run(self, *args: Any, **kwargs: Any) -> bool:
            stored = await super().checkpoint_model_run(*args, **kwargs)
            if kwargs["checkpoint"] == "retrievalInProgress" and not self.crashed:
                self.crashed = True
                raise asyncio.CancelledError
            return stored

    class SearchThenExtractProvider(FakeProviderClient):
        async def request_initial_tool_calls(
            self,
            raw_capture: str,
            locale: str,
            tool_observations: list[dict[str, Any]] | None = None,
        ) -> tuple[RuntimeToolCall, ...]:
            del raw_capture, locale
            await self._record_model_call()
            if not tool_observations:
                return (
                    RuntimeToolCall(
                        id="search-call",
                        name="web_search",
                        arguments={"query": "Sift runtime recovery"},
                    ),
                )
            return (
                RuntimeToolCall(
                    id="extract-call",
                    name="web_extract",
                    arguments={"url": tool_observations[0]["result"][0]["url"]},
                ),
            )

    class CountingWebTools:
        def __init__(self) -> None:
            self.search_calls = 0
            self.extract_calls = 0

        async def search(self, _query: str) -> list[dict[str, str]]:
            self.search_calls += 1
            return [
                {
                    "id": "search-source",
                    "title": "Runtime recovery",
                    "url": "https://example.com/recovery",
                    "snippet": "Search evidence.",
                }
            ]

        async def extract(self, url: str) -> dict[str, str]:
            self.extract_calls += 1
            return {
                "id": "read-source",
                "title": "Runtime recovery",
                "url": url,
                "snippet": "Read evidence.",
                "provenance": "extracted",
            }

    async def scenario() -> None:
        store = CrashAfterSearchStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        web_tools = CountingWebTools()
        service = ModelRunService(store, web_search_client=web_tools)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {
                    "capture": {
                        "rawCapture": "Search the web for Sift runtime recovery",
                        "locale": "en",
                    }
                }
            ),
            idempotency_key="retrieval-checkpoint-recovery",
            has_provider_credential=True,
        )

        with pytest.raises(PublicError) as stopped:
            await service.execute_initial(
                run.id,
                principal,
                "request-only-key",
                client_factory=SearchThenExtractProvider,
            )
        assert stopped.value.code == "agent_lease_lost"
        assert store.runs[run.id]["checkpoint"] == "retrievalInProgress"
        assert web_tools.search_calls == 1

        store.runs[run.id]["lease_expires_at"] = "2000-01-01T00:00:00Z"
        completed = await service.execute_initial(
            run.id,
            principal,
            "request-only-key",
            client_factory=SearchThenExtractProvider,
        )

        assert completed.status == "succeeded"
        assert completed.tool_call_count == 2
        assert web_tools.search_calls == 1
        assert web_tools.extract_calls == 1

    asyncio.run(scenario())


def test_long_running_model_call_renews_execution_lease(monkeypatch) -> None:
    class HeartbeatStore(MemoryWorkerStore):
        renewals = 0

        async def renew_model_run_lease(self, *args: Any, **kwargs: Any) -> bool:
            self.renewals += 1
            return await super().renew_model_run_lease(*args, **kwargs)

    class SlowProvider(FakeProviderClient):
        async def stream_initial_answer(
            self,
            raw_capture: str,
            locale: str,
            retrieval_evidence: list[dict[str, str]] | None,
            on_delta,
        ) -> str:
            await asyncio.sleep(0.05)
            return await super().stream_initial_answer(
                raw_capture,
                locale,
                retrieval_evidence,
                on_delta,
            )

    async def scenario() -> None:
        store = HeartbeatStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Heartbeat safety", "locale": "en"}}
            ),
            idempotency_key="heartbeat-safety",
            has_provider_credential=True,
        )
        completed = await service.execute_initial(
            run.id,
            principal,
            "request-only-key",
            client_factory=SlowProvider,
        )

        assert completed.status == "succeeded"
        assert store.renewals >= 2

    monkeypatch.setattr("sift_worker.services.RUN_LEASE_HEARTBEAT_SECONDS", 0.01)
    asyncio.run(scenario())


def test_follow_up_model_checkpoint_resumes_without_duplicate_provider_calls() -> None:
    class CrashAfterFollowUpModelStore(MemoryWorkerStore):
        crashed = False

        async def checkpoint_model_run(self, *args: Any, **kwargs: Any) -> bool:
            stored = await super().checkpoint_model_run(*args, **kwargs)
            run = self.runs[str(args[0])]
            if (
                run["kind"] == "followUp"
                and kwargs["checkpoint"] == "modelCompleted"
                and not self.crashed
            ):
                self.crashed = True
                raise asyncio.CancelledError
            return stored

    class CountingProvider(FakeProviderClient):
        calls = 0

        async def _record_model_call(self) -> None:
            type(self).calls += 1
            await super()._record_model_call()

    async def scenario() -> None:
        store = CrashAfterFollowUpModelStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "custom",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        initial, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Recovery card", "locale": "en"}}
            ),
            idempotency_key="follow-up-recovery-initial",
            has_provider_credential=True,
        )
        completed_initial = await service.execute_initial(
            initial.id,
            principal,
            "request-only-key",
            client_factory=FakeProviderClient,
        )
        concept_id = str(completed_initial.concept_id)
        follow_up, _ = await service.submit_follow_up(
            principal,
            concept_id,
            CreateTurnRunRequest.model_validate(
                {"turn": {"question": "Explain the recovery contract."}}
            ),
            idempotency_key="follow-up-recovery",
            has_provider_credential=True,
        )

        with pytest.raises(PublicError) as stopped:
            await service.execute_follow_up(
                follow_up.id,
                principal,
                "request-only-key",
                client_factory=CountingProvider,
            )
        assert stopped.value.code == "agent_lease_lost"
        calls_before_resume = CountingProvider.calls
        store.runs[follow_up.id]["lease_expires_at"] = "2000-01-01T00:00:00Z"

        completed = await service.execute_follow_up(
            follow_up.id,
            principal,
            "request-only-key",
            client_factory=CountingProvider,
        )
        assert completed.status == "succeeded"
        assert CountingProvider.calls == calls_before_resume
        assert len(store.turns[concept_id]) == 4
        assert sum(
            event["event_type"] == "completed"
            for event in store.events[follow_up.id]
        ) == 1

    asyncio.run(scenario())


def test_failed_follow_up_does_not_enter_completed_conversation_history() -> None:
    class FailingFollowUpProvider(FakeProviderClient):
        async def stream_follow_up_answer(self, *args: Any, **kwargs: Any) -> str:
            await self._record_model_call()
            raise PublicError(
                "provider_unreachable",
                "The provider could not complete the follow-up.",
                502,
            )

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        initial, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Conversation safety", "locale": "en"}}
            ),
            idempotency_key="conversation-safety-initial",
            has_provider_credential=True,
        )
        completed_initial = await service.execute_initial(
            initial.id,
            principal,
            "request-only-key",
            client_factory=FakeProviderClient,
        )
        concept_id = str(completed_initial.concept_id)
        follow_up, _ = await service.submit_follow_up(
            principal,
            concept_id,
            CreateTurnRunRequest.model_validate(
                {"turn": {"question": "Explain failure recovery."}}
            ),
            idempotency_key="conversation-safety-follow-up",
            has_provider_credential=True,
        )

        assert len(store.turns[concept_id]) == 2
        assert "Explain failure recovery." in store.runs[follow_up.id]["payload_json"]

        with pytest.raises(PublicError) as failed:
            await service.execute_follow_up(
                follow_up.id,
                principal,
                "request-only-key",
                client_factory=FailingFollowUpProvider,
            )

        assert failed.value.code == "provider_unreachable"
        assert len(store.turns[concept_id]) == 2

    asyncio.run(scenario())


def test_answer_stream_checkpoint_resets_partial_delta_before_replay() -> None:
    class InterruptedStreamProvider(FakeProviderClient):
        interrupted = False

        async def stream_initial_answer(
            self,
            raw_capture: str,
            locale: str,
            retrieval_evidence: list[dict[str, str]] | None,
            on_delta,
        ) -> str:
            await self._record_model_call()
            del locale, retrieval_evidence
            if not type(self).interrupted:
                type(self).interrupted = True
                await on_delta("Partial answer that must be cleared. " * 12)
                raise asyncio.CancelledError
            answer = f"Recovered answer about {raw_capture}."
            await on_delta(answer)
            return answer

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "custom",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Stream recovery", "locale": "en"}}
            ),
            idempotency_key="stream-recovery",
            has_provider_credential=True,
        )
        with pytest.raises(PublicError) as stopped:
            await service.execute_initial(
                run.id,
                principal,
                "request-only-key",
                client_factory=InterruptedStreamProvider,
            )
        assert stopped.value.code == "agent_lease_lost"
        assert store.runs[run.id]["checkpoint"] == "answerStreaming"
        store.runs[run.id]["lease_expires_at"] = "2000-01-01T00:00:00Z"

        completed = await service.execute_initial(
            run.id,
            principal,
            "request-only-key",
            client_factory=InterruptedStreamProvider,
        )
        assert completed.status == "succeeded"
        event_types = [event["event_type"] for event in store.events[run.id]]
        assert event_types.index("delta") < event_types.index("deltaReset")
        concept = completed.result["concept"]
        assert concept["initialAnswer"] == "Recovered answer about Stream recovery."

    asyncio.run(scenario())


def test_cancelling_running_agent_prevents_domain_commit() -> None:
    started = asyncio.Event()
    release = asyncio.Event()

    class PausedProvider(FakeProviderClient):
        async def stream_initial_answer(
            self,
            raw_capture: str,
            locale: str,
            retrieval_evidence: list[dict[str, str]] | None,
            on_delta,
        ) -> str:
            del raw_capture, locale, retrieval_evidence
            await self._record_model_call()
            started.set()
            await release.wait()
            chunk = "This provider chunk arrives only after cancellation."
            await on_delta(chunk)
            return chunk

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "custom",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Cancel safely", "locale": "en"}}
            ),
            idempotency_key="cancel-running",
            has_provider_credential=True,
        )
        task = asyncio.create_task(
            service.execute_initial(
                run.id,
                principal,
                "request-only-key",
                client_factory=PausedProvider,
            )
        )
        await started.wait()
        cancelled = await service.cancel(run.id, principal.owner_id)
        assert cancelled.status == "cancelled"
        release.set()
        with pytest.raises(PublicError) as stopped:
            await task
        assert stopped.value.code == "agent_cancelled"
        assert store.concepts[run.id]["captureStatus"] == "generationFailed"
        assert store.events[run.id][-1]["event_type"] == "cancelled"

    asyncio.run(scenario())


def test_cancel_endpoint_is_owner_scoped_and_idempotent() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("cancel-invite")
    client = TestClient(create_app(lambda _request: store))
    session = activate(client, "cancel-invite", "installation-a")
    headers = auth_headers(session, "installation-a")
    submitted = client.post(
        "/v1/concept-runs",
        headers={**headers, "Idempotency-Key": "queued-cancel"},
        json={"capture": {"rawCapture": "Cancel queued", "locale": "en"}},
    ).json()

    first = client.post(f"/v1/model-runs/{submitted['id']}/cancel", headers=headers)
    second = client.post(f"/v1/model-runs/{submitted['id']}/cancel", headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "cancelled"
    assert second.json()["status"] == "cancelled"
    assert sum(
        event["event_type"] == "cancelled" for event in store.events[submitted["id"]]
    ) == 1


def test_provider_cannot_exceed_agent_model_call_budget() -> None:
    class RunawayProvider(FakeProviderClient):
        async def stream_initial_answer(
            self,
            raw_capture: str,
            locale: str,
            retrieval_evidence: list[dict[str, str]] | None,
            on_delta,
        ) -> str:
            del raw_capture, locale, retrieval_evidence, on_delta
            for _ in range(6):
                await self._record_model_call()
            return "unreachable"

    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "deepseek",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {"capture": {"rawCapture": "Bounded runtime", "locale": "en"}}
            ),
            idempotency_key="bounded-runtime",
            has_provider_credential=True,
        )

        with pytest.raises(PublicError) as error:
            await service.execute_initial(
                run.id,
                principal,
                "request-only-key",
                client_factory=RunawayProvider,
            )

        assert error.value.code == "agent_budget_exceeded"
        assert store.runs[run.id]["status"] == "failed"
        assert store.runs[run.id]["model_call_count"] == 6
        assert store.concepts[run.id]["captureStatus"] == "generationFailed"

    asyncio.run(scenario())


def test_explicit_retrieval_rejects_provider_without_tool_capability() -> None:
    async def scenario() -> None:
        store = MemoryWorkerStore()
        principal = CurrentPrincipal(owner_id="owner-a", installation_id="installation-a")
        await store.save_provider_connection(
            {
                "owner_id": principal.owner_id,
                "provider_id": "custom",
                "base_url": "https://provider.example/v1",
                "model": "test-model",
                "created_at": "2026-08-01T00:00:00Z",
                "updated_at": "2026-08-01T00:00:00Z",
            }
        )
        service = ModelRunService(store)
        run, _ = await service.submit_initial(
            principal,
            CreateConceptRunRequest.model_validate(
                {
                    "capture": {
                        "rawCapture": "Search the web for today's Sift news",
                        "locale": "en",
                    }
                }
            ),
            idempotency_key="missing-tool-capability",
            has_provider_credential=True,
        )

        with pytest.raises(PublicError) as error:
            await service.execute_initial(
                run.id,
                principal,
                "request-only-key",
                client_factory=FakeProviderClient,
            )

        assert error.value.code == "provider_capability_missing"
        assert store.runs[run.id]["error_code"] == "provider_capability_missing"
        assert store.runs[run.id]["model_call_count"] == 0

    asyncio.run(scenario())


class MemoryWorkerStore:
    def __init__(self) -> None:
        self.invites: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, dict[str, Any]] = {}
        self.revoked_owners: set[str] = set()
        self.provider_connections: dict[str, dict[str, Any]] = {}
        self.web_provider_settings: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.concepts: dict[str, dict[str, Any]] = {}
        self.turns: dict[str, list[dict[str, Any]]] = {}
        self.revisions: dict[str, list[dict[str, Any]]] = {}
        self.relations: dict[str, dict[str, Any]] = {}
        self.proposals: dict[str, dict[str, Any]] = {}
        self.mutation_idempotency: dict[tuple[str, str, str], dict[str, Any]] = {}
        self.sources: dict[str, dict[str, Any]] = {}
        self.continuity_summaries: dict[str, dict[str, Any]] = {}
        self.maintenance_state: dict[str, dict[str, Any]] = {}
        self.claims: dict[str, dict[str, Any]] = {}
        self.learning_state_entries: dict[str, dict[str, Any]] = {}

    def seed_invite(self, invite_code: str) -> None:
        code_hash = hashlib.sha256(invite_code.encode()).hexdigest()
        self.invites[code_hash] = {
            "code_hash": code_hash,
            "owner_id": None,
            "installation_id": None,
            "revoked_at": None,
        }

    async def get_invite(self, code_hash: str) -> dict[str, Any] | None:
        return deepcopy(self.invites.get(code_hash))

    async def activate_invite(
        self,
        *,
        code_hash: str,
        owner_id: str,
        installation_id: str,
        session_id: str,
        token_hash: str,
        expires_at: str,
        now: str,
    ) -> dict[str, Any] | None:
        invite = self.invites.get(code_hash)
        if invite is None or invite["revoked_at"] is not None:
            return None
        if invite["installation_id"] not in {None, installation_id}:
            return None
        invite["owner_id"] = invite["owner_id"] or owner_id
        invite["installation_id"] = invite["installation_id"] or installation_id
        invite["consumed_at"] = now
        session = {
            "id": session_id,
            "token_hash": token_hash,
            "owner_id": invite["owner_id"],
            "installation_id": invite["installation_id"],
            "expires_at": expires_at,
            "revoked_at": None,
            "created_at": now,
        }
        self.sessions[token_hash] = session
        return deepcopy(session)

    async def get_session(self, token_hash: str) -> dict[str, Any] | None:
        return deepcopy(self.sessions.get(token_hash))

    async def rotate_session(
        self,
        *,
        current_token_hash: str,
        session_id: str,
        token_hash: str,
        expires_at: str,
        now: str,
    ) -> dict[str, Any] | None:
        current = self.sessions.get(current_token_hash)
        if current is None or current["revoked_at"] is not None:
            return None
        current["revoked_at"] = now
        replacement = {
            **current,
            "id": session_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "revoked_at": None,
            "created_at": now,
        }
        self.sessions[token_hash] = replacement
        return deepcopy(replacement)

    async def owner_is_revoked(self, owner_id: str) -> bool:
        return owner_id in self.revoked_owners

    async def get_provider_connection(self, owner_id: str) -> dict[str, Any] | None:
        return deepcopy(self.provider_connections.get(owner_id))

    async def save_provider_connection(
        self,
        connection: dict[str, Any],
    ) -> dict[str, Any]:
        existing = self.provider_connections.get(str(connection["owner_id"]), {})
        stored = {**existing, **deepcopy(connection)}
        self.provider_connections[str(connection["owner_id"])] = stored
        return deepcopy(stored)

    async def get_web_provider_settings(self, owner_id: str) -> dict[str, Any]:
        return deepcopy(
            self.web_provider_settings.get(
                owner_id,
                {"provider_type": "ddgs", "web_search_enabled": 1},
            )
        )

    async def save_web_provider_settings(
        self,
        *,
        owner_id: str,
        provider_type: str,
        web_search_enabled: bool,
        now: str,
    ) -> dict[str, Any]:
        del now
        settings = {
            "provider_type": provider_type,
            "web_search_enabled": 1 if web_search_enabled else 0,
        }
        self.web_provider_settings[owner_id] = settings
        return deepcopy(settings)

    async def create_model_run(
        self,
        *,
        run: dict[str, Any],
        event: dict[str, Any],
        pending_concept: dict[str, Any] | None = None,
        input_turn: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        for existing in self.runs.values():
            if (
                existing["owner_id"],
                existing["kind"],
                existing["idempotency_key"],
            ) == (
                run["owner_id"],
                run["kind"],
                run["idempotency_key"],
            ):
                return deepcopy(existing), False
        self.runs[str(run["id"])] = deepcopy(run)
        self.events[str(run["id"])] = [deepcopy(event)]
        if pending_concept is not None:
            import json

            self.concepts[str(pending_concept["id"])] = json.loads(
                str(pending_concept["document_json"])
            )
        if input_turn is not None:
            self.turns.setdefault(str(input_turn["concept_id"]), []).append(
                deepcopy(input_turn)
            )
        return deepcopy(run), True

    async def get_model_run(self, run_id: str, owner_id: str) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        if run is None or run["owner_id"] != owner_id:
            return None
        response = deepcopy(run)
        response["child_run_ids"] = [
            child["id"]
            for child in self.runs.values()
            if child.get("dependency_run_id") == run_id
            and child["owner_id"] == owner_id
        ]
        return response

    async def list_model_runs(
        self,
        owner_id: str,
        *,
        active: bool,
    ) -> list[dict[str, Any]]:
        active_statuses = {"queued", "waitingForCredential", "running"}
        return [
            deepcopy(run)
            for run in self.runs.values()
            if run["owner_id"] == owner_id
            and (not active or run["status"] in active_statuses)
        ]

    async def list_model_run_events(
        self,
        run_id: str,
        owner_id: str,
        after_sequence: int,
    ) -> list[dict[str, Any]] | None:
        if await self.get_model_run(run_id, owner_id) is None:
            return None
        return [
            deepcopy(event)
            for event in self.events[run_id]
            if event["sequence"] > after_sequence
        ]

    async def append_model_run_event(
        self,
        run_id: str,
        owner_id: str,
        *,
        event_type: str,
        data_json: str,
        now: str,
        worker_id: str | None = None,
    ) -> int | None:
        run = await self.get_model_run(run_id, owner_id)
        if run is None or (worker_id is not None and run.get("lease_owner") != worker_id):
            return None
        import json

        self._append_event(run_id, event_type, json.loads(data_json), now)
        return int(self.events[run_id][-1]["sequence"])

    async def record_agent_event(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        event_type: str,
        data_json: str,
        now: str,
        current_step: str | None = None,
        update_current_step: bool = False,
        model_call_count: int | None = None,
        tool_call_count: int | None = None,
        step_count: int | None = None,
        model_latency_ms: int | None = None,
        input_token_count: int | None = None,
        output_token_count: int | None = None,
    ) -> int | None:
        run = self.runs.get(run_id)
        if (
            run is None
            or run["owner_id"] != owner_id
            or run["status"] != "running"
            or run.get("lease_owner") != worker_id
        ):
            return None
        if update_current_step:
            run["current_step"] = current_step
        if model_call_count is not None:
            run["model_call_count"] = model_call_count
        if tool_call_count is not None:
            run["tool_call_count"] = tool_call_count
        if step_count is not None:
            run["step_count"] = step_count
        if model_latency_ms is not None:
            run["model_latency_ms"] = int(run.get("model_latency_ms") or 0) + model_latency_ms
        if input_token_count is not None:
            run["input_token_count"] = int(run.get("input_token_count") or 0) + input_token_count
        if output_token_count is not None:
            run["output_token_count"] = int(run.get("output_token_count") or 0) + output_token_count
        run["updated_at"] = now
        import json

        self._append_event(run_id, event_type, json.loads(data_json), now)
        return int(self.events[run_id][-1]["sequence"])

    async def claim_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        now: str,
        worker_id: str,
        lease_expires_at: str,
    ) -> tuple[dict[str, Any] | None, bool]:
        run = self.runs.get(run_id)
        if run is None or run["owner_id"] != owner_id:
            return None, False
        reclaimable = run["status"] == "running" and str(
            run.get("lease_expires_at") or ""
        ) <= now
        if run["status"] not in {"queued", "waitingForCredential", "failed"} and not reclaimable:
            return deepcopy(run), False
        resumed = (
            run["status"] == "running"
            or bool(run.get("checkpoint"))
            or bool(run.get("current_step"))
        )
        run["status"] = "running"
        run["current_step"] = run.get("current_step") if resumed else "providerCall"
        run["current_step"] = run["current_step"] or "providerCall"
        run["lease_owner"] = worker_id
        run["lease_expires_at"] = lease_expires_at
        run["cancel_requested_at"] = None
        run["started_at"] = run.get("started_at") or now
        run["updated_at"] = now
        self._append_event(
            run_id,
            "restarted" if resumed else "started",
            {"step": run["current_step"], "resumed": resumed},
            now,
        )
        return deepcopy(run), True

    async def renew_model_run_lease(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        lease_expires_at: str,
        now: str,
    ) -> bool:
        run = self.runs.get(run_id)
        if (
            run is None
            or run["owner_id"] != owner_id
            or run["status"] != "running"
            or run.get("lease_owner") != worker_id
        ):
            return False
        run["lease_expires_at"] = lease_expires_at
        run["updated_at"] = now
        return True

    async def snapshot_model_run_provider(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        provider_snapshot_json: str,
        now: str,
    ) -> bool:
        run = self.runs.get(run_id)
        if (
            run is None
            or run["owner_id"] != owner_id
            or run["status"] != "running"
            or run.get("lease_owner") != worker_id
            or str(run.get("provider_snapshot_json") or "{}") != "{}"
        ):
            return False
        run["provider_snapshot_json"] = provider_snapshot_json
        run["updated_at"] = now
        return True

    async def checkpoint_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        checkpoint: str,
        checkpoint_json: str,
        now: str,
    ) -> bool:
        run = self.runs.get(run_id)
        if (
            run is None
            or run["owner_id"] != owner_id
            or run["status"] != "running"
            or run.get("lease_owner") != worker_id
        ):
            return False
        run["checkpoint"] = checkpoint
        run["checkpoint_json"] = checkpoint_json
        run["updated_at"] = now
        self._append_event(run_id, "checkpoint", {"name": checkpoint}, now)
        return True

    async def cancel_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        now: str,
    ) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        if run is None or run["owner_id"] != owner_id:
            return None
        if run["status"] in {"queued", "waitingForCredential", "running"}:
            run.update(
                {
                    "status": "cancelled",
                    "cancel_requested_at": now,
                    "termination_reason": "cancelled",
                    "current_step": None,
                    "lease_owner": None,
                    "lease_expires_at": None,
                    "completed_at": now,
                    "updated_at": now,
                }
            )
            if run["kind"] == "initialConcept" and run.get("concept_id") in self.concepts:
                self.concepts[str(run["concept_id"])]["captureStatus"] = "generationFailed"
                self.concepts[str(run["concept_id"])]["updatedAt"] = now
            self._append_event(run_id, "cancelled", {"code": "agent_cancelled"}, now)
        return deepcopy(run)

    async def model_run_is_cancelled(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
    ) -> bool:
        run = self.runs.get(run_id)
        del worker_id
        return bool(
            run is not None
            and run["owner_id"] == owner_id
            and run["status"] == "cancelled"
        )

    async def fail_model_run(
        self,
        run_id: str,
        owner_id: str,
        *,
        worker_id: str,
        code: str,
        message: str,
        now: str,
    ) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        if (
            run is None
            or run["owner_id"] != owner_id
            or run.get("lease_owner") != worker_id
        ):
            return None
        run.update(
            {
                "status": "failed",
                "error_code": code,
                "error_message": message,
                "termination_reason": code,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": now,
                "updated_at": now,
            }
        )
        if run["kind"] == "initialConcept" and run.get("concept_id") in self.concepts:
            self.concepts[str(run["concept_id"])]["captureStatus"] = "generationFailed"
            self.concepts[str(run["concept_id"])]["updatedAt"] = now
        self._append_event(run_id, "failed", {"code": code, "message": message}, now)
        return deepcopy(run)

    async def complete_initial_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        concept: dict[str, Any],
        blocks: list[dict[str, Any]],
        tags: list[str],
        topics: list[str],
        revision: dict[str, Any],
        turns: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        provider_snapshot_json: str,
        result_json: str,
        now: str,
        model_call_count: int = 1,
        tool_call_count: int = 0,
    ) -> dict[str, Any] | None:
        del blocks, tags, topics
        run = self.runs.get(run_id)
        if (
            run is None
            or run["owner_id"] != owner_id
            or run["status"] != "running"
            or run.get("lease_owner") != worker_id
        ):
            return deepcopy(run) if run is not None else None
        import json

        self.concepts[str(concept["id"])] = json.loads(str(concept["document_json"]))
        stored_turns = self.turns.setdefault(str(concept["id"]), [])
        existing_turn_keys = {
            (turn["operation_key"], turn["role"]) for turn in stored_turns
        }
        stored_turns.extend(
            deepcopy(turn)
            for turn in turns
            if (turn["operation_key"], turn["role"]) not in existing_turn_keys
        )
        for source in sources:
            self.sources[str(source["id"])] = {
                **deepcopy(source),
                "concept_id": str(concept["id"]),
                "owner_id": owner_id,
            }
        self.revisions[str(concept["id"])] = [
            {
                **deepcopy(revision),
                "current_revision": concept["note_revision"],
                "snapshot_schema_version": 1,
                "restored_from_revision": None,
            }
        ]
        run.update(
            {
                "status": "succeeded",
                "concept_id": concept["id"],
                "provider_snapshot_json": provider_snapshot_json,
                "result_json": result_json,
                "result_ref": concept["id"],
                "model_call_count": model_call_count,
                "tool_call_count": tool_call_count,
                "termination_reason": "completed",
                "current_step": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": now,
                "updated_at": now,
            }
        )
        self._append_event(run_id, "completed", json.loads(result_json), now)
        return deepcopy(run)

    async def complete_follow_up_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        concept_id: str,
        replacing_turn_index: int | None,
        turns: list[dict[str, Any]],
        proposal: dict[str, Any] | None,
        sources: list[dict[str, Any]],
        provider_snapshot_json: str,
        result_json: str,
        now: str,
        model_call_count: int = 1,
        tool_call_count: int = 0,
    ) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        if (
            run is None
            or run["owner_id"] != owner_id
            or run["status"] != "running"
            or run.get("lease_owner") != worker_id
        ):
            return deepcopy(run) if run is not None else None
        if replacing_turn_index is not None:
            del self.turns[concept_id][replacing_turn_index:]
        existing_roles = {
            (item["operation_key"], item["role"])
            for item in self.turns.setdefault(concept_id, [])
        }
        self.turns[concept_id].extend(
            deepcopy(turn)
            for turn in turns
            if (turn["operation_key"], turn["role"]) not in existing_roles
        )
        if proposal is not None:
            self.proposals[str(proposal["id"])] = {
                **deepcopy(proposal),
                "concept_id": concept_id,
                "owner_id": owner_id,
                "source_run_id": run_id,
                "resolved_at": None,
            }
        for source in sources:
            self.sources[str(source["id"])] = {
                **deepcopy(source),
                "concept_id": concept_id,
                "owner_id": owner_id,
            }
        import json

        run.update(
            {
                "status": "succeeded",
                "provider_snapshot_json": provider_snapshot_json,
                "result_json": result_json,
                "result_ref": concept_id,
                "model_call_count": model_call_count,
                "tool_call_count": tool_call_count,
                "termination_reason": "completed",
                "current_step": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": now,
                "updated_at": now,
            }
        )
        self._append_event(run_id, "completed", json.loads(result_json), now)
        return deepcopy(run)

    async def get_continuity_summary(
        self,
        concept_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        summary = self.continuity_summaries.get(concept_id)
        if summary is None or summary["owner_id"] != owner_id:
            return None
        return deepcopy(summary)

    async def get_maintenance_status(
        self,
        concept_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        turns = self.turns.get(concept_id, [])
        state = self.maintenance_state.get(concept_id, {})
        summary = self.continuity_summaries.get(concept_id, {})
        return {
            "turn_count": len(turns),
            "user_turn_count": sum(turn["role"] == "user" for turn in turns),
            "summarized_turn_count": summary.get("through_turn_count", 0),
            "reviewed_user_turn_count": state.get("reviewed_user_turn_count", 1),
            "review_due": state.get("review_due", 0),
            "has_pending_proposal": any(
                proposal["concept_id"] == concept_id
                and proposal["owner_id"] == owner_id
                and proposal["status"] == "proposed"
                for proposal in self.proposals.values()
            ),
        }

    async def complete_continuity_summary_run(self, **kwargs: Any) -> dict[str, Any] | None:
        import json

        run = self.runs[str(kwargs["run_id"])]
        if (
            run["status"] != "running"
            or run.get("lease_owner") != kwargs["worker_id"]
        ):
            return deepcopy(run)
        concept_id = str(kwargs["concept_id"])
        self.continuity_summaries[concept_id] = {
            "concept_id": concept_id,
            "owner_id": kwargs["owner_id"],
            "summary": kwargs["summary"],
            "through_turn_count": kwargs["through_turn_count"],
            "source_turns_hash": kwargs["source_turns_hash"],
        }
        run.update(
            {
                "status": "succeeded",
                "provider_snapshot_json": kwargs["provider_snapshot_json"],
                "result_json": kwargs["result_json"],
                "result_ref": concept_id,
                "model_call_count": 1,
                "termination_reason": "completed",
                "current_step": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": kwargs["now"],
                "updated_at": kwargs["now"],
            }
        )
        self._append_event(
            str(kwargs["run_id"]),
            "completed",
            json.loads(str(kwargs["result_json"])),
            str(kwargs["now"]),
        )
        return deepcopy(run)

    async def complete_knowledge_review_run(self, **kwargs: Any) -> dict[str, Any] | None:
        import json

        run = self.runs[str(kwargs["run_id"])]
        if (
            run["status"] != "running"
            or run.get("lease_owner") != kwargs["worker_id"]
        ):
            return deepcopy(run)
        concept_id = str(kwargs["concept_id"])
        proposal = kwargs.get("proposal")
        if proposal is not None:
            self.proposals[str(proposal["id"])] = {
                **deepcopy(proposal),
                "concept_id": concept_id,
                "owner_id": kwargs["owner_id"],
                "source_run_id": kwargs["run_id"],
                "origin": "periodicReview",
                "resolved_at": None,
            }
        for claim in kwargs.get("claims", []):
            self.claims[str(claim["id"])] = {
                **deepcopy(claim),
                "concept_id": concept_id,
                "owner_id": kwargs["owner_id"],
            }
        for update in kwargs.get("learning_state_updates", []):
            self.learning_state_entries[str(update["id"])] = {
                **deepcopy(update),
                "concept_id": concept_id,
                "owner_id": kwargs["owner_id"],
            }
        self.maintenance_state[concept_id] = {
            "reviewed_user_turn_count": kwargs["reviewed_user_turn_count"],
            "review_due": 0,
        }
        run.update(
            {
                "status": "succeeded",
                "provider_snapshot_json": kwargs["provider_snapshot_json"],
                "result_json": kwargs["result_json"],
                "result_ref": concept_id,
                "model_call_count": 1,
                "termination_reason": "completed",
                "current_step": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": kwargs["now"],
                "updated_at": kwargs["now"],
            }
        )
        self._append_event(
            str(kwargs["run_id"]),
            "completed",
            json.loads(str(kwargs["result_json"])),
            str(kwargs["now"]),
        )
        return deepcopy(run)

    async def list_update_proposals(
        self,
        concept_id: str,
        owner_id: str,
        status: str | None,
    ) -> list[dict[str, Any]] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        return [
            deepcopy(proposal)
            for proposal in reversed(list(self.proposals.values()))
            if proposal["concept_id"] == concept_id
            and proposal["owner_id"] == owner_id
            and (status is None or proposal["status"] == status)
        ]

    async def get_update_proposal(
        self,
        proposal_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        proposal = self.proposals.get(proposal_id)
        if proposal is None or proposal["owner_id"] != owner_id:
            return None
        return deepcopy(proposal)

    async def resolve_update_proposal(
        self,
        proposal_id: str,
        owner_id: str,
        *,
        status: str,
        now: str,
    ) -> bool:
        proposal = self.proposals.get(proposal_id)
        if (
            proposal is None
            or proposal["owner_id"] != owner_id
            or proposal["status"] != "proposed"
        ):
            return False
        proposal["status"] = status
        proposal["resolved_at"] = now
        return True

    async def complete_regenerated_follow_up_run(
        self,
        *,
        run_id: str,
        owner_id: str,
        worker_id: str,
        expected_revision: int,
        concept: dict[str, Any],
        blocks: list[dict[str, Any]],
        tags: list[str],
        topics: list[str],
        revision: dict[str, Any],
        turns: list[dict[str, Any]],
        provider_snapshot_json: str,
        result_json: str,
        now: str,
        model_call_count: int = 1,
        tool_call_count: int = 0,
    ) -> dict[str, Any] | None:
        del blocks, tags, topics
        run = self.runs.get(run_id)
        current = await self.get_concept(str(concept["id"]), owner_id)
        if (
            run is None
            or run["owner_id"] != owner_id
            or run["status"] != "running"
            or run.get("lease_owner") != worker_id
            or current is None
            or current["noteRevision"] != expected_revision
        ):
            return None
        import json

        concept_id = str(concept["id"])
        self.concepts[concept_id] = json.loads(str(concept["document_json"]))
        self.turns[concept_id] = deepcopy(turns)
        for existing in self.revisions.setdefault(concept_id, []):
            existing["current_revision"] = concept["note_revision"]
        self.revisions[concept_id].append(
            {
                **deepcopy(revision),
                "current_revision": concept["note_revision"],
                "restored_from_revision": None,
            }
        )
        run.update(
            {
                "status": "succeeded",
                "provider_snapshot_json": provider_snapshot_json,
                "result_json": result_json,
                "result_ref": concept_id,
                "model_call_count": model_call_count,
                "tool_call_count": tool_call_count,
                "termination_reason": "completed",
                "current_step": None,
                "lease_owner": None,
                "lease_expires_at": None,
                "completed_at": now,
                "updated_at": now,
            }
        )
        self._append_event(run_id, "completed", json.loads(result_json), now)
        return deepcopy(run)

    async def get_concept(self, concept_id: str, owner_id: str) -> dict[str, Any] | None:
        run = next(
            (
                candidate
                for candidate in self.runs.values()
                if candidate.get("concept_id") == concept_id
                and candidate["owner_id"] == owner_id
            ),
            None,
        )
        if run is None:
            return None
        concept = deepcopy(self.concepts.get(concept_id))
        if concept is None:
            return None
        concept["relations"] = [
            deepcopy(relation)
            for relation in self.relations.values()
            if concept_id
            in {relation["sourceConceptId"], relation["targetConceptId"]}
        ]
        concept["sources"] = [
            {
                "id": source["id"],
                "conceptId": source["concept_id"],
                "title": source["title"],
                "url": source["url"],
                "sourceType": source["source_type"],
                "retrievedAt": source["retrieved_at"],
                "publishedAt": source["published_at"],
                "contentHash": source["content_hash"],
            }
            for source in self.sources.values()
            if source["concept_id"] == concept_id and source["owner_id"] == owner_id
        ]
        concept["claims"] = [
            {
                "id": claim["id"],
                "conceptId": concept_id,
                "statement": claim["statement"],
                "type": claim["claim_type"],
                "evidenceStatus": claim["evidence_status"],
                "timeSensitivity": claim["time_sensitivity"],
                "sourceIds": [],
                "verifiedAt": claim["verified_at"],
                "supersededByClaimId": None,
            }
            for claim in self.claims.values()
            if claim["concept_id"] == concept_id and claim["owner_id"] == owner_id
        ]
        entries = [
            entry
            for entry in self.learning_state_entries.values()
            if entry["concept_id"] == concept_id and entry["owner_id"] == owner_id
        ]
        concept["learningState"] = (
            {
                "conceptId": concept_id,
                **{
                    field: [
                        {
                            "content": entry["content"],
                            "origin": entry["origin"],
                            "createdAt": entry["created_at"],
                        }
                        for entry in entries
                        if entry["field"] == field
                    ]
                    for field in (
                        "userContext",
                        "confirmedUnderstanding",
                        "openQuestions",
                        "recurringConfusions",
                    )
                },
            }
            if entries
            else None
        )
        return concept

    async def list_concepts(self, owner_id: str) -> list[dict[str, Any]]:
        allowed = {
            str(run["concept_id"])
            for run in self.runs.values()
            if run["owner_id"] == owner_id and run.get("concept_id")
        }
        concepts = []
        for concept_id in self.concepts:
            if concept_id not in allowed:
                continue
            concept = await self.get_concept(concept_id, owner_id)
            if concept is not None:
                concepts.append(concept)
        return concepts

    async def set_concepts_archived(
        self,
        concept_ids: list[str],
        owner_id: str,
        *,
        archived: bool,
        now: str,
    ) -> list[dict[str, Any]] | None:
        concepts = []
        for concept_id in concept_ids:
            concept = await self.get_concept(concept_id, owner_id)
            if concept is None:
                return None
            stored = self.concepts[concept_id]
            if archived:
                if stored["captureStatus"] != "archived":
                    stored["_archivedFromStatus"] = stored["captureStatus"]
                stored["captureStatus"] = "archived"
            else:
                stored["captureStatus"] = stored.pop("_archivedFromStatus", "ready")
            stored["updatedAt"] = now
            updated = await self.get_concept(concept_id, owner_id)
            if updated is not None:
                concepts.append(updated)
        return concepts

    async def add_concept_relation(
        self,
        *,
        relation: dict[str, Any],
        owner_id: str,
    ) -> dict[str, Any] | None:
        source_id = str(relation["source_concept_id"])
        target_id = str(relation["target_concept_id"])
        if (
            await self.get_concept(source_id, owner_id) is None
            or await self.get_concept(target_id, owner_id) is None
        ):
            return None
        existing = next(
            (
                item
                for item in self.relations.values()
                if (
                    item["sourceConceptId"],
                    item["targetConceptId"],
                    item["relationType"],
                )
                == (source_id, target_id, relation["relation_type"])
            ),
            None,
        )
        if existing is None:
            self.relations[str(relation["id"])] = {
                "id": relation["id"],
                "sourceConceptId": source_id,
                "targetConceptId": target_id,
                "relationType": relation["relation_type"],
                "status": relation["status"],
                "confidence": relation["confidence"],
                "source": relation["source"],
            }
        return await self.get_concept(source_id, owner_id)

    async def remove_concept_relation(
        self,
        *,
        concept_id: str,
        relation_id: str,
        owner_id: str,
    ) -> dict[str, Any] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        relation = self.relations.get(relation_id)
        if relation is None or concept_id not in {
            relation["sourceConceptId"],
            relation["targetConceptId"],
        }:
            return None
        del self.relations[relation_id]
        return await self.get_concept(concept_id, owner_id)

    async def list_concept_turns(
        self,
        concept_id: str,
        owner_id: str,
    ) -> list[dict[str, Any]] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        return deepcopy(self.turns.get(concept_id, []))

    async def list_note_revisions(
        self,
        concept_id: str,
        owner_id: str,
    ) -> list[dict[str, Any]] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        return deepcopy(list(reversed(self.revisions.get(concept_id, []))))

    async def get_note_revision(
        self,
        concept_id: str,
        revision: int,
        owner_id: str,
    ) -> dict[str, Any] | None:
        if await self.get_concept(concept_id, owner_id) is None:
            return None
        return deepcopy(
            next(
                (
                    item
                    for item in self.revisions.get(concept_id, [])
                    if item["revision"] == revision
                ),
                None,
            )
        )

    async def save_concept_revision(
        self,
        *,
        concept_id: str,
        owner_id: str,
        expected_revision: int,
        concept: dict[str, Any],
        blocks: list[dict[str, Any]],
        tags: list[str],
        topics: list[str],
        revision: dict[str, Any],
        proposal_id: str | None = None,
        idempotency: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        del blocks, tags, topics
        current = await self.get_concept(concept_id, owner_id)
        if current is None or current["noteRevision"] != expected_revision:
            return None
        proposal = self.proposals.get(proposal_id) if proposal_id is not None else None
        if proposal_id is not None and (
            proposal is None
            or proposal["owner_id"] != owner_id
            or proposal["status"] != "proposed"
            or proposal["base_note_revision"] != expected_revision
        ):
            return None
        import json

        document = json.loads(str(concept["document_json"]))
        self.concepts[concept_id] = document
        for existing in self.revisions.setdefault(concept_id, []):
            existing["current_revision"] = concept["note_revision"]
        self.revisions[concept_id].append(
            {
                **deepcopy(revision),
                "current_revision": concept["note_revision"],
            }
        )
        if proposal is not None:
            proposal["status"] = "accepted"
            proposal["resolved_at"] = concept["updated_at"]
        if idempotency is not None:
            self.mutation_idempotency[
                (
                    owner_id,
                    str(idempotency["scope"]),
                    str(idempotency["idempotency_key"]),
                )
            ] = deepcopy(idempotency)
        return deepcopy(document)

    async def get_mutation_idempotency(
        self,
        owner_id: str,
        scope: str,
        idempotency_key: str,
    ) -> dict[str, Any] | None:
        return deepcopy(
            self.mutation_idempotency.get((owner_id, scope, idempotency_key))
        )

    def _append_event(
        self,
        run_id: str,
        event_type: str,
        data: dict[str, Any],
        now: str,
    ) -> None:
        events = self.events.setdefault(run_id, [])
        events.append(
            {
                "run_id": run_id,
                "sequence": len(events) + 1,
                "event_type": event_type,
                "data_json": __import__("json").dumps(data),
                "created_at": now,
            }
        )


class FakeProviderClient:
    def __init__(self, connection, api_key: str) -> None:
        self.connection = connection
        self.api_key = api_key
        self.model_call_count = 0
        self.model_call_observer = None

    def bind_model_call_observer(self, observer) -> None:
        self.model_call_observer = observer

    async def _record_model_call(self) -> None:
        if self.model_call_observer is not None:
            await self.model_call_observer()
        self.model_call_count += 1

    async def request_initial_tool_calls(
        self,
        raw_capture: str,
        locale: str,
        tool_observations: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeToolCall, ...]:
        del locale
        await self._record_model_call()
        if tool_observations:
            return ()
        return _fake_web_search_tool_calls(raw_capture)

    async def request_follow_up_tool_calls(
        self,
        concept: dict[str, Any],
        question: str,
        recent_turns: list[dict[str, str]],
        continuity_summary: str,
        tool_observations: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeToolCall, ...]:
        del concept, recent_turns, continuity_summary
        await self._record_model_call()
        if tool_observations:
            return ()
        return _fake_web_search_tool_calls(question)

    async def test(self) -> None:
        return None

    async def list_models(self) -> list[str]:
        return [self.connection.model, "provider-model-2"]

    async def generate_initial_concept(
        self,
        raw_capture: str,
        locale: str,
        *,
        answer: str | None = None,
        retrieval_evidence: list[dict[str, str]] | None = None,
    ) -> InitialConceptResult:
        await self._record_model_call()
        del locale
        evidence = retrieval_evidence or []
        citations = [
            {"sourceId": item["id"], "title": item["title"], "url": item["url"]}
            for item in evidence[:1]
        ]
        return InitialConceptResult.model_validate(
            {
                "canonicalTitle": raw_capture,
                "displayTitle": raw_capture,
                "oneLineExplanation": f"{raw_capture} explained.",
                "answer": answer or f"An answer about {raw_capture}.",
                "blocks": [
                    {"blockType": "whatItIs", "content": "A generated definition."},
                    {"blockType": "whyItMatters", "content": "A generated reason."},
                ],
                "suggestedTags": [{"name": "Cloudflare", "confidence": 0.9}],
                "suggestedTopics": [{"name": "Infrastructure", "confidence": 0.8}],
                "answerSource": {
                    "sourceType": "webVerified" if evidence else "modelKnowledge",
                    "confidence": 0.8,
                    "uncertaintyNote": None,
                    "retrievalUsed": bool(evidence),
                    "freshnessNote": "Checked now." if evidence else None,
                    "citations": citations,
                },
                "proposal": None,
                "modelMeta": {
                    "provider": self.connection.provider_id,
                    "model": self.connection.model,
                    "latencyMs": 1,
                    "inputTokens": 10,
                    "outputTokens": 20,
                },
            }
        )

    async def generate_initial_answer(
        self,
        raw_capture: str,
        locale: str,
        retrieval_evidence: list[dict[str, str]] | None = None,
    ) -> str:
        await self._record_model_call()
        del locale, retrieval_evidence
        return (
            f"**What it is**\n\nAn answer about {raw_capture}.\n\n"
            "**Why it matters**\n\nIt is useful enough to become a durable card."
        )

    async def stream_initial_answer(
        self,
        raw_capture: str,
        locale: str,
        retrieval_evidence: list[dict[str, str]] | None,
        on_delta,
    ) -> str:
        await self._record_model_call()
        del locale, retrieval_evidence
        deltas = [
            "**What it is**\n\n",
            f"An answer about {raw_capture}",
            ".\n\n**Why it matters**\n\nIt is useful enough to become a durable card.",
        ]
        for delta in deltas:
            await on_delta(delta)
        return "".join(deltas)

    async def generate_follow_up(
        self,
        concept: dict[str, Any],
        question: str,
        recent_turns: list[dict[str, str]],
        retrieval_evidence: list[dict[str, str]] | None = None,
        continuity_summary: str = "",
        *,
        answer: str | None = None,
    ) -> FollowUpResult:
        await self._record_model_call()
        del recent_turns, continuity_summary
        evidence = retrieval_evidence or []
        citations = [
            {"sourceId": item["id"], "title": item["title"], "url": item["url"]}
            for item in evidence[:1]
        ]
        proposal = None
        if question.lower().startswith("save "):
            proposal = {
                "patchOperations": [
                    {
                        "operation": "append",
                        "targetBlockId": concept["blocks"][0]["id"],
                        "content": question[5:],
                    }
                ],
                "rationale": "The user asked to save this durable detail.",
            }
        return FollowUpResult.model_validate(
            {
                "answer": answer or f"{question} about {concept['displayTitle']}.",
                "answerSource": {
                    "sourceType": "webVerified" if evidence else "modelKnowledge",
                    "confidence": 0.8,
                    "uncertaintyNote": None,
                    "retrievalUsed": bool(evidence),
                    "freshnessNote": "Checked now." if evidence else None,
                    "citations": citations,
                },
                "proposal": proposal,
                "modelMeta": {
                    "provider": self.connection.provider_id,
                    "model": self.connection.model,
                    "latencyMs": 1,
                    "inputTokens": 10,
                    "outputTokens": 20,
                },
            }
        )

    async def generate_follow_up_answer(
        self,
        concept: dict[str, Any],
        question: str,
        recent_turns: list[dict[str, str]],
        retrieval_evidence: list[dict[str, str]] | None = None,
        continuity_summary: str = "",
    ) -> str:
        await self._record_model_call()
        del recent_turns, retrieval_evidence, continuity_summary
        return f"{question} about {concept['displayTitle']}."

    async def stream_follow_up_answer(
        self,
        concept: dict[str, Any],
        question: str,
        recent_turns: list[dict[str, str]],
        retrieval_evidence: list[dict[str, str]] | None,
        continuity_summary: str,
        on_delta,
    ) -> str:
        await self._record_model_call()
        del recent_turns, retrieval_evidence, continuity_summary
        deltas = [question, " about ", f"{concept['displayTitle']}."]
        for delta in deltas:
            await on_delta(delta)
        return "".join(deltas)

    async def summarize_continuity(
        self,
        concept: dict[str, Any],
        turns: list[dict[str, str]],
    ) -> ContinuitySummaryResult:
        await self._record_model_call()
        del concept
        return ContinuitySummaryResult(
            summary=f"Summary of {len(turns)} earlier turns."
        )

    async def review_knowledge(
        self,
        concept: dict[str, Any],
        turns: list[dict[str, str]],
        continuity_summary: str,
    ) -> KnowledgeReviewResult:
        await self._record_model_call()
        del turns, continuity_summary
        return KnowledgeReviewResult.model_validate(
            {
                "proposal": {
                    "patchOperations": [
                        {
                            "operation": "append",
                            "targetBlockId": concept["blocks"][0]["id"],
                            "content": "Periodic learning review.",
                        }
                    ],
                    "rationale": "Recent follow-ups established durable knowledge.",
                },
                "claims": [
                    {
                        "statement": "Maintenance reviews preserve durable knowledge.",
                        "type": "fact",
                        "evidenceStatus": "modelExplanation",
                        "timeSensitivity": "stable",
                        "sourceIds": [],
                    }
                ],
                "learningStateUpdates": [
                    {
                        "field": "confirmedUnderstanding",
                        "content": "The user connected follow-ups to durable notes.",
                        "origin": "userConfirmed",
                    }
                ],
            }
        )


def _fake_web_search_tool_calls(question: str) -> tuple[RuntimeToolCall, ...]:
    normalized = question.casefold()
    if not any(term in normalized for term in ("latest", "today", "use web search")):
        return ()
    return (
        RuntimeToolCall(
            id="call-search",
            name="web_search",
            arguments={"query": question},
        ),
    )


def activate(client: TestClient, invite_code: str, installation_id: str) -> dict[str, Any]:
    response = client.post(
        "/v1/beta/activate",
        json={"inviteCode": invite_code, "installationId": installation_id},
    )
    assert response.status_code == 200
    return response.json()


def auth_headers(session: dict[str, Any], installation_id: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {session['betaAccessToken']}",
        "X-Sift-Installation": installation_id,
    }


def test_health_identifies_cloudflare_runtime() -> None:
    app = create_app(lambda _request: MemoryWorkerStore())
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "env": "development",
        "runtime": "cloudflare-workers",
    }


def test_activation_binds_invite_to_installation_and_authenticates() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("invite-one")
    client = TestClient(create_app(lambda _request: store))

    session = activate(client, "invite-one", "installation-a")
    response = client.get(
        "/v1/model-runs",
        headers=auth_headers(session, "installation-a"),
    )
    reused = activate(client, "invite-one", "installation-a")
    conflict = client.post(
        "/v1/beta/activate",
        json={"inviteCode": "invite-one", "installationId": "installation-b"},
    )

    assert response.status_code == 200
    assert response.json() == []
    assert reused["ownerId"] == session["ownerId"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "invite_consumed"


def test_session_refresh_rotates_token_and_invalidates_previous_token() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("refreshable")
    client = TestClient(create_app(lambda _request: store))
    session = activate(client, "refreshable", "installation-a")

    refreshed = client.post(
        "/v1/beta/session/refresh",
        headers=auth_headers(session, "installation-a"),
    )
    old_token_response = client.get(
        "/v1/app-status",
        headers=auth_headers(session, "installation-a"),
    )
    new_token_response = client.get(
        "/v1/app-status",
        headers=auth_headers(refreshed.json(), "installation-a"),
    )

    assert refreshed.status_code == 200
    assert refreshed.json()["ownerId"] == session["ownerId"]
    assert refreshed.json()["betaAccessToken"] != session["betaAccessToken"]
    assert old_token_response.status_code == 401
    assert new_token_response.status_code == 200


def test_managed_web_search_setting_is_persisted() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("web-setting")
    client = TestClient(create_app(lambda _request: store))
    session = activate(client, "web-setting", "installation-a")
    headers = auth_headers(session, "installation-a")

    initial = client.get("/v1/web-provider-settings", headers=headers)
    updated = client.put(
        "/v1/web-provider-settings",
        headers=headers,
        json={
            "providerType": "ddgs",
            "apiKey": None,
            "webSearchEnabled": False,
        },
    )
    status = client.get("/v1/app-status", headers=headers)

    assert initial.json()["webSearchEnabled"] is True
    assert updated.status_code == 200
    assert updated.json()["webSearchEnabled"] is False
    assert status.json()["webSearchEnabled"] is False


def test_managed_bootstrap_contract_matches_ios_client() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("bootstrap")
    client = TestClient(create_app(lambda _request: store))
    session = activate(client, "bootstrap", "installation-a")
    headers = auth_headers(session, "installation-a")

    status = client.get("/v1/app-status", headers=headers)
    models = client.get("/v1/runtime/model-providers", headers=headers)
    web = client.get("/v1/runtime/web-providers", headers=headers)

    assert status.status_code == 200
    assert status.json()["databaseURL"] == "d1"
    assert status.json()["modelProvider"] == "unconfigured"
    assert models.status_code == 200
    model_providers = models.json()["providers"]
    assert {provider["id"] for provider in model_providers} >= {
        "openai",
        "anthropic",
        "gemini",
        "custom",
    }
    assert all(
        provider["exposureTier"] in {"plannedStable", "advanced"}
        for provider in model_providers
    )
    assert all(provider["supportsModelListing"] for provider in model_providers)
    assert web.status_code == 200
    assert {provider["id"] for provider in web.json()["providers"]} == {
        "ddgs",
        "tavily",
        "exa",
        "firecrawl",
        "brave-free",
        "xai",
    }
    assert web.json()["providers"][0]["supportsSearch"] is True


def test_managed_provider_model_listing_relays_key_without_persisting_it() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("model-listing")
    client = TestClient(create_app(lambda _request: store, FakeProviderClient))
    session = activate(client, "model-listing", "installation-a")
    headers = {
        **auth_headers(session, "installation-a"),
        "X-Sift-Provider-Key": "ephemeral-secret",
    }

    response = client.post(
        "/v1/providers/models",
        headers=headers,
        json={
            "providerId": "openai",
            "baseURL": "https://api.openai.com/v1",
            "model": "gpt-5.5",
        },
    )

    assert response.status_code == 200
    assert response.json()["models"] == [
        {"id": "gpt-5.5", "ownedBy": "openai"},
        {"id": "provider-model-2", "ownedBy": "openai"},
    ]
    assert "ephemeral-secret" not in repr(store.provider_connections)


def test_managed_provider_test_is_read_only() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("provider-test")
    client = TestClient(create_app(lambda _request: store, FakeProviderClient))
    session = activate(client, "provider-test", "installation-a")
    headers = {
        **auth_headers(session, "installation-a"),
        "X-Sift-Provider-Key": "ephemeral-secret",
    }

    response = client.post(
        "/v1/providers/test",
        headers=headers,
        json={
            "providerId": "deepseek",
            "baseURL": "https://api.deepseek.com/v1",
            "model": "deepseek-v4-flash",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert store.provider_connections == {}
    assert "ephemeral-secret" not in repr(store.provider_connections)


def test_capture_is_persisted_before_generation_and_provider_key_is_not_stored() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("invite-two")
    client = TestClient(
        create_app(
            lambda _request: store,
            provider_client_factory=FakeProviderClient,
        )
    )
    session = activate(client, "invite-two", "installation-a")
    connection = client.put(
        "/v1/provider-connection",
        headers=auth_headers(session, "installation-a"),
        json={
            "providerId": "custom",
            "baseURL": "https://provider.example/v1",
            "model": "test-model",
        },
    )
    assert connection.status_code == 200
    headers = {
        **auth_headers(session, "installation-a"),
        "Idempotency-Key": "capture-operation-1",
        "X-Sift-Provider-Key": "provider-secret-value",
    }

    response = client.post(
        "/v1/concept-runs",
        headers=headers,
        json={
            "capture": {"rawCapture": "Cloudflare Workers", "locale": "en"},
            "clientDraftId": "2ba815bb-f936-4758-969c-293c9aab7241",
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "succeeded"
    persisted = store.runs[body["id"]]
    assert persisted["status"] == "succeeded"
    assert persisted["idempotency_key"] == "capture-operation-1"
    assert persisted["owner_id"] == session["ownerId"]
    assert "provider-secret-value" not in repr(persisted)
    assert "provider-secret-value" not in repr(store.events[persisted["id"]])
    concept = body["result"]["concept"]
    assert concept["captureStatus"] == "ready"
    assert concept["displayTitle"] == "Cloudflare Workers"
    stored_concept = client.get(
        f"/v1/concepts/{concept['id']}",
        headers=auth_headers(session, "installation-a"),
    )
    turns = client.get(
        f"/v1/concepts/{concept['id']}/turns",
        headers=auth_headers(session, "installation-a"),
    )
    revisions = client.get(
        f"/v1/concepts/{concept['id']}/revisions",
        headers=auth_headers(session, "installation-a"),
    )
    revision = client.get(
        f"/v1/concepts/{concept['id']}/revisions/1",
        headers=auth_headers(session, "installation-a"),
    )
    assert stored_concept.status_code == 200
    assert stored_concept.json() == concept
    assert turns.status_code == 200
    assert [(turn["role"], turn["content"]) for turn in turns.json()] == [
        ("user", "Cloudflare Workers"),
        ("assistant", concept["initialAnswer"]),
    ]
    assert revisions.status_code == 200
    assert revisions.json()[0]["source"] == "initialGeneration"
    assert revisions.json()[0]["isCurrent"] is True
    assert revision.status_code == 200
    assert revision.json()["displayTitle"] == "Cloudflare Workers"
    assert revision.json()["blocks"] == concept["blocks"]


def test_manual_edits_and_revision_restore_preserve_concept_history() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("editable")
    client = TestClient(
        create_app(
            lambda _request: store,
            provider_client_factory=FakeProviderClient,
        )
    )
    session = activate(client, "editable", "installation-a")
    headers = auth_headers(session, "installation-a")
    assert client.put(
        "/v1/provider-connection",
        headers=headers,
        json={
            "providerId": "custom",
            "baseURL": "https://provider.example/v1",
            "model": "test-model",
        },
    ).status_code == 200
    created = client.post(
        "/v1/concept-runs",
        headers={**headers, "X-Sift-Provider-Key": "request-only-key"},
        json={"capture": {"rawCapture": "Original title", "locale": "en"}},
    ).json()["result"]["concept"]
    concept_id = created["id"]
    block_id = created["blocks"][0]["id"]

    summary = client.patch(
        f"/v1/concepts/{concept_id}",
        headers=headers,
        json={"displayTitle": "Edited title", "oneLineExplanation": "Edited summary"},
    )
    block = client.patch(
        f"/v1/concepts/{concept_id}/blocks/{block_id}",
        headers=headers,
        json={"content": "A user-edited definition."},
    )
    whole_note = client.put(
        f"/v1/concepts/{concept_id}/note",
        headers=headers,
        json={
            "displayTitle": "Edited title",
            "oneLineExplanation": "Edited summary",
            "blocks": [
                {
                    "id": block_id,
                    "blockType": "whatItIs",
                    "content": "A user-edited definition.",
                },
                {
                    "blockType": "example",
                    "content": "A new user example.",
                },
            ],
            "tags": [" Workers ", "workers", "Edge"],
            "topics": ["Infrastructure"],
        },
    )
    organization = client.patch(
        f"/v1/concepts/{concept_id}/organization",
        headers=headers,
        json={"tags": ["Saved"], "topics": ["Knowledge", "knowledge"]},
    )
    missing_block = client.patch(
        f"/v1/concepts/{concept_id}/blocks/not-this-concept",
        headers=headers,
        json={"content": "Must not be saved"},
    )
    restored = client.post(
        f"/v1/concepts/{concept_id}/revisions/1/restore",
        headers=headers,
        json={},
    )
    revisions = client.get(
        f"/v1/concepts/{concept_id}/revisions",
        headers=headers,
    )

    assert summary.status_code == 200
    assert summary.json()["canonicalTitle"] == "Edited title"
    assert summary.json()["noteRevision"] == 2
    assert block.status_code == 200
    assert block.json()["maturity"] == "growing"
    assert block.json()["blocks"][0]["source"] == "user"
    assert block.json()["blocks"][0]["isUserLocked"] is True
    assert block.json()["noteRevision"] == 3
    assert whole_note.status_code == 200
    assert whole_note.json()["noteRevision"] == 4
    assert whole_note.json()["blocks"][0]["revision"] == 1
    assert whole_note.json()["tags"] == ["Workers", "Edge"]
    assert organization.status_code == 200
    assert organization.json()["noteRevision"] == 5
    assert organization.json()["tags"] == ["Saved"]
    assert organization.json()["topics"] == ["Knowledge"]
    assert missing_block.status_code == 404
    assert restored.status_code == 200
    assert restored.json()["noteRevision"] == 6
    assert restored.json()["displayTitle"] == "Original title"
    assert restored.json()["blocks"] == created["blocks"]
    assert restored.json()["tags"] == ["Saved"]
    assert restored.json()["topics"] == ["Knowledge"]
    assert revisions.status_code == 200
    assert [item["revision"] for item in revisions.json()] == [6, 5, 4, 3, 2, 1]
    assert revisions.json()[0]["source"] == "revisionRestore"
    assert revisions.json()[0]["restoredFromRevision"] == 1
    assert revisions.json()[0]["isCurrent"] is True


def test_archive_restore_and_relations_match_ios_contract() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("lifecycle")
    client = TestClient(
        create_app(
            lambda _request: store,
            provider_client_factory=FakeProviderClient,
        )
    )
    session = activate(client, "lifecycle", "installation-a")
    headers = auth_headers(session, "installation-a")
    assert client.put(
        "/v1/provider-connection",
        headers=headers,
        json={
            "providerId": "custom",
            "baseURL": "https://provider.example/v1",
            "model": "test-model",
        },
    ).status_code == 200

    concepts = []
    for capture in ("Source concept", "Target concept"):
        response = client.post(
            "/v1/concept-runs",
            headers={**headers, "X-Sift-Provider-Key": "request-only-key"},
            json={"capture": {"rawCapture": capture, "locale": "en"}},
        )
        concepts.append(response.json()["result"]["concept"])
    source_id, target_id = (concept["id"] for concept in concepts)

    archived = client.patch(
        "/v1/concepts/archive",
        headers=headers,
        json={"conceptIds": [source_id, source_id]},
    )
    restored = client.patch(
        "/v1/concepts/restore",
        headers=headers,
        json={"conceptIds": [source_id]},
    )
    related = client.post(
        f"/v1/concepts/{source_id}/relations",
        headers=headers,
        json={"targetConceptId": target_id, "relationType": "supports"},
    )
    relation = related.json()["relations"][0]
    target = client.get(f"/v1/concepts/{target_id}", headers=headers)
    removed = client.delete(
        f"/v1/concepts/{target_id}/relations/{relation['id']}",
        headers=headers,
    )

    assert archived.status_code == 200
    assert len(archived.json()) == 1
    assert archived.json()[0]["captureStatus"] == "archived"
    assert restored.status_code == 200
    assert restored.json()[0]["captureStatus"] == "ready"
    assert related.status_code == 200
    assert relation["sourceConceptId"] == source_id
    assert relation["targetConceptId"] == target_id
    assert relation["relationType"] == "supports"
    assert target.status_code == 200
    assert target.json()["relations"] == [relation]
    assert removed.status_code == 200
    assert removed.json()["relations"] == []
    assert client.get(
        f"/v1/concepts/{source_id}",
        headers=headers,
    ).json()["relations"] == []


def test_follow_up_run_persists_turns_and_replaces_a_user_turn_idempotently() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("follow-up")
    client = TestClient(
        create_app(
            lambda _request: store,
            provider_client_factory=FakeProviderClient,
        )
    )
    session = activate(client, "follow-up", "installation-a")
    headers = auth_headers(session, "installation-a")
    assert client.put(
        "/v1/provider-connection",
        headers=headers,
        json={
            "providerId": "custom",
            "baseURL": "https://provider.example/v1",
            "model": "test-model",
        },
    ).status_code == 200
    concept = client.post(
        "/v1/concept-runs",
        headers={**headers, "X-Sift-Provider-Key": "request-only-key"},
        json={"capture": {"rawCapture": "Follow-up target", "locale": "en"}},
    ).json()["result"]["concept"]
    turn_headers = {
        **headers,
        "X-Sift-Provider-Key": "request-only-key",
        "Idempotency-Key": "follow-up-operation",
    }

    first = client.post(
        f"/v1/concepts/{concept['id']}/turn-runs",
        headers=turn_headers,
        json={"turn": {"question": "Why does it matter?"}},
    )
    retry = client.post(
        f"/v1/concepts/{concept['id']}/turn-runs",
        headers=turn_headers,
        json={"turn": {"question": "Why does it matter?"}},
    )
    replacement = client.post(
        f"/v1/concepts/{concept['id']}/turn-runs",
        headers={
            **turn_headers,
            "Idempotency-Key": "replacement-operation",
        },
        json={
            "turn": {
                "question": "Why is it useful?",
                "replacingTurnIndex": 2,
            }
        },
    )
    turns = client.get(
        f"/v1/concepts/{concept['id']}/turns",
        headers=headers,
    )

    assert first.status_code == 202
    assert first.json()["status"] == "succeeded"
    response = first.json()["result"]["response"]
    assert response["answer"] == "Why does it matter? about Follow-up target."
    assert response["updateMode"] == "none"
    assert response["concept"] == concept
    assert retry.status_code == 202
    assert retry.json()["id"] == first.json()["id"]
    assert replacement.status_code == 202
    assert replacement.json()["status"] == "succeeded"
    assert [(turn["role"], turn["content"]) for turn in turns.json()] == [
        ("user", "Follow-up target"),
        ("assistant", concept["initialAnswer"]),
        ("user", "Why is it useful?"),
        ("assistant", "Why is it useful? about Follow-up target."),
    ]
    assert "request-only-key" not in repr(store.runs)
    assert "request-only-key" not in repr(store.turns)

    regenerated = client.post(
        f"/v1/concepts/{concept['id']}/turn-runs",
        headers={
            **turn_headers,
            "Idempotency-Key": "initial-replacement-operation",
        },
        json={
            "turn": {
                "question": "Regenerated title",
                "replacingTurnIndex": 0,
            }
        },
    )
    regenerated_turns = client.get(
        f"/v1/concepts/{concept['id']}/turns",
        headers=headers,
    )
    regenerated_revisions = client.get(
        f"/v1/concepts/{concept['id']}/revisions",
        headers=headers,
    )

    assert regenerated.status_code == 202
    regenerated_concept = regenerated.json()["result"]["response"]["concept"]
    assert regenerated_concept["id"] == concept["id"]
    assert regenerated_concept["displayTitle"] == "Regenerated title"
    assert regenerated_concept["noteRevision"] == 2
    assert [(turn["role"], turn["content"]) for turn in regenerated_turns.json()] == [
        ("user", "Regenerated title"),
        ("assistant", regenerated_concept["initialAnswer"]),
    ]
    assert regenerated_revisions.json()[0]["source"] == "retryGeneration"
    assert regenerated_revisions.json()[0]["revision"] == 2


def test_fifth_follow_up_runs_continuity_and_periodic_review_children() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("maintenance")
    client = TestClient(
        create_app(
            lambda _request: store,
            provider_client_factory=FakeProviderClient,
        )
    )
    session = activate(client, "maintenance", "installation-a")
    headers = auth_headers(session, "installation-a")
    assert client.put(
        "/v1/provider-connection",
        headers=headers,
        json={
            "providerId": "custom",
            "baseURL": "https://provider.example/v1",
            "model": "test-model",
        },
    ).status_code == 200
    concept = client.post(
        "/v1/concept-runs",
        headers={**headers, "X-Sift-Provider-Key": "request-only-key"},
        json={"capture": {"rawCapture": "Maintenance target", "locale": "en"}},
    ).json()["result"]["concept"]

    completed = None
    for index in range(5):
        completed = client.post(
            f"/v1/concepts/{concept['id']}/turn-runs",
            headers={
                **headers,
                "X-Sift-Provider-Key": "request-only-key",
                "Idempotency-Key": f"maintenance-follow-up-{index}",
            },
            json={"turn": {"question": f"Question {index}?"}},
        )
        assert completed.status_code == 202

    assert completed is not None
    child_ids = completed.json()["childRunIds"]
    assert len(child_ids) == 2
    children = [store.runs[child_id] for child_id in child_ids]
    assert {child["kind"] for child in children} == {
        "continuitySummary",
        "knowledgeReview",
    }
    assert {child["status"] for child in children} == {"succeeded"}
    assert store.continuity_summaries[concept["id"]]["through_turn_count"] == 12

    summary_child = next(
        child for child in children if child["kind"] == "continuitySummary"
    )
    store.runs[summary_child["id"]].update(
        {
            "status": "failed",
            "lease_owner": None,
            "lease_expires_at": None,
            "current_step": "summarize",
            "step_count": 2,
        }
    )
    del store.continuity_summaries[concept["id"]]
    asyncio.run(
        ModelRunService(store)._run_continuity_summary(
            completed.json()["id"],
            session["ownerId"],
            concept["id"],
            12,
            validate_provider_connection(
                session["ownerId"],
                "custom",
                "https://provider.example/v1",
                "test-model",
            ),
            "request-only-key",
            FakeProviderClient,
        )
    )
    assert store.runs[summary_child["id"]]["status"] == "succeeded"
    assert store.continuity_summaries[concept["id"]]["through_turn_count"] == 12

    proposals = client.get(
        f"/v1/concepts/{concept['id']}/proposals?status=proposed",
        headers=headers,
    )
    assert proposals.status_code == 200
    assert proposals.json()[0]["origin"] == "periodicReview"
    assert proposals.json()[0]["sourceRunId"] in child_ids
    refreshed = client.get(f"/v1/concepts/{concept['id']}", headers=headers).json()
    assert refreshed["claims"][0]["type"] == "fact"
    assert (
        refreshed["learningState"]["confirmedUnderstanding"][0]["origin"]
        == "userConfirmed"
    )


def test_proposal_list_merge_retry_and_dismiss_are_revision_safe() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("proposals")
    client = TestClient(
        create_app(
            lambda _request: store,
            provider_client_factory=FakeProviderClient,
        )
    )
    session = activate(client, "proposals", "installation-a")
    headers = auth_headers(session, "installation-a")
    assert client.put(
        "/v1/provider-connection",
        headers=headers,
        json={
            "providerId": "custom",
            "baseURL": "https://provider.example/v1",
            "model": "test-model",
        },
    ).status_code == 200
    concept = client.post(
        "/v1/concept-runs",
        headers={**headers, "X-Sift-Provider-Key": "request-only-key"},
        json={"capture": {"rawCapture": "Proposal target", "locale": "en"}},
    ).json()["result"]["concept"]
    run_headers = {
        **headers,
        "X-Sift-Provider-Key": "request-only-key",
    }

    proposed_run = client.post(
        f"/v1/concepts/{concept['id']}/turn-runs",
        headers={**run_headers, "Idempotency-Key": "proposal-source"},
        json={"turn": {"question": "Save durable detail"}},
    )
    proposal = proposed_run.json()["result"]["response"]["proposal"]
    listed = client.get(
        f"/v1/concepts/{concept['id']}/proposals?status=proposed",
        headers=headers,
    )
    merge_headers = {**headers, "Idempotency-Key": "proposal-merge"}
    merged = client.post(
        f"/v1/update-proposals/{proposal['id']}/merge",
        headers=merge_headers,
        json={},
    )
    merge_retry = client.post(
        f"/v1/update-proposals/{proposal['id']}/merge",
        headers=merge_headers,
        json={},
    )
    accepted = client.get(
        f"/v1/concepts/{concept['id']}/proposals?status=accepted",
        headers=headers,
    )

    assert proposed_run.status_code == 202
    assert proposal["baseNoteRevision"] == 1
    assert proposal["status"] == "proposed"
    assert listed.status_code == 200
    assert listed.json() == [proposal]
    assert merged.status_code == 200
    assert merged.json()["noteRevision"] == 2
    assert merged.json()["blocks"][0]["content"].endswith("\n\ndurable detail")
    assert merged.json()["blocks"][0]["source"] == "merged"
    assert merge_retry.status_code == 200
    assert merge_retry.json() == merged.json()
    assert accepted.status_code == 200
    assert accepted.json()[0]["id"] == proposal["id"]

    second_run = client.post(
        f"/v1/concepts/{concept['id']}/turn-runs",
        headers={**run_headers, "Idempotency-Key": "proposal-to-dismiss"},
        json={"turn": {"question": "Save another detail"}},
    )
    second_proposal = second_run.json()["result"]["response"]["proposal"]
    dismissed = client.post(
        f"/v1/update-proposals/{second_proposal['id']}/dismiss",
        headers=headers,
        json={},
    )
    remaining = client.get(
        f"/v1/concepts/{concept['id']}/proposals?status=proposed",
        headers=headers,
    )
    assert dismissed.status_code == 204
    assert remaining.json() == []


def test_idempotent_retry_returns_same_run_and_rejects_changed_payload() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("invite-three")
    client = TestClient(create_app(lambda _request: store))
    session = activate(client, "invite-three", "installation-a")
    headers = {
        **auth_headers(session, "installation-a"),
        "Idempotency-Key": "capture-operation-2",
    }

    first = client.post(
        "/v1/concept-runs",
        headers=headers,
        json={"capture": {"rawCapture": "first", "locale": "en"}},
    )
    retry = client.post(
        "/v1/concept-runs",
        headers=headers,
        json={"capture": {"rawCapture": "first", "locale": "en"}},
    )
    conflict = client.post(
        "/v1/concept-runs",
        headers=headers,
        json={"capture": {"rawCapture": "changed", "locale": "en"}},
    )

    assert first.status_code == 202
    assert retry.status_code == 202
    assert retry.json()["id"] == first.json()["id"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_payload_conflict"
    assert len(store.runs) == 1


def test_owner_scope_hides_another_owners_run() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("owner-one")
    store.seed_invite("owner-two")
    client = TestClient(create_app(lambda _request: store))
    first_session = activate(client, "owner-one", "installation-a")
    second_session = activate(client, "owner-two", "installation-b")
    created = client.post(
        "/v1/concept-runs",
        headers=auth_headers(first_session, "installation-a"),
        json={"capture": {"rawCapture": "private", "locale": "en"}},
    )

    response = client.get(
        f"/v1/model-runs/{created.json()['id']}",
        headers=auth_headers(second_session, "installation-b"),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "owner_scope_not_found"


def test_expired_token_is_rejected_with_stable_error_code() -> None:
    store = MemoryWorkerStore()
    store.seed_invite("expired")
    client = TestClient(create_app(lambda _request: store))
    session = activate(client, "expired", "installation-a")
    token_hash = hashlib.sha256(session["betaAccessToken"].encode()).hexdigest()
    store.sessions[token_hash]["expires_at"] = (
        datetime.now(UTC) - timedelta(minutes=1)
    ).isoformat()

    response = client.get(
        "/v1/model-runs",
        headers=auth_headers(session, "installation-a"),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "beta_token_expired"
