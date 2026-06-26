import httpx
import pytest

from sift_backend.runtime.providers import (
    AnthropicMessagesRuntimeProvider,
    OpenAICompatibleRuntimeProvider,
    build_model_provider_registry,
    build_runtime_model_provider,
    normalize_runtime_provider,
    resolve_runtime_base_url,
    resolve_runtime_model,
)
from sift_backend.runtime.types import (
    RuntimeMessage,
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelRequest,
    SiftRuntimeError,
)


@pytest.mark.asyncio
async def test_runtime_provider_posts_chat_completion_and_parses_response() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["authorization"] = request.headers.get("authorization")
        captured["payload"] = json_payload(request)
        return httpx.Response(
            200,
            json={
                "model": "runtime-model",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 2},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://runtime.test/v1") as http:
        provider = OpenAICompatibleRuntimeProvider(
            base_url="https://runtime.test/v1",
            api_key="runtime-key",
        )
        provider._request = _request_with_client(http, provider)  # type: ignore[method-assign]

        response = await provider.complete(
            RuntimeModelRequest(
                model="sift-model",
                messages=(RuntimeMessage(role="user", content="Explain RAG"),),
                response_format={"type": "json_object"},
            )
        )

    assert captured["path"] == "/v1/chat/completions"
    assert captured["authorization"] == "Bearer runtime-key"
    assert captured["payload"]["model"] == "sift-model"
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    assert response.content == "ok"
    assert response.model == "runtime-model"
    assert response.input_tokens == 7
    assert response.output_tokens == 2


@pytest.mark.asyncio
async def test_runtime_provider_maps_http_errors() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": {"message": "rate limited"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://runtime.test/v1") as http:
        provider = OpenAICompatibleRuntimeProvider(
            base_url="https://runtime.test/v1",
            api_key="runtime-key",
        )
        provider._request = _request_with_client(http, provider)  # type: ignore[method-assign]

        with pytest.raises(SiftRuntimeError, match="HTTP 429"):
            await provider.complete(
                RuntimeModelRequest(
                    model="sift-model",
                    messages=(RuntimeMessage(role="user", content="Explain RAG"),),
                )
            )


@pytest.mark.asyncio
async def test_anthropic_messages_provider_posts_messages_and_parses_response() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["path"] = request.url.path
        captured["api_key"] = request.headers.get("x-api-key")
        captured["version"] = request.headers.get("anthropic-version")
        captured["payload"] = json_payload(request)
        return httpx.Response(
            200,
            json={
                "model": "claude-runtime",
                "content": [{"type": "text", "text": "ok"}],
                "usage": {"input_tokens": 11, "output_tokens": 3},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://runtime.test") as http:
        provider = AnthropicMessagesRuntimeProvider(
            base_url="https://runtime.test",
            api_key="anthropic-key",
        )
        provider._request = _request_with_anthropic_client(http, provider)  # type: ignore[method-assign]

        response = await provider.complete(
            RuntimeModelRequest(
                model="claude-test",
                messages=(
                    RuntimeMessage(role="system", content="Be exact."),
                    RuntimeMessage(role="user", content="Explain RAG"),
                ),
                response_format={"type": "json_object"},
            )
        )

    assert captured["path"] == "/v1/messages"
    assert captured["api_key"] == "anthropic-key"
    assert captured["version"] == "2023-06-01"
    assert captured["payload"]["system"].endswith(
        "Return only valid JSON matching the requested schema."
    )
    assert captured["payload"]["messages"] == [{"role": "user", "content": "Explain RAG"}]
    assert response.content == "ok"
    assert response.model == "claude-runtime"
    assert response.input_tokens == 11
    assert response.output_tokens == 3


@pytest.mark.asyncio
async def test_runtime_provider_streams_deltas_and_completion() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=(
                'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n'
                "data: [DONE]\n\n"
            ),
            headers={"content-type": "text/event-stream"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://runtime.test/v1") as http:
        provider = OpenAICompatibleRuntimeProvider(
            base_url="https://runtime.test/v1",
            api_key="runtime-key",
        )
        provider._stream_request = _stream_with_client(http, provider)  # type: ignore[method-assign]

        events = [
            event
            async for event in provider.stream(
                RuntimeModelRequest(
                    model="sift-model",
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


def json_payload(request: httpx.Request) -> dict:
    import json

    return json.loads(request.content.decode("utf-8"))


def _request_with_client(http: httpx.AsyncClient, provider: OpenAICompatibleRuntimeProvider):
    async def request(method: str, path: str, **kwargs):
        headers = provider._headers()
        try:
            response = await http.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            from sift_backend.runtime.providers import _error_detail

            raise SiftRuntimeError(
                "provider_error",
                f"Runtime provider returned HTTP {error.response.status_code}: "
                f"{_error_detail(error.response)}",
            ) from error

    return request


def _request_with_anthropic_client(
    http: httpx.AsyncClient,
    provider: AnthropicMessagesRuntimeProvider,
):
    async def request(method: str, path: str, **kwargs):
        headers = provider._headers()
        try:
            response = await http.request(method, path, headers=headers, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPStatusError as error:
            from sift_backend.runtime.providers import _error_detail

            raise SiftRuntimeError(
                "provider_error",
                f"Runtime provider returned HTTP {error.response.status_code}: "
                f"{_error_detail(error.response)}",
            ) from error

    return request


def _stream_with_client(http: httpx.AsyncClient, provider: OpenAICompatibleRuntimeProvider):
    async def stream(path: str, payload: dict):
        import json

        headers = provider._headers() | {"Accept": "text/event-stream"}
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


def test_model_provider_registry_normalizes_legacy_aliases() -> None:
    assert normalize_runtime_provider("sift_runtime") == "custom"
    assert normalize_runtime_provider("hermes_lite") == "custom"
    assert normalize_runtime_provider("openai_compatible") == "custom"
    assert normalize_runtime_provider("openai_responses") == "openai"


def test_model_provider_registry_resolves_known_provider_defaults() -> None:
    assert resolve_runtime_base_url("deepseek", "") == "https://api.deepseek.com/v1"
    assert resolve_runtime_model("deepseek", "") == "deepseek-chat"
    assert resolve_runtime_base_url("openrouter", "") == "https://openrouter.ai/api/v1"


def test_model_provider_registry_creates_openai_compatible_provider() -> None:
    provider = build_runtime_model_provider(
        "deepseek",
        base_url="",
        api_key="deepseek-key",
    )

    assert isinstance(provider, OpenAICompatibleRuntimeProvider)
    assert provider.provider_name == "deepseek"
    assert provider.base_url == "https://api.deepseek.com/v1"


def test_model_provider_registry_creates_anthropic_messages_provider() -> None:
    provider = build_runtime_model_provider(
        "anthropic",
        base_url="",
        api_key="anthropic-key",
    )

    assert isinstance(provider, AnthropicMessagesRuntimeProvider)
    assert provider.provider_name == "anthropic"
    assert provider.base_url == "https://api.anthropic.com"


def test_model_provider_registry_lists_canonical_profiles() -> None:
    registry = build_model_provider_registry()

    names = set(registry.names())

    assert {"custom", "deepseek", "kimi", "mock", "nous", "openai", "openrouter"}.issubset(names)
    assert {"anthropic", "gemini", "minimax", "zai"}.issubset(names)
    assert {"bedrock", "xai", "qwen-oauth"}.isdisjoint(names)
    assert registry.profile("deepseek").status == "available"
    assert registry.profile("anthropic").status == "available"
    assert registry.profile("minimax").adapter == "anthropic_messages"
    assert registry.profile("gemini").adapter == "openai_compatible"
