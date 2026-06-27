import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from sift_backend.runtime.types import (
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelRequest,
    RuntimeModelResponse,
    RuntimeModelStreamEvent,
    SiftRuntimeError,
)


class ResponsesDriver:
    """Runtime driver for OpenAI Responses-compatible endpoints.

    This driver is intentionally not wired to a visible provider preset yet.
    Deferred providers can map here once they pass conformance and product
    exposure gates.
    """

    provider_name = "responses"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60,
        provider_name: str = "responses",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.provider_name = provider_name

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        data = await self._request("POST", "/responses", json=_responses_payload(request))
        return _parse_responses(data, self.provider_name, request.model)

    async def stream(self, request: RuntimeModelRequest) -> AsyncIterator[RuntimeModelStreamEvent]:
        payload = _responses_payload(request) | {"stream": True}
        chunks: list[str] = []
        completed: RuntimeModelResponse | None = None
        async for data in self._stream_request("/responses", payload):
            delta = _responses_stream_delta(data)
            if delta:
                chunks.append(delta)
                yield RuntimeModelDelta(delta)
            if data.get("type") == "response.completed" and isinstance(data.get("response"), dict):
                completed = _parse_responses(data["response"], self.provider_name, request.model)
        if completed is None:
            completed = RuntimeModelResponse(
                content="".join(chunks),
                provider=self.provider_name,
                model=request.model,
            )
        yield RuntimeModelCompleted(completed)

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/models")
        raw_models = data.get("data")
        if not isinstance(raw_models, list):
            raise SiftRuntimeError("provider_error", "Runtime provider did not return models.")
        return [
            raw_model["id"]
            for raw_model in raw_models
            if isinstance(raw_model, dict) and isinstance(raw_model.get("id"), str)
        ]

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        headers = self._headers()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.request(method, path, headers=headers, **kwargs)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "provider_error",
                    f"Runtime provider returned HTTP {error.response.status_code}: "
                    f"{_error_detail(error.response)}",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("provider_timeout", "Runtime provider timed out.") from error
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                raise SiftRuntimeError(
                    "provider_error",
                    "Runtime provider request failed.",
                ) from error
        if not isinstance(data, dict):
            raise SiftRuntimeError("provider_error", "Runtime provider returned invalid JSON.")
        return data

    async def _stream_request(
        self,
        path: str,
        payload: dict[str, Any],
    ) -> AsyncIterator[dict[str, Any]]:
        headers = self._headers() | {"Accept": "text/event-stream"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                async with client.stream("POST", path, headers=headers, json=payload) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        line = line.strip()
                        if not line or not line.startswith("data:"):
                            continue
                        raw_data = line.removeprefix("data:").strip()
                        if raw_data == "[DONE]":
                            break
                        data = json.loads(raw_data)
                        if isinstance(data, dict):
                            yield data
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "provider_error",
                    f"Runtime provider returned HTTP {error.response.status_code}: "
                    f"{await _async_error_detail(error.response)}",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("provider_timeout", "Runtime provider timed out.") from error
            except (httpx.HTTPError, json.JSONDecodeError) as error:
                raise SiftRuntimeError(
                    "provider_error",
                    "Runtime provider stream failed.",
                ) from error

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers


def _responses_payload(request: RuntimeModelRequest) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": request.model,
        "input": [
            {"role": _responses_role(message.role), "content": message.content}
            for message in request.messages
        ],
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if request.response_format:
        payload["text"] = {"format": request.response_format}
    return payload


def _responses_role(role: str) -> str:
    if role == "assistant":
        return "assistant"
    if role == "system":
        return "system"
    return "user"


def _parse_responses(
    data: dict[str, Any],
    provider: str,
    fallback_model: str,
) -> RuntimeModelResponse:
    content = _responses_text(data)
    if not content:
        raise SiftRuntimeError("provider_error", "Runtime provider returned no content.")
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return RuntimeModelResponse(
        content=content,
        provider=provider,
        model=data.get("model") if isinstance(data.get("model"), str) else fallback_model,
        input_tokens=(
            usage.get("input_tokens") if isinstance(usage.get("input_tokens"), int) else None
        ),
        output_tokens=(
            usage.get("output_tokens") if isinstance(usage.get("output_tokens"), int) else None
        ),
    )


def _responses_text(data: dict[str, Any]) -> str:
    output_text = data.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    raw_output = data.get("output")
    if not isinstance(raw_output, list):
        return ""
    parts: list[str] = []
    for item in raw_output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict):
                continue
            if block.get("type") in {"output_text", "text"} and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts).strip()


def _responses_stream_delta(data: dict[str, Any]) -> str:
    if data.get("type") != "response.output_text.delta":
        return ""
    delta = data.get("delta")
    return delta if isinstance(delta, str) else ""


def _error_detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except json.JSONDecodeError:
        return response.text[:500]
    if isinstance(data, dict):
        detail = data.get("error") or data.get("detail") or data
        return json.dumps(detail, ensure_ascii=False)[:500]
    return str(data)[:500]


async def _async_error_detail(response: httpx.Response) -> str:
    try:
        await response.aread()
    except httpx.HTTPError:
        pass
    return _error_detail(response)
