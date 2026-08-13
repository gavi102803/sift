from __future__ import annotations

from types import SimpleNamespace

import pytest

from sift_worker.errors import PublicError
from sift_worker.runtime import RuntimeToolCall, validate_provider_connection
from verification.live_conformance import exercise_provider


class ConformingClient:
    def __init__(self) -> None:
        self.connection = validate_provider_connection(
            "conformance",
            "deepseek",
            None,
            "deepseek-chat",
        )
        self.model_call_count = 0

    async def test(self) -> None:
        self.model_call_count += 2

    async def stream_initial_answer(self, *_args, on_delta, **_kwargs) -> str:
        self.model_call_count += 1
        await on_delta("First ")
        await on_delta("answer")
        return "First answer"

    async def generate_initial_concept(self, *_args, answer: str, **_kwargs):
        self.model_call_count += 1
        return SimpleNamespace(answer=answer)

    async def request_initial_tool_calls(self, *_args, **_kwargs):
        self.model_call_count += 1
        return (
            RuntimeToolCall(
                id="search-1",
                name="web_search",
                arguments={"query": "Cloudflare Workers current release"},
            ),
        )

    async def list_models(self) -> list[str]:
        return ["deepseek-chat"]


@pytest.mark.asyncio
async def test_worker_live_conformance_exercises_production_provider_contract() -> None:
    result = await exercise_provider(ConformingClient())

    assert result == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "plainAndToolProbe": True,
        "streamDeltaCount": 2,
        "streamCharacterCount": 12,
        "structuredCard": True,
        "autonomousToolCall": True,
        "modelListing": True,
        "modelCallCount": 5,
    }


@pytest.mark.asyncio
async def test_worker_live_conformance_rejects_terminal_only_fake_stream() -> None:
    client = ConformingClient()

    async def one_chunk(*_args, on_delta, **_kwargs) -> str:
        await on_delta("Whole answer")
        return "Whole answer"

    client.stream_initial_answer = one_chunk

    with pytest.raises(PublicError) as failure:
        await exercise_provider(client)

    assert failure.value.code == "provider_stream_not_incremental"
