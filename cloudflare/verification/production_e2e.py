"""Out-of-bundle production verification for the Worker Harness."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse
from uuid import uuid4

from sift_worker.agent_core import INITIAL_AGENT_SPEC

_DEFAULT_QUERY = (
    "Use web search for current official Cloudflare Workers compatibility-date "
    "guidance, cite sources, and explain it in three useful Markdown sections."
)


class ProductionE2EFailure(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductionE2EConfig:
    base_url: str
    installation_id: str
    session_token: str | None
    invite_code: str | None
    provider: str
    provider_base_url: str | None
    model: str
    provider_api_key: str
    locale: str
    query: str
    idempotency_key: str

    @classmethod
    def from_environment(cls) -> ProductionE2EConfig:
        base_url = _required_env("SIFT_E2E_BASE_URL").rstrip("/")
        parsed = urlparse(base_url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ProductionE2EFailure(
                "SIFT_E2E_BASE_URL must be an HTTPS URL without credentials."
            )
        session_token = os.environ.get("SIFT_E2E_SESSION_TOKEN", "").strip() or None
        invite_code = os.environ.get("SIFT_E2E_INVITE_CODE", "").strip() or None
        if bool(session_token) == bool(invite_code):
            raise ProductionE2EFailure(
                "Set exactly one of SIFT_E2E_SESSION_TOKEN or SIFT_E2E_INVITE_CODE."
            )
        return cls(
            base_url=base_url,
            installation_id=_required_env("SIFT_E2E_INSTALLATION_ID"),
            session_token=session_token,
            invite_code=invite_code,
            provider=os.environ.get("SIFT_E2E_PROVIDER", "deepseek").strip().lower(),
            provider_base_url=(
                os.environ.get("SIFT_E2E_PROVIDER_BASE_URL", "").strip() or None
            ),
            model=os.environ.get("SIFT_E2E_MODEL", "deepseek-chat").strip(),
            provider_api_key=_required_env("SIFT_E2E_PROVIDER_API_KEY"),
            locale=os.environ.get("SIFT_E2E_LOCALE", "en").strip() or "en",
            query=os.environ.get("SIFT_E2E_QUERY", "").strip() or _DEFAULT_QUERY,
            idempotency_key=(
                os.environ.get("SIFT_E2E_IDEMPOTENCY_KEY", "").strip()
                or str(uuid4())
            ),
        )


class ProductionClient(Protocol):
    async def request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> Any:
        ...

    def stream_ndjson(
        self,
        path: str,
        *,
        headers: dict[str, str],
    ) -> AsyncIterator[dict[str, Any]]:
        ...


async def run_production_e2e(
    client: ProductionClient,
    config: ProductionE2EConfig,
) -> dict[str, Any]:
    token = config.session_token
    if token is None:
        activation = await client.request_json(
            "POST",
            "/v1/beta/activate",
            headers={},
            body={
                "inviteCode": config.invite_code,
                "installationId": config.installation_id,
            },
        )
        token = _required_string(activation, "betaAccessToken")

    auth_headers = {
        "Authorization": f"Bearer {token}",
        "X-Sift-Installation": config.installation_id,
    }
    await client.request_json(
        "PUT",
        "/v1/provider-connection",
        headers=auth_headers,
        body={
            "providerId": config.provider,
            "baseURL": config.provider_base_url,
            "model": config.model,
        },
    )
    before_runs = _required_list(
        await client.request_json(
            "GET",
            "/v1/model-runs?active=false",
            headers=auth_headers,
        ),
        "model-runs",
    )
    before_concepts = _required_list(
        await client.request_json("GET", "/v1/concepts", headers=auth_headers),
        "concepts",
    )
    capture_body = {
        "capture": {"rawCapture": config.query, "locale": config.locale},
        "clientDraftId": str(uuid4()),
    }
    submit_headers = {
        **auth_headers,
        "Idempotency-Key": config.idempotency_key,
    }
    submitted = await client.request_json(
        "POST",
        "/v1/concept-runs",
        headers=submit_headers,
        body=capture_body,
    )
    run_id = _required_string(submitted, "id")
    if submitted.get("status") not in {"queued", "waitingForCredential", "running"}:
        raise ProductionE2EFailure(
            "The initial durable run did not enter a resumable pre-terminal state."
        )
    if submitted.get("idempotencyKey") != config.idempotency_key:
        raise ProductionE2EFailure("The submitted run changed its idempotency key.")

    stream_headers = {
        **auth_headers,
        "Accept": "application/x-ndjson",
        "X-Sift-Provider-Key": config.provider_api_key,
    }
    answer_parts: list[str] = []
    delta_count = 0
    completed: dict[str, Any] | None = None
    async for event in client.stream_ndjson(
        f"/v1/model-runs/{run_id}/resume-stream",
        headers=stream_headers,
    ):
        event_type = event.get("type")
        if event_type == "reset":
            answer_parts.clear()
            delta_count = 0
        elif event_type == "delta":
            delta = event.get("delta")
            if isinstance(delta, str) and delta:
                answer_parts.append(delta)
                delta_count += 1
        elif event_type == "completed":
            model_run = event.get("modelRun")
            if isinstance(model_run, dict):
                completed = model_run
        elif event_type in {"failed", "cancelled", "detached"}:
            code = event.get("errorCode") or event_type
            raise ProductionE2EFailure(f"The streamed run terminated as {code}.")

    if completed is None or completed.get("status") != "succeeded":
        raise ProductionE2EFailure("The stream ended without a succeeded ModelRun.")
    if completed.get("id") != run_id:
        raise ProductionE2EFailure("The terminal stream event changed the ModelRun id.")
    if delta_count < 2:
        raise ProductionE2EFailure(
            "The production stream did not expose at least two provider deltas."
        )
    _assert_current_agent_contract(completed)

    result = completed.get("result")
    concept = result.get("concept") if isinstance(result, dict) else None
    if not isinstance(concept, dict):
        raise ProductionE2EFailure("The completed run returned no concept card.")
    concept_id = _required_string(concept, "id")
    streamed_answer = "".join(answer_parts).strip()
    initial_answer = str(concept.get("initialAnswer") or "").strip()
    if not streamed_answer or streamed_answer != initial_answer:
        raise ProductionE2EFailure(
            "The visible streamed answer does not equal the persisted card answer."
        )
    if len(initial_answer) < 120 or _markdown_section_count(initial_answer) < 3:
        raise ProductionE2EFailure(
            "The initial answer did not satisfy the card-level three-section contract."
        )
    citation_count = _assert_retrieval_and_citations(concept)

    replayed = await client.request_json(
        "POST",
        "/v1/concept-runs",
        headers=submit_headers,
        body=capture_body,
    )
    if replayed.get("id") != run_id or replayed.get("status") != "succeeded":
        raise ProductionE2EFailure(
            "Idempotent replay did not return the same succeeded ModelRun."
        )
    after_runs = _required_list(
        await client.request_json(
            "GET",
            "/v1/model-runs?active=false",
            headers=auth_headers,
        ),
        "model-runs",
    )
    matching_runs = [
        run for run in after_runs if run.get("idempotencyKey") == config.idempotency_key
    ]
    if len(after_runs) != len(before_runs) + 1 or [run.get("id") for run in matching_runs] != [
        run_id
    ]:
        raise ProductionE2EFailure("One query did not produce exactly one durable run.")
    after_concepts = _required_list(
        await client.request_json("GET", "/v1/concepts", headers=auth_headers),
        "concepts",
    )
    matching_concepts = [item for item in after_concepts if item.get("id") == concept_id]
    if len(after_concepts) != len(before_concepts) + 1 or len(matching_concepts) != 1:
        raise ProductionE2EFailure("One query did not produce exactly one concept card.")
    turns = _required_list(
        await client.request_json(
            "GET",
            f"/v1/concepts/{concept_id}/turns",
            headers=auth_headers,
        ),
        "turns",
    )
    if [turn.get("role") for turn in turns] != ["user", "assistant"]:
        raise ProductionE2EFailure("The concept did not contain exactly one turn pair.")
    if turns[0].get("content") != config.query or turns[1].get("content") != initial_answer:
        raise ProductionE2EFailure("The durable turn pair differs from the query and answer.")
    events = _required_list(
        await client.request_json(
            "GET",
            f"/v1/model-runs/{run_id}/events",
            headers=auth_headers,
        ),
        "events",
    )
    _assert_runtime_events(events)

    return {
        "kind": "sift.productionHarnessE2E",
        "ok": True,
        "provider": config.provider,
        "model": config.model,
        "runId": run_id,
        "conceptId": concept_id,
        "streamDeltaCount": delta_count,
        "modelCallCount": int(completed.get("modelCallCount") or 0),
        "toolCallCount": int(completed.get("toolCallCount") or 0),
        "citationCount": citation_count,
        "modelLatencyMs": int(completed.get("modelLatencyMs") or 0),
        "inputTokenCount": int(completed.get("inputTokenCount") or 0),
        "outputTokenCount": int(completed.get("outputTokenCount") or 0),
    }


class HTTPXProductionClient:
    def __init__(self, base_url: str, http: Any) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = http

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        body: dict[str, Any] | None = None,
    ) -> Any:
        response = await self.http.request(
            method,
            f"{self.base_url}{path}",
            headers={"Accept": "application/json", **headers},
            json=body,
        )
        payload = _json_response(response)
        if not response.is_success:
            raise _http_failure(path, response.status_code, payload)
        return payload

    async def stream_ndjson(
        self,
        path: str,
        *,
        headers: dict[str, str],
    ) -> AsyncIterator[dict[str, Any]]:
        async with self.http.stream(
            "POST",
            f"{self.base_url}{path}",
            headers=headers,
        ) as response:
            if not response.is_success:
                raw = await response.aread()
                try:
                    payload = json.loads(raw)
                except (TypeError, ValueError):
                    payload = {}
                raise _http_failure(path, response.status_code, payload)
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except ValueError as error:
                    raise ProductionE2EFailure(
                        "The production stream returned invalid NDJSON."
                    ) from error
                if not isinstance(event, dict):
                    raise ProductionE2EFailure(
                        "The production stream returned a non-object event."
                    )
                yield event


def _assert_current_agent_contract(run: dict[str, Any]) -> None:
    expected = {
        "agentSpec": INITIAL_AGENT_SPEC.name,
        "agentSpecVersion": INITIAL_AGENT_SPEC.version,
        "promptVersion": INITIAL_AGENT_SPEC.prompt_version,
        "toolContractHash": INITIAL_AGENT_SPEC.tool_contract_hash,
    }
    for key, value in expected.items():
        if run.get(key) != value:
            raise ProductionE2EFailure(
                f"The production run does not use the current {key} contract."
            )
    if int(run.get("modelCallCount") or 0) < 3:
        raise ProductionE2EFailure("The production run recorded too few model calls.")
    if int(run.get("toolCallCount") or 0) < 1:
        raise ProductionE2EFailure("The production run recorded no tool call.")
    if int(run.get("modelLatencyMs") or 0) <= 0:
        raise ProductionE2EFailure("The production run recorded no model latency.")
    for field in ("inputTokenCount", "outputTokenCount"):
        if not isinstance(run.get(field), int) or int(run[field]) < 0:
            raise ProductionE2EFailure(f"The production run has invalid {field}.")


def _assert_retrieval_and_citations(concept: dict[str, Any]) -> int:
    answer_source = concept.get("answerSource")
    if not isinstance(answer_source, dict) or answer_source.get("retrievalUsed") is not True:
        raise ProductionE2EFailure("The completed card did not set retrievalUsed=true.")
    citations = answer_source.get("citations")
    sources = concept.get("sources")
    if not isinstance(citations, list) or not citations:
        raise ProductionE2EFailure("The completed card returned no citations.")
    if not isinstance(sources, list) or not sources:
        raise ProductionE2EFailure("The completed card persisted no sources.")
    source_pairs = {
        (source.get("id"), source.get("url"))
        for source in sources
        if isinstance(source, dict)
    }
    if any(
        not isinstance(citation, dict)
        or (citation.get("sourceId"), citation.get("url")) not in source_pairs
        for citation in citations
    ):
        raise ProductionE2EFailure(
            "A citation does not map to a source persisted by the runtime."
        )
    return len(citations)


def _assert_runtime_events(events: list[dict[str, Any]]) -> None:
    types = [event.get("type") for event in events]
    for required in ("modelCallStarted", "modelCallCompleted", "toolCompleted", "completed"):
        if required not in types:
            raise ProductionE2EFailure(f"The run event trace is missing {required}.")
    if not any(
        event.get("type") == "toolStarted"
        and isinstance(event.get("data"), dict)
        and event["data"].get("tool") == "web.search"
        for event in events
    ):
        raise ProductionE2EFailure("The run trace contains no web.search tool call.")


def _markdown_section_count(answer: str) -> int:
    return sum(
        1
        for line in answer.splitlines()
        if re.match(r"^#{1,6}\s+\S", line.strip())
        or re.match(r"^\*\*[^*]+\*\*$", line.strip())
    )


def _required_list(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ProductionE2EFailure(f"The production {label} response is invalid.")
    return value


def _required_string(value: Any, key: str) -> str:
    field = value.get(key) if isinstance(value, dict) else None
    if not isinstance(field, str) or not field.strip():
        raise ProductionE2EFailure(f"The production response has no {key}.")
    return field


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ProductionE2EFailure(f"{name} is required.")
    return value


def _json_response(response: Any) -> Any:
    try:
        return response.json()
    except ValueError as error:
        raise ProductionE2EFailure("The production API returned invalid JSON.") from error


def _http_failure(path: str, status: int, payload: Any) -> ProductionE2EFailure:
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else "unknown_error"
    return ProductionE2EFailure(f"{path} failed with HTTP {status} ({code}).")


async def run_from_environment() -> dict[str, Any]:
    try:
        import httpx
    except ImportError as error:
        raise ProductionE2EFailure("Production E2E requires httpx.") from error
    config = ProductionE2EConfig.from_environment()
    async with httpx.AsyncClient(timeout=150) as http:
        try:
            return await run_production_e2e(
                HTTPXProductionClient(config.base_url, http),
                config,
            )
        except httpx.HTTPError as error:
            raise ProductionE2EFailure(
                "The production Worker could not be reached."
            ) from error


def main() -> int:
    output_path = Path(
        os.environ.get(
            "SIFT_E2E_OUTPUT",
            ".data/production-e2e.json",
        )
    )
    try:
        artifact = asyncio.run(run_from_environment())
        exit_code = 0
    except ProductionE2EFailure as error:
        artifact = {
            "kind": "sift.productionHarnessE2E",
            "ok": False,
            "error": str(error),
        }
        exit_code = 2
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
