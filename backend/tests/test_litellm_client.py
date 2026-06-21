import json

import httpx
import pytest

from sift_backend.ai.litellm_client import (
    LiteLLMClient,
    LiteLLMClientError,
    LiteLLMCompletionRequest,
    LiteLLMMessage,
)


@pytest.mark.asyncio
async def test_litellm_client_posts_model_alias_and_parses_response() -> None:
    seen_payload: dict[str, object] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen_payload.update(json.loads(request.content.decode("utf-8")))
        return httpx.Response(
            200,
            json={
                "model": "sift-explain",
                "provider": "openai",
                "choices": [{"message": {"content": "{\"answer\":\"ok\"}"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 4},
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://litellm.test") as http:
        client = LiteLLMClient(
            base_url="http://litellm.test",
            api_key="test-key",
            http_client=http,
        )
        response = await client.create_chat_completion(
            LiteLLMCompletionRequest(
                model_alias="sift-explain",
                messages=(LiteLLMMessage(role="user", content="Explain RAG"),),
                response_format={"type": "json_object"},
            )
        )

    assert seen_payload["model"] == "sift-explain"
    assert seen_payload["response_format"] == {"type": "json_object"}
    assert response.content == "{\"answer\":\"ok\"}"
    assert response.provider == "openai"
    assert response.model == "sift-explain"
    assert response.input_tokens == 12
    assert response.output_tokens == 4


@pytest.mark.asyncio
async def test_litellm_client_maps_http_error() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"error": "rate limited"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://litellm.test") as http:
        client = LiteLLMClient(
            base_url="http://litellm.test",
            api_key="test-key",
            http_client=http,
        )

        with pytest.raises(LiteLLMClientError, match="HTTP 429"):
            await client.create_chat_completion(
                LiteLLMCompletionRequest(
                    model_alias="sift-explain",
                    messages=(LiteLLMMessage(role="user", content="Explain RAG"),),
                )
            )


@pytest.mark.asyncio
async def test_litellm_client_rejects_missing_choices() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"model": "sift-explain", "choices": []})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://litellm.test") as http:
        client = LiteLLMClient(
            base_url="http://litellm.test",
            api_key="test-key",
            http_client=http,
        )

        with pytest.raises(LiteLLMClientError, match="choices"):
            await client.create_chat_completion(
                LiteLLMCompletionRequest(
                    model_alias="sift-explain",
                    messages=(LiteLLMMessage(role="user", content="Explain RAG"),),
                )
            )

