import json

import httpx
import pytest

from sift_backend.runtime.gemini_driver import GeminiDriver
from sift_backend.runtime.providers import ModelProviderRegistry, RuntimeModelProviderProfile
from sift_backend.runtime.types import (
    RuntimeMessage,
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelRequest,
)


@pytest.mark.asyncio
async def test_gemini_driver_posts_native_generate_content_payload() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["api_key"] = request.headers.get("x-goog-api-key")
        captured["payload"] = json_payload(request)
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {"content": {"parts": [{"text": '{"answer":"ok"}'}]}}
                ],
                "usageMetadata": {"promptTokenCount": 8, "candidatesTokenCount": 3},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://generativelanguage.googleapis.com/v1beta",
    ) as http:
        driver = GeminiDriver(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="gemini-key",
        )
        driver._request = _request_with_client(http, driver)  # type: ignore[method-assign]

        response = await driver.complete(
            RuntimeModelRequest(
                model="gemini-test",
                messages=(
                    RuntimeMessage(role="system", content="Be exact."),
                    RuntimeMessage(role="user", content="Reply JSON."),
                ),
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "answer",
                        "schema": {
                            "type": "object",
                            "properties": {"answer": {"type": "string"}},
                            "required": ["answer"],
                        },
                    },
                },
                temperature=0.2,
            )
        )

    assert captured["path"] == "/v1beta/models/gemini-test:generateContent"
    assert captured["api_key"] == "gemini-key"
    assert captured["payload"]["systemInstruction"] == {
        "parts": [{"text": "Be exact."}]
    }
    assert captured["payload"]["contents"] == [
        {"role": "user", "parts": [{"text": "Reply JSON."}]}
    ]
    assert captured["payload"]["generationConfig"]["temperature"] == 0.2
    assert captured["payload"]["generationConfig"]["responseMimeType"] == "application/json"
    assert captured["payload"]["generationConfig"]["responseSchema"]["required"] == ["answer"]
    assert response.content == '{"answer":"ok"}'
    assert response.provider == "gemini"
    assert response.input_tokens == 8
    assert response.output_tokens == 3


@pytest.mark.asyncio
async def test_gemini_driver_streams_sse_deltas_and_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                'data: {"candidates":[{"content":{"parts":[{"text":"Hel"}]}}]}\n\n'
                'data: {"candidates":[{"content":{"parts":[{"text":"lo"}]}}]}\n\n'
            ),
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://generativelanguage.googleapis.com/v1beta",
    ) as http:
        driver = GeminiDriver(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="",
        )
        driver._stream_request = _stream_with_client(http, driver)  # type: ignore[method-assign]

        events = [
            event
            async for event in driver.stream(
                RuntimeModelRequest(
                    model="models/gemini-test",
                    messages=(RuntimeMessage(role="user", content="Hello"),),
                )
            )
        ]

    assert [event.content for event in events if isinstance(event, RuntimeModelDelta)] == [
        "Hel",
        "lo",
    ]
    completed = [event for event in events if isinstance(event, RuntimeModelCompleted)]
    assert len(completed) == 1
    assert completed[0].response.content == "Hello"


@pytest.mark.asyncio
async def test_gemini_driver_lists_generate_content_models() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "name": "models/gemini-flash",
                        "supportedGenerationMethods": ["generateContent"],
                    },
                    {
                        "name": "models/embedding-test",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://generativelanguage.googleapis.com/v1beta",
    ) as http:
        driver = GeminiDriver(
            base_url="https://generativelanguage.googleapis.com/v1beta",
            api_key="",
        )
        driver._request = _request_with_client(http, driver)  # type: ignore[method-assign]

        models = await driver.list_models()

    assert models == ["gemini-flash"]


def test_registry_creates_native_gemini_driver() -> None:
    registry = ModelProviderRegistry()
    registry.register(
        RuntimeModelProviderProfile(
            name="gemini",
            display_name="Gemini",
            adapter="gemini",
            default_base_url="https://generativelanguage.googleapis.com/v1beta",
            default_model="gemini-test",
            api_mode="gemini",
            protocol_driver="GeminiDriver",
        )
    )

    provider = registry.create_provider("gemini", base_url="", api_key="gemini-key")

    assert isinstance(provider, GeminiDriver)
    assert provider.base_url == "https://generativelanguage.googleapis.com/v1beta"


def json_payload(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


def _request_with_client(http: httpx.AsyncClient, driver: GeminiDriver):
    async def request(method: str, path: str, **kwargs):
        headers = driver._headers()
        response = await http.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        data = response.json()
        assert isinstance(data, dict)
        return data

    return request


def _stream_with_client(http: httpx.AsyncClient, driver: GeminiDriver):
    async def stream(path: str, payload: dict):
        headers = driver._headers() | {"Accept": "text/event-stream"}
        response = await http.post(path, headers=headers, json=payload)
        response.raise_for_status()
        for line in response.text.splitlines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            data = json.loads(line.removeprefix("data:").strip())
            if isinstance(data, dict):
                yield data

    return stream
