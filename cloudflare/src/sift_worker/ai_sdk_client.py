from __future__ import annotations

import json
from codecs import getincrementaldecoder
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

from sift_worker.agent_core import MAX_MODEL_OUTPUT_TOKENS
from sift_worker.errors import PublicError
from sift_worker.runtime import (
    PROVIDER_PROFILES,
    ProviderConnection,
    RuntimeToolCall,
    TextDeltaSink,
    WorkerProviderClient,
    _provider_payload_error,
    _response_json,
    _stream_bytes,
    _stream_result_value,
)
from sift_worker.tool_contracts import WEB_TOOL_CONTRACTS, tool_contract

EngineFetch = Callable[..., Awaitable[Any]]

_INTERNAL_BASE_URL = "https://sift-ai-sdk-engine.internal"
_MAX_ENGINE_REQUEST_BYTES = 1_048_576
_MAX_STREAM_ANSWER_CHARS = 8_000
_TOOL_DECISION_MAX_OUTPUT_TOKENS = 512
_ANSWER_MAX_OUTPUT_TOKENS = 2_048


class AiSdkProviderClient(WorkerProviderClient):
    """Sift runtime adapter for the upstream Vercel AI SDK engine Worker."""

    def __init__(
        self,
        connection: ProviderConnection,
        api_key: str,
        *,
        engine_fetcher: EngineFetch | None = None,
        provider_fetcher: EngineFetch | None = None,
        engine_token: str | None = None,
    ) -> None:
        super().__init__(connection, api_key, fetcher=provider_fetcher)
        self.engine_fetcher = engine_fetcher or _binding_fetch
        self.engine_token = engine_token

    async def _complete(
        self,
        messages: tuple[dict[str, str], ...],
        *,
        response_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        async def complete() -> dict[str, Any]:
            payload: dict[str, Any] = {
                "messages": list(messages),
                "maxOutputTokens": (
                    MAX_MODEL_OUTPUT_TOKENS
                    if response_schema is not None
                    else _ANSWER_MAX_OUTPUT_TOKENS
                ),
            }
            if response_schema is not None:
                payload["responseSchema"] = response_schema
            data = await self._request_json("/internal/v1/generate", payload)
            content = data.get("content")
            if not isinstance(content, str) or not content.strip():
                raise _provider_payload_error()
            return {
                "content": content,
                "model": _optional_string(data.get("model")) or self.connection.model,
                "input_tokens": _optional_int(data.get("input_tokens")),
                "output_tokens": _optional_int(data.get("output_tokens")),
            }

        return await self._run_model_call(complete)

    async def _request_tool_calls(
        self,
        messages: tuple[dict[str, str], ...],
        *,
        forced_tool_name: str | None = None,
        tool_observations: list[dict[str, Any]] | None = None,
    ) -> tuple[RuntimeToolCall, ...]:
        profile = PROVIDER_PROFILES[self.connection.provider_id]
        if not profile.supports_tool_calling:
            return ()

        async def request_calls() -> dict[str, Any]:
            observations = []
            for observation in (tool_observations or [])[-4:]:
                try:
                    contract = tool_contract(str(observation.get("tool") or ""))
                except ValueError:
                    continue
                call_id = str(observation.get("callId") or "").strip()
                if not call_id:
                    continue
                raw_arguments = observation.get("arguments")
                item: dict[str, Any] = {
                    "callId": call_id,
                    "providerName": contract.provider_name,
                    "arguments": raw_arguments if isinstance(raw_arguments, dict) else {},
                    "result": observation.get("result"),
                }
                provider_context = observation.get("providerContext")
                if isinstance(provider_context, dict):
                    item["providerContext"] = provider_context
                observations.append(item)

            payload: dict[str, Any] = {
                "messages": list(messages),
                "maxOutputTokens": _TOOL_DECISION_MAX_OUTPUT_TOKENS,
                "tools": [
                    {
                        "providerName": contract.provider_name,
                        "description": contract.description,
                        "inputSchema": contract.input_schema,
                    }
                    for contract in WEB_TOOL_CONTRACTS
                ],
                "observations": observations,
            }
            if forced_tool_name is not None:
                payload["forcedToolName"] = tool_contract(
                    forced_tool_name
                ).provider_name
            return await self._request_json("/internal/v1/tool-calls", payload)

        result = await self._run_model_call(request_calls)
        raw_calls = result.get("tool_calls")
        calls: list[RuntimeToolCall] = []
        for raw_call in raw_calls if isinstance(raw_calls, list) else []:
            if not isinstance(raw_call, dict):
                continue
            call_id = _optional_string(raw_call.get("id"))
            name = _optional_string(raw_call.get("name"))
            arguments = raw_call.get("arguments")
            if call_id is None or name is None or not isinstance(arguments, dict):
                continue
            provider_context = raw_call.get("provider_context")
            calls.append(
                RuntimeToolCall(
                    id=call_id,
                    name=name,
                    arguments=arguments,
                    provider_context=(
                        provider_context if isinstance(provider_context, dict) else None
                    ),
                )
            )
        return tuple(calls)

    async def _stream_complete(
        self,
        messages: tuple[dict[str, str], ...],
        on_delta: TextDeltaSink,
    ) -> str:
        async def stream() -> dict[str, Any]:
            response = await self._fetch(
                "/internal/v1/stream",
                {
                    "messages": list(messages),
                    "maxOutputTokens": _ANSWER_MAX_OUTPUT_TOKENS,
                },
            )
            _raise_for_internal_status(response)
            chunks: list[str] = []
            completed: dict[str, Any] | None = None
            answer_chars = 0
            async for event in _iter_ndjson(response):
                event_type = event.get("type")
                if event_type == "delta":
                    delta = event.get("delta")
                    if not isinstance(delta, str) or not delta:
                        raise _provider_payload_error()
                    answer_chars += len(delta)
                    if answer_chars > _MAX_STREAM_ANSWER_CHARS:
                        raise _provider_payload_error()
                    chunks.append(delta)
                    await on_delta(delta)
                elif event_type == "completed":
                    if completed is not None:
                        raise _provider_payload_error()
                    completed = event
                elif event_type == "error":
                    _raise_for_engine_code(event.get("code"))
                else:
                    raise _provider_payload_error()

            content = "".join(chunks)
            if completed is None or completed.get("content") != content:
                raise _provider_payload_error()
            answer = content.strip()
            if not answer:
                raise _provider_payload_error()
            return {
                "content": answer,
                "model": _optional_string(completed.get("model"))
                or self.connection.model,
                "input_tokens": _optional_int(completed.get("input_tokens")),
                "output_tokens": _optional_int(completed.get("output_tokens")),
            }

        result = await self._run_model_call(stream)
        return str(result["content"])

    async def _request_json(
        self,
        pathname: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        response = await self._fetch(pathname, payload)
        await _raise_for_internal_json_status(response)
        return await _response_json(response)

    async def _fetch(self, pathname: str, payload: dict[str, Any]) -> Any:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(body.encode()) > _MAX_ENGINE_REQUEST_BYTES:
            raise _provider_payload_error()
        headers = {
            "Content-Type": "application/json",
            "X-Sift-Engine-Token": self.engine_token or _engine_token(),
            "X-Sift-Provider": _engine_provider(self.connection.provider_id),
            "X-Sift-Model": self.connection.model,
            "X-Sift-Provider-Key": self.api_key,
        }
        base_url = _engine_base_url(self.connection)
        if base_url is not None:
            headers["X-Sift-Provider-Base-URL"] = base_url
        return await self.engine_fetcher(
            f"{_INTERNAL_BASE_URL}{pathname}",
            method="POST",
            headers=headers,
            body=body,
        )


def configured_provider_client_factory(
    connection: ProviderConnection,
    api_key: str,
) -> WorkerProviderClient:
    from workers import env

    if str(getattr(env, "SIFT_MODEL_ENGINE", "legacy")).strip().lower() == "ai-sdk":
        return AiSdkProviderClient(connection, api_key)
    return WorkerProviderClient(connection, api_key)


async def _binding_fetch(url: str, **options: Any) -> Any:
    from js import AbortSignal
    from workers import Request, env

    options.setdefault("signal", AbortSignal.timeout(45_000))
    return await env.AI_SDK_ENGINE.fetch(Request(url, **options))


def _engine_token() -> str:
    from workers import env

    token = str(getattr(env, "SIFT_ENGINE_TOKEN", ""))
    if len(token) < 24:
        raise PublicError(
            "provider_unreachable",
            "The AI provider runtime is not configured.",
            503,
        )
    return token


def _engine_provider(provider_id: str) -> str:
    profile = PROVIDER_PROFILES[provider_id]
    if profile.adapter == "anthropic":
        return "anthropic"
    if profile.adapter == "gemini":
        return "google"
    if provider_id == "openai":
        return "openai"
    return "openai-compatible"


def _engine_base_url(connection: ProviderConnection) -> str | None:
    profile = PROVIDER_PROFILES[connection.provider_id]
    if _engine_provider(connection.provider_id) == "openai-compatible":
        return connection.base_url
    if connection.base_url != profile.default_base_url:
        return connection.base_url
    return None


def _raise_for_internal_status(response: Any) -> None:
    status = int(response.status)
    if 200 <= status < 300:
        return
    if status in {401, 403}:
        raise PublicError("invalid_provider_key", "Check your provider API key.", 401)
    if status in {402, 429}:
        raise PublicError(
            "provider_quota_exhausted",
            "Your provider quota is used up.",
            status,
        )
    raise PublicError(
        "provider_unreachable",
        "The AI provider could not be reached.",
        502,
    )


async def _raise_for_internal_json_status(response: Any) -> None:
    if 200 <= int(response.status) < 300:
        return
    code = ""
    try:
        data = await response.json()
        converted = data.to_py() if hasattr(data, "to_py") else data
        if isinstance(converted, dict):
            error = converted.get("error")
            if isinstance(error, dict):
                code = str(error.get("code") or "")
    except Exception:
        pass
    _raise_for_engine_code(code, status=int(response.status))


def _raise_for_engine_code(raw_code: Any, *, status: int | None = None) -> None:
    code = str(raw_code or "")
    if code == "invalid_provider_key" or status in {401, 403}:
        raise PublicError("invalid_provider_key", "Check your provider API key.", 401)
    if code == "provider_quota_exhausted" or status in {402, 429}:
        raise PublicError(
            "provider_quota_exhausted",
            "Your provider quota is used up.",
            status if status in {402, 429} else 429,
        )
    if code == "cancelled":
        raise PublicError("agent_cancelled", "The model run was cancelled.", 409)
    if code == "timeout":
        raise PublicError(
            "provider_timeout",
            "The AI provider timed out while building the card.",
            504,
        )
    if code == "schema_validation_failed":
        raise PublicError(
            "schema_validation_failed",
            "The AI provider returned an invalid structured card.",
            502,
        )
    raise PublicError(
        "provider_unreachable",
        "The AI provider could not be reached.",
        502,
    )


async def _iter_ndjson(response: Any) -> AsyncIterator[dict[str, Any]]:
    body = getattr(response, "body", None)
    if body is None:
        raise _provider_payload_error()
    reader = body.getReader()
    decoder = getincrementaldecoder("utf-8")()
    buffer = ""
    while True:
        result = await reader.read()
        done = bool(_stream_result_value(result, "done"))
        value = _stream_result_value(result, "value")
        if value is not None:
            buffer += decoder.decode(_stream_bytes(value), final=False)
        if done:
            buffer += decoder.decode(b"", final=True)
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            if line.strip():
                yield _parse_ndjson_line(line)
        if done:
            if buffer.strip():
                yield _parse_ndjson_line(buffer)
            return


def _parse_ndjson_line(line: str) -> dict[str, Any]:
    try:
        event = json.loads(line)
    except ValueError as error:
        raise _provider_payload_error() from error
    if not isinstance(event, dict):
        raise _provider_payload_error()
    return event


def _optional_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
