import json
from collections.abc import AsyncIterator
from typing import Any
from urllib.parse import quote

import httpx

from sift_backend.runtime.types import (
    RuntimeMessage,
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelRequest,
    RuntimeModelResponse,
    RuntimeModelStreamEvent,
    SiftRuntimeError,
)


class GeminiDriver:
    """Runtime driver for the native Google Gemini API."""

    provider_name = "gemini"

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout: float = 60,
        provider_name: str = "gemini",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.provider_name = provider_name

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        data = await self._request(
            "POST",
            _model_action_path(request.model, "generateContent"),
            json=_gemini_payload(request),
        )
        return _parse_gemini_response(data, self.provider_name, request.model)

    async def stream(self, request: RuntimeModelRequest) -> AsyncIterator[RuntimeModelStreamEvent]:
        chunks: list[str] = []
        async for data in self._stream_request(
            _model_action_path(request.model, "streamGenerateContent") + "?alt=sse",
            _gemini_payload(request),
        ):
            delta = _gemini_text(data)
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
        data = await self._request("GET", "/models")
        raw_models = data.get("models")
        if not isinstance(raw_models, list):
            raise SiftRuntimeError("provider_error", "Runtime provider did not return models.")
        models: list[str] = []
        for raw_model in raw_models:
            if not isinstance(raw_model, dict):
                continue
            name = raw_model.get("name")
            supported = raw_model.get("supportedGenerationMethods")
            if not isinstance(name, str):
                continue
            if isinstance(supported, list) and "generateContent" not in supported:
                continue
            models.append(name.removeprefix("models/"))
        return models

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
            headers["x-goog-api-key"] = self.api_key
        return headers


def _model_action_path(model: str, action: str) -> str:
    normalized = model.removeprefix("models/")
    return f"/models/{quote(normalized, safe='')}:{action}"


def _gemini_payload(request: RuntimeModelRequest) -> dict[str, Any]:
    system_texts: list[str] = []
    contents: list[dict[str, Any]] = []
    for message in request.messages:
        if message.role == "system":
            system_texts.append(message.content)
            continue
        contents.append(_gemini_content(message))

    payload: dict[str, Any] = {
        "contents": contents,
    }
    if system_texts:
        payload["systemInstruction"] = {
            "parts": [{"text": "\n\n".join(system_texts)}],
        }
    generation_config = _generation_config(request)
    if generation_config:
        payload["generationConfig"] = generation_config
    return payload


def _gemini_content(message: RuntimeMessage) -> dict[str, Any]:
    role = "model" if message.role == "assistant" else "user"
    return {"role": role, "parts": [{"text": message.content}]}


def _generation_config(request: RuntimeModelRequest) -> dict[str, Any]:
    config: dict[str, Any] = {}
    if request.temperature is not None:
        config["temperature"] = request.temperature
    if not request.response_format:
        return config

    response_type = request.response_format.get("type")
    if response_type in {"json_schema", "json_object"}:
        config["responseMimeType"] = "application/json"
    if response_type == "json_schema":
        json_schema = request.response_format.get("json_schema")
        if isinstance(json_schema, dict) and isinstance(json_schema.get("schema"), dict):
            config["responseSchema"] = json_schema["schema"]
    return config


def _parse_gemini_response(
    data: dict[str, Any],
    provider: str,
    fallback_model: str,
) -> RuntimeModelResponse:
    content = _gemini_text(data)
    if not content:
        raise SiftRuntimeError("provider_error", "Runtime provider returned no content.")
    usage = data.get("usageMetadata") if isinstance(data.get("usageMetadata"), dict) else {}
    return RuntimeModelResponse(
        content=content,
        provider=provider,
        model=fallback_model,
        input_tokens=(
            usage.get("promptTokenCount")
            if isinstance(usage.get("promptTokenCount"), int)
            else None
        ),
        output_tokens=(
            usage.get("candidatesTokenCount")
            if isinstance(usage.get("candidatesTokenCount"), int)
            else None
        ),
    )


def _gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    texts = [
        part["text"]
        for part in parts
        if isinstance(part, dict) and isinstance(part.get("text"), str)
    ]
    return "".join(texts).strip()


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
