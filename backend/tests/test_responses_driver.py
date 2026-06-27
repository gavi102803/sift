import json

import httpx
import pytest

from sift_backend.runtime.providers import ModelProviderRegistry, RuntimeModelProviderProfile
from sift_backend.runtime.responses_driver import ResponsesDriver
from sift_backend.runtime.types import (
    RuntimeMessage,
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelRequest,
)


@pytest.mark.asyncio
async def test_responses_driver_posts_request_and_parses_output_text() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json_payload(request)
        return httpx.Response(
            200,
            json={
                "model": "gpt-responses",
                "output_text": "ok",
                "usage": {"input_tokens": 5, "output_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://runtime.test/v1") as http:
        driver = ResponsesDriver(
            base_url="https://runtime.test/v1",
            api_key="runtime-key",
            provider_name="openai-responses",
        )
        driver._request = _request_with_client(http, driver)  # type: ignore[method-assign]

        response = await driver.complete(
            RuntimeModelRequest(
                model="gpt-responses",
                messages=(
                    RuntimeMessage(role="system", content="Be exact."),
                    RuntimeMessage(role="user", content="Reply ok."),
                ),
                response_format={"type": "json_object"},
            )
        )

    assert captured["path"] == "/v1/responses"
    assert captured["authorization"] == "Bearer runtime-key"
    assert captured["payload"]["model"] == "gpt-responses"
    assert captured["payload"]["input"] == [
        {"role": "system", "content": "Be exact."},
        {"role": "user", "content": "Reply ok."},
    ]
    assert captured["payload"]["text"] == {"format": {"type": "json_object"}}
    assert response.content == "ok"
    assert response.provider == "openai-responses"
    assert response.input_tokens == 5
    assert response.output_tokens == 2


@pytest.mark.asyncio
async def test_responses_driver_parses_output_content_blocks() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "model": "gpt-responses",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": "hello"},
                            {"type": "output_text", "text": "world"},
                        ],
                    }
                ],
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://runtime.test/v1") as http:
        driver = ResponsesDriver(base_url="https://runtime.test/v1", api_key="")
        driver._request = _request_with_client(http, driver)  # type: ignore[method-assign]

        response = await driver.complete(
            RuntimeModelRequest(
                model="gpt-responses",
                messages=(RuntimeMessage(role="user", content="Say hello."),),
            )
        )

    assert response.content == "hello\nworld"


@pytest.mark.asyncio
async def test_responses_driver_streams_text_deltas_and_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                'data: {"type":"response.output_text.delta","delta":"Hel"}\n\n'
                'data: {"type":"response.output_text.delta","delta":"lo"}\n\n'
                'data: {"type":"response.completed","response":{"model":"gpt-responses",'
                '"output_text":"Hello"}}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://runtime.test/v1") as http:
        driver = ResponsesDriver(base_url="https://runtime.test/v1", api_key="")
        driver._stream_request = _stream_with_client(http, driver)  # type: ignore[method-assign]

        events = [
            event
            async for event in driver.stream(
                RuntimeModelRequest(
                    model="gpt-responses",
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


def test_model_provider_registry_can_create_responses_driver_without_profile_exposure() -> None:
    registry = ModelProviderRegistry()
    registry.register(
        RuntimeModelProviderProfile(
            name="responses-test",
            display_name="Responses Test",
            adapter="responses",
            default_base_url="https://runtime.test/v1",
            default_model="gpt-responses",
            api_mode="codex_responses",
            protocol_driver="ResponsesDriver",
            exposure_tier="hidden",
        )
    )

    provider = registry.create_provider(
        "responses-test",
        base_url="",
        api_key="runtime-key",
    )

    assert isinstance(provider, ResponsesDriver)
    assert provider.provider_name == "responses-test"
    assert provider.base_url == "https://runtime.test/v1"


def json_payload(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8"))


def _request_with_client(http: httpx.AsyncClient, driver: ResponsesDriver):
    async def request(method: str, path: str, **kwargs):
        headers = driver._headers()
        response = await http.request(method, path, headers=headers, **kwargs)
        response.raise_for_status()
        data = response.json()
        assert isinstance(data, dict)
        return data

    return request


def _stream_with_client(http: httpx.AsyncClient, driver: ResponsesDriver):
    async def stream(path: str, payload: dict):
        headers = driver._headers() | {"Accept": "text/event-stream"}
        response = await http.post(path, headers=headers, json=payload)
        response.raise_for_status()
        for line in response.text.splitlines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            raw_data = line.removeprefix("data:").strip()
            if raw_data == "[DONE]":
                break
            data = json.loads(raw_data)
            if isinstance(data, dict):
                yield data

    return stream
