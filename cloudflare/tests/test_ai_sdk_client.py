from __future__ import annotations

import json

import pytest

from sift_worker.ai_sdk_client import AiSdkProviderClient
from sift_worker.errors import PublicError
from sift_worker.runtime import validate_provider_connection


class FakeResponse:
    def __init__(self, status: int, payload: dict) -> None:
        self.status = status
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


class FakeStreamReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = iter(chunks)

    async def read(self) -> dict:
        try:
            return {"done": False, "value": next(self.chunks)}
        except StopIteration:
            return {"done": True, "value": None}


class FakeStreamBody:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    def getReader(self) -> FakeStreamReader:
        return FakeStreamReader(self.chunks)


class FakeStreamResponse:
    def __init__(self, chunks: list[bytes], status: int = 200) -> None:
        self.status = status
        self.body = FakeStreamBody(chunks)


@pytest.mark.asyncio
async def test_ai_sdk_adapter_maps_structured_generation_without_secret_in_body() -> None:
    captured: dict = {}

    async def fetcher(url: str, **options):
        captured.update({"url": url, **options})
        return FakeResponse(
            200,
            {
                "content": json.dumps(_initial_result()),
                "model": "sdk-model",
                "input_tokens": 11,
                "output_tokens": 22,
            },
        )

    connection = validate_provider_connection(
        "owner",
        "deepseek",
        None,
        "deepseek-chat",
    )
    completed_calls: list[tuple[int | None, int | None, bool]] = []
    client = AiSdkProviderClient(
        connection,
        "request-only-secret",
        engine_fetcher=fetcher,
        engine_token="engine-test-token-with-enough-entropy",
    )

    async def completed(
        _call_index: int,
        _latency_ms: int,
        input_tokens: int | None,
        output_tokens: int | None,
        succeeded: bool,
    ) -> None:
        completed_calls.append((input_tokens, output_tokens, succeeded))

    client.bind_model_call_completion_observer(completed)
    result = await client.generate_initial_concept("Workers", "en")

    payload = json.loads(captured["body"])
    assert captured["url"].endswith("/internal/v1/generate")
    assert captured["headers"]["X-Sift-Provider"] == "openai-compatible"
    assert captured["headers"]["X-Sift-Provider-Key"] == "request-only-secret"
    assert captured["headers"]["X-Sift-Provider-Base-URL"] == (
        "https://api.deepseek.com/v1"
    )
    assert "request-only-secret" not in captured["body"]
    assert payload["maxOutputTokens"] == 4_096
    assert payload["responseSchema"]["type"] == "object"
    assert result.display_title == "Cloudflare Workers"
    assert result.model_meta.model == "sdk-model"
    assert completed_calls == [(11, 22, True)]


@pytest.mark.asyncio
async def test_ai_sdk_adapter_checkpoints_and_replays_native_tool_context() -> None:
    payloads: list[dict] = []

    async def fetcher(_url: str, **options):
        payloads.append(json.loads(options["body"]))
        if len(payloads) == 1:
            return FakeResponse(
                200,
                {
                    "tool_calls": [
                        {
                            "id": "call-search",
                            "name": "web_search",
                            "arguments": {"query": "Sift runtime"},
                            "provider_context": {
                                "assistantMessages": [
                                    {
                                        "role": "assistant",
                                        "content": [
                                            {
                                                "type": "tool-call",
                                                "toolCallId": "call-search",
                                                "toolName": "web_search",
                                                "input": {"query": "Sift runtime"},
                                            }
                                        ],
                                    }
                                ]
                            },
                        }
                    ],
                    "input_tokens": 7,
                    "output_tokens": 3,
                },
            )
        return FakeResponse(
            200,
            {"tool_calls": [], "input_tokens": 5, "output_tokens": 1},
        )

    client = AiSdkProviderClient(
        validate_provider_connection("owner", "openai", None, "gpt-test"),
        "request-only-secret",
        engine_fetcher=fetcher,
        engine_token="engine-test-token-with-enough-entropy",
    )
    calls = await client.request_initial_tool_calls("Search for Sift runtime", "en")
    assert calls[0].name == "web_search"
    assert calls[0].arguments == {"query": "Sift runtime"}

    await client.request_initial_tool_calls(
        "Search for Sift runtime",
        "en",
        tool_observations=[
            {
                "callId": calls[0].id,
                "tool": "web.search",
                "arguments": calls[0].arguments,
                "result": [{"title": "Sift", "url": "https://example.com/sift"}],
                "providerContext": calls[0].provider_context,
            }
        ],
    )

    assert [tool["providerName"] for tool in payloads[0]["tools"]] == [
        "web_search",
        "web_extract",
    ]
    assert payloads[1]["observations"][0]["providerContext"] == (
        calls[0].provider_context
    )


