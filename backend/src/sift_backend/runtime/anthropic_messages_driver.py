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


class AnthropicMessagesDriver:
    """Runtime driver for Anthropic-compatible Messages endpoints."""

    provider_name = "anthropic"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60,
        provider_name: str = "anthropic",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.provider_name = provider_name

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        data = await self._request("POST", "/v1/messages", json=_anthropic_payload(request))
        return _parse_anthropic_message(data, self.provider_name, request.model)

    async def stream(self, request: RuntimeModelRequest) -> AsyncIterator[RuntimeModelStreamEvent]:
        payload = _anthropic_payload(request) | {"stream": True}
        chunks: list[str] = []
        async for data in self._stream_request("/v1/messages", payload):
            delta = _anthropic_stream_delta(data)
            if delta:
                chunks.append(delta)
                yield RuntimeModelDelta(delta)
        yield RuntimeModelCompleted(
            RuntimeModelResponse(
                content="".join(chunks),
                provider=self.provider_name,
                model=request.model,
            )
        )

    async def list_models(self) -> list[str]:
        data = await self._request("GET", "/v1/models")
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
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": "2023-06-01",
        }
        if self.api_key:
            headers["x-api-key"] = self.api_key
        return headers


def _anthropic_payload(request: RuntimeModelRequest) -> dict[str, Any]:
    messages: list[dict[str, str]] = []
    system_parts: list[str] = []
    for message in request.messages:
        if message.role == "system":
            system_parts.append(message.content)
            continue
        role = "assistant" if message.role == "assistant" else "user"
        messages.append({"role": role, "content": message.content})

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
        "max_tokens": 4096,
    }
    if request.temperature is not None:
        payload["temperature"] = request.temperature
    if system_parts:
        payload["system"] = "\n\n".join(system_parts)
    if request.response_format:
        payload["system"] = (
            (payload.get("system", "") + "\n\n") if payload.get("system") else ""
        ) + "Return only valid JSON matching the requested schema."
    return payload


def _parse_anthropic_message(
    data: dict[str, Any],
    provider: str,
    fallback_model: str,
) -> RuntimeModelResponse:
    raw_content = data.get("content")
    if not isinstance(raw_content, list):
        raise SiftRuntimeError("provider_error", "Runtime provider returned no content.")
    text_parts: list[str] = []
    for block in raw_content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            text_parts.append(block["text"])
    content = "\n".join(text_parts).strip()
    if not content:
        raise SiftRuntimeError("provider_error", "Runtime provider returned no text content.")
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


def _anthropic_stream_delta(data: dict[str, Any]) -> str:
    if data.get("type") != "content_block_delta":
        return ""
    delta = data.get("delta")
    if not isinstance(delta, dict):
        return ""
    text = delta.get("text")
    return text if isinstance(text, str) else ""


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
