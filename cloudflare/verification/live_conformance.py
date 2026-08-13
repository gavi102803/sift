"""Out-of-bundle live conformance for production provider adapters."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from sift_worker.errors import PublicError
from sift_worker.runtime import (
    WorkerProviderClient,
    provider_supports_tools,
    validate_provider_connection,
)

_LIVE_QUERY = "Explain durable agent execution with three short sections."
_LIVE_TOOL_QUERY = (
    "Use web search to find the current Cloudflare Workers release and cite sources."
)


async def exercise_provider(client: Any) -> dict[str, Any]:
    """Exercise the production Worker provider adapter without persisting credentials."""

    await client.test()

    deltas: list[str] = []

    async def collect(delta: str) -> None:
        if delta:
            deltas.append(delta)

    answer = await client.stream_initial_answer(
        _LIVE_QUERY,
        "en",
        [],
        on_delta=collect,
    )
    if len(deltas) < 2 or "".join(deltas).strip() != answer.strip():
        raise PublicError(
            "provider_stream_not_incremental",
            "The provider did not produce a verifiable incremental text stream.",
            502,
        )

    card = await client.generate_initial_concept(
        _LIVE_QUERY,
        "en",
        answer=answer,
        retrieval_evidence=[],
    )
    if card.answer.strip() != answer.strip():
        raise PublicError(
            "provider_structured_contract_failed",
            "The provider did not preserve the streamed answer in the card contract.",
            502,
        )

    supports_tools = provider_supports_tools(client.connection.provider_id)
    autonomous_tool_call = False
    if supports_tools:
        calls = await client.request_initial_tool_calls(_LIVE_TOOL_QUERY, "en")
        autonomous_tool_call = any(
            call.name in {"web_search", "web.search"}
            and isinstance(call.arguments.get("query"), str)
            and call.arguments["query"].strip()
            for call in calls
        )
        if not autonomous_tool_call:
            raise PublicError(
                "provider_capability_missing",
                "The model did not autonomously call Sift's web search tool.",
                409,
            )

    models = await client.list_models()
    return {
        "provider": client.connection.provider_id,
        "model": client.connection.model,
        "plainAndToolProbe": True,
        "streamDeltaCount": len(deltas),
        "streamCharacterCount": len(answer),
        "structuredCard": True,
        "autonomousToolCall": autonomous_tool_call,
        "modelListing": bool(models),
        "modelCallCount": client.model_call_count,
    }


class _HTTPXReader:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.iterator = response.aiter_bytes().__aiter__()
        self.closed = False

    async def read(self) -> dict[str, Any]:
        if self.closed:
            return {"done": True, "value": None}
        try:
            return {"done": False, "value": await self.iterator.__anext__()}
        except StopAsyncIteration:
            self.closed = True
            await self.response.aclose()
            return {"done": True, "value": None}

    async def cancel(self) -> None:
        if not self.closed:
            self.closed = True
            await self.response.aclose()


class _HTTPXBody:
    def __init__(self, response: Any) -> None:
        self.response = response

    def getReader(self) -> _HTTPXReader:
        return _HTTPXReader(self.response)


class _HTTPXResponse:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.status = response.status_code
        self.body = _HTTPXBody(response)

    async def json(self) -> dict[str, Any]:
        try:
            await self.response.aread()
            value = self.response.json()
            return value if isinstance(value, dict) else {}
        finally:
            await self.response.aclose()

    async def text(self) -> str:
        try:
            await self.response.aread()
            return self.response.text
        finally:
            await self.response.aclose()


async def run_from_environment() -> dict[str, Any]:
    try:
        import httpx
    except ImportError as error:
        raise RuntimeError("Live conformance requires httpx.") from error

    provider = os.environ.get("SIFT_LIVE_PROVIDER", "deepseek").strip().lower()
    api_key = os.environ.get("SIFT_LIVE_API_KEY", "").strip()
    if not api_key:
        raise PublicError(
            "live_credential_missing",
            "SIFT_LIVE_API_KEY is required for live conformance.",
            422,
        )
    connection = validate_provider_connection(
        "live-conformance",
        provider,
        os.environ.get("SIFT_LIVE_BASE_URL", "").strip() or None,
        os.environ.get("SIFT_LIVE_MODEL", "").strip(),
    )

    async with httpx.AsyncClient(timeout=60) as http:
        async def fetcher(url: str, **kwargs: Any) -> _HTTPXResponse:
            request = http.build_request(
                kwargs.get("method", "GET"),
                url,
                headers=kwargs.get("headers"),
                content=kwargs.get("body"),
            )
            response = await http.send(request, stream=True)
            return _HTTPXResponse(response)

        client = WorkerProviderClient(connection, api_key, fetcher=fetcher)
        return await exercise_provider(client)


def main() -> int:
    output_path = Path(
        os.environ.get("SIFT_LIVE_CONFORMANCE_OUTPUT", ".data/live-conformance.json")
    )
    try:
        result = asyncio.run(run_from_environment())
        artifact = {"kind": "sift.workerProviderConformance", "ok": True, **result}
        exit_code = 0
    except PublicError as error:
        artifact = {
            "kind": "sift.workerProviderConformance",
            "ok": False,
            "errorCode": error.code,
            "errorMessage": error.message,
        }
        exit_code = 2 if error.code == "live_credential_missing" else 1
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(json.dumps(artifact, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
