from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from sift_worker.agent_core import INITIAL_AGENT_SPEC
from verification.production_e2e import (
    ProductionE2EConfig,
    ProductionE2EFailure,
    run_production_e2e,
)


class FakeProductionClient:
    def __init__(self, *, retrieval_used: bool = True) -> None:
        self.retrieval_used = retrieval_used
        self.requests: list[tuple[str, str, dict[str, str], Any]] = []
        self.submissions = 0
        self.submitted_query = ""
        self.answer = (
            "## What changed\n\nCurrent Workers behavior is documented.\n\n"
            "## Why it matters\n\nCompatibility dates control platform behavior.\n\n"
            "## Practical takeaway\n\nPin and review the date before deployment."
        )
        self.concept = {
            "id": "concept-1",
            "initialAnswer": self.answer,
            "answerSource": {
                "retrievalUsed": retrieval_used,
                "citations": [
                    {
                        "sourceId": "source-1",
                        "title": "Cloudflare Workers docs",
                        "url": "https://developers.cloudflare.com/workers/",
                    }
                ],
            },
            "sources": [
                {
                    "id": "source-1",
                    "title": "Cloudflare Workers docs",
                    "url": "https://developers.cloudflare.com/workers/",
                }
            ],
        }
        self.completed_run = {
            "id": "run-1",
            "kind": "initialConcept",
            "status": "succeeded",
            "conceptId": "concept-1",
            "idempotencyKey": "e2e-key",
            "agentSpec": INITIAL_AGENT_SPEC.name,
            "agentSpecVersion": INITIAL_AGENT_SPEC.version,
            "promptVersion": INITIAL_AGENT_SPEC.prompt_version,
            "toolContractHash": INITIAL_AGENT_SPEC.tool_contract_hash,
            "modelCallCount": 3,
            "toolCallCount": 1,
            "modelLatencyMs": 120,
            "inputTokenCount": 50,
            "outputTokenCount": 25,
            "result": {"concept": self.concept},
        }

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> Any:
        self.requests.append((method, path, headers, body))
        if method == "PUT" and path == "/v1/provider-connection":
            return {
                "providerId": body["providerId"],
                "baseURL": "https://api.deepseek.com/v1",
                "model": body["model"],
            }
        if method == "GET" and path == "/v1/model-runs?active=false":
            return [self.completed_run] if self.submissions else []
        if method == "GET" and path == "/v1/concepts":
            return [self.concept] if self.submissions else []
        if method == "POST" and path == "/v1/concept-runs":
            self.submissions += 1
            self.submitted_query = str(body["capture"]["rawCapture"])
            if self.submissions == 1:
                return {
                    **self.completed_run,
                    "status": "waitingForCredential",
                    "result": None,
                }
            return self.completed_run
        if method == "GET" and path == "/v1/concepts/concept-1/turns":
            return [
                {"role": "user", "content": self.submitted_query},
                {"role": "assistant", "content": self.answer},
            ]
        if method == "GET" and path == "/v1/model-runs/run-1/events":
            return [
                {"sequence": 1, "type": "modelCallStarted", "data": {}},
                {
                    "sequence": 2,
                    "type": "toolStarted",
                    "data": {"tool": "web.search"},
                },
                {
                    "sequence": 3,
                    "type": "toolCompleted",
                    "data": {"tool": "web.search", "resultCount": 1},
                },
                {"sequence": 4, "type": "modelCallCompleted", "data": {}},
                {"sequence": 5, "type": "completed", "data": {}},
            ]
        raise AssertionError(f"Unexpected request: {method} {path}")

    async def stream_ndjson(
        self,
        path: str,
        *,
        headers: dict[str, str],
    ) -> AsyncIterator[dict[str, Any]]:
        self.requests.append(("POST", path, headers, None))
        yield {"type": "progress", "progressLabel": "Researching"}
        midpoint = len(self.answer) // 2
        yield {"type": "delta", "delta": self.answer[:midpoint]}
        yield {"type": "delta", "delta": self.answer[midpoint:]}
        yield {"type": "completed", "modelRun": self.completed_run}


def config() -> ProductionE2EConfig:
    return ProductionE2EConfig(
        base_url="https://sift.example",
        installation_id="installation-e2e",
        session_token="session-secret",
        invite_code=None,
        provider="deepseek",
        provider_base_url=None,
        model="deepseek-chat",
        provider_api_key="provider-secret",
        locale="en",
        query=(
            "Use web search for current Cloudflare Workers compatibility-date guidance, "
            "cite sources, and explain it in three sections."
        ),
        idempotency_key="e2e-key",
    )


@pytest.mark.asyncio
async def test_production_e2e_proves_stream_search_citations_and_idempotency() -> None:
    client = FakeProductionClient()

    artifact = await run_production_e2e(client, config())

    assert artifact == {
        "kind": "sift.productionHarnessE2E",
        "ok": True,
        "provider": "deepseek",
        "model": "deepseek-chat",
        "runId": "run-1",
        "conceptId": "concept-1",
        "streamDeltaCount": 2,
        "modelCallCount": 3,
        "toolCallCount": 1,
        "citationCount": 1,
        "modelLatencyMs": 120,
        "inputTokenCount": 50,
        "outputTokenCount": 25,
    }
    submit_headers = next(
        headers
        for method, path, headers, _ in client.requests
        if method == "POST" and path == "/v1/concept-runs"
    )
    assert "X-Sift-Provider-Key" not in submit_headers
    stream_headers = next(
        headers
        for method, path, headers, _ in client.requests
        if method == "POST" and path.endswith("/resume-stream")
    )
    assert stream_headers["X-Sift-Provider-Key"] == "provider-secret"
    assert "session-secret" not in str(artifact)
    assert "provider-secret" not in str(artifact)


@pytest.mark.asyncio
async def test_production_e2e_rejects_a_card_without_runtime_retrieval() -> None:
    client = FakeProductionClient(retrieval_used=False)

    with pytest.raises(ProductionE2EFailure, match="retrievalUsed"):
        await run_production_e2e(client, config())


@pytest.mark.asyncio
async def test_production_e2e_rejects_an_old_deployed_contract() -> None:
    client = FakeProductionClient()
    client.completed_run["agentSpecVersion"] = "1.3"

    with pytest.raises(ProductionE2EFailure, match="agentSpecVersion"):
        await run_production_e2e(client, config())


@pytest.mark.asyncio
async def test_production_e2e_rejects_terminal_only_streaming() -> None:
    class TerminalOnlyClient(FakeProductionClient):
        async def stream_ndjson(
            self,
            path: str,
            *,
            headers: dict[str, str],
        ) -> AsyncIterator[dict[str, Any]]:
            self.requests.append(("POST", path, headers, None))
            yield {"type": "delta", "delta": self.answer}
            yield {"type": "completed", "modelRun": self.completed_run}

    with pytest.raises(ProductionE2EFailure, match="at least two provider deltas"):
        await run_production_e2e(TerminalOnlyClient(), config())