@pytest.mark.asyncio
async def test_ai_sdk_adapter_relays_one_ndjson_stream_without_retry() -> None:
    fetch_count = 0

    async def fetcher(_url: str, **_options):
        nonlocal fetch_count
        fetch_count += 1
        return FakeStreamResponse(
            [
                b'{"type":"delta","delta":"Streaming "}\n',
                b'{"type":"delta","delta":"answer"}\n',
                (
                    b'{"type":"completed","content":"Streaming answer",'
                    b'"model":"sdk-model","input_tokens":9,"output_tokens":2}\n'
                ),
            ]
        )

    client = AiSdkProviderClient(
        validate_provider_connection("owner", "anthropic", None, "claude-test"),
        "request-only-secret",
        engine_fetcher=fetcher,
        engine_token="engine-test-token-with-enough-entropy",
    )
    deltas: list[str] = []

    async def on_delta(delta: str) -> None:
        deltas.append(delta)

    answer = await client.stream_initial_answer("Explain Sift", "en", [], on_delta)

    assert answer == "Streaming answer"
    assert deltas == ["Streaming ", "answer"]
    assert fetch_count == 1
    assert client.model_call_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("engine_code", "expected_code"),
    [
        ("schema_validation_failed", "schema_validation_failed"),
        ("timeout", "provider_timeout"),
        ("provider_error", "provider_unreachable"),
    ],
)
async def test_ai_sdk_adapter_preserves_safe_engine_error_category(
    engine_code: str,
    expected_code: str,
) -> None:
    async def fetcher(_url: str, **_options):
        return FakeResponse(
            502,
            {"error": {"code": engine_code, "message": "redacted"}},
        )

    client = AiSdkProviderClient(
        validate_provider_connection("owner", "deepseek", None, "deepseek-chat"),
        "request-only-secret",
        engine_fetcher=fetcher,
        engine_token="engine-test-token-with-enough-entropy",
    )

    with pytest.raises(PublicError) as captured:
        await client.generate_initial_concept("Workers", "en")

    assert captured.value.code == expected_code
    assert "redacted" not in captured.value.message


def _initial_result() -> dict:
    return {
        "canonicalTitle": "Workers",
        "displayTitle": "Cloudflare Workers",
        "oneLineExplanation": "An edge compute runtime.",
        "answer": "An edge compute runtime.",
        "blocks": [
            {"blockType": "whatItIs", "content": "An edge compute runtime."},
            {"blockType": "whyItMatters", "content": "It removes server management."},
        ],
        "suggestedTags": [],
        "suggestedTopics": [],
        "answerSource": {
            "sourceType": "modelKnowledge",
            "confidence": 0.8,
            "uncertaintyNote": None,
            "retrievalUsed": False,
            "freshnessNote": None,
            "citations": [],
        },
        "modelMeta": {
            "provider": "ignored",
            "model": "ignored",
            "latencyMs": None,
            "inputTokens": None,
            "outputTokens": None,
        },
    }
