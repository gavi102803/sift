import json

import pytest

from sift_backend.api.concepts import build_concept_service
from sift_backend.concepts.service import InMemoryConceptStore
from sift_backend.config import Settings
from sift_backend.runtime.providers import OpenAICompatibleRuntimeProvider
from sift_backend.runtime.tools import TavilyWebProvider
from sift_backend.schemas.common import AnswerSourceType
from sift_backend.schemas.concepts import ConceptTurnRequest, CreateConceptRequest


@pytest.mark.asyncio
async def test_runtime_service_uses_provider_profile_tool_dispatch_and_web_retrieval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_model_requests: list[dict] = []
    captured_search_payloads: list[dict] = []

    async def fake_model_request(
        self: OpenAICompatibleRuntimeProvider,
        method: str,
        path: str,
        **kwargs,
    ) -> dict:
        assert self.provider_name == "deepseek"
        assert self.base_url == "https://api.deepseek.com/v1"
        assert path == "/chat/completions"
        payload = kwargs["json"]
        captured_model_requests.append(payload)
        messages = payload["messages"]
        assert any("Runtime retrieval results" in message["content"] for message in messages)

        user_message = messages[-1]["content"]
        if "Create a Sift concept card" in user_message:
            content = _initial_concept_payload()
        else:
            content = _turn_payload()
        return {
            "model": payload["model"],
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 8},
        }

    async def fake_tavily_request(
        self: TavilyWebProvider,
        path: str,
        payload: dict,
    ) -> dict:
        assert self.api_key == "tavily-key"
        assert path == "/search"
        captured_search_payloads.append(payload)
        return {
            "results": [
                {
                    "title": "A2A Protocol",
                    "url": "https://example.com/a2a",
                    "content": "A2A is a protocol for agent-to-agent communication.",
                }
            ]
        }

    monkeypatch.setattr(OpenAICompatibleRuntimeProvider, "_request", fake_model_request)
    monkeypatch.setattr(TavilyWebProvider, "_request", fake_tavily_request)

    service = build_concept_service(
        Settings(
            runtime_provider="deepseek",
            runtime_api_key="runtime-key",
            runtime_model="",
            runtime_web_search_enabled=True,
            web_search_provider="tavily",
            web_search_api_key="tavily-key",
        ),
        store=InMemoryConceptStore(),
    )

    concept = await service.create_concept_async(
        CreateConceptRequest(rawCapture="What is A2A protocol?", locale="en")
    )
    turn = await service.submit_turn(
        concept.id,
        ConceptTurnRequest(question="How does A2A differ from MCP?"),
    )

    assert len(captured_model_requests) == 2
    assert [request["model"] for request in captured_model_requests] == [
        "deepseek-chat",
        "deepseek-chat",
    ]
    assert [payload["query"] for payload in captured_search_payloads] == [
        "What is A2A protocol?",
        "How does A2A differ from MCP?",
    ]
    assert concept.answer_source is not None
    assert concept.answer_source.source_type == AnswerSourceType.web_verified
    assert concept.answer_source.retrieval_used is True
    assert concept.answer_source.citations[0].url == "https://example.com/a2a"
    assert turn.answer_source.source_type == AnswerSourceType.web_verified
    assert turn.answer_source.retrieval_used is True
    assert turn.answer_source.citations[0].title == "A2A Protocol"


def _initial_concept_payload() -> str:
    return json.dumps(
        {
            "canonicalTitle": "A2A Protocol",
            "displayTitle": "A2A Protocol",
            "oneLineExplanation": "A2A coordinates communication between agents.",
            "blocks": [
                {
                    "blockType": "whatItIs",
                    "content": "A2A is an agent-to-agent communication protocol.",
                },
                {
                    "blockType": "whyItMatters",
                    "content": "It helps independent agents exchange requests and results.",
                },
            ],
            "suggestedTags": [{"name": "Agents", "confidence": 0.9}],
            "suggestedTopics": [{"name": "Protocols", "confidence": 0.8}],
            "answerSource": {
                "sourceType": "modelKnowledge",
                "confidence": 0.7,
                "retrievalUsed": False,
                "citations": [],
            },
            "modelMeta": {
                "provider": "test",
                "model": "test-model",
                "latencyMs": None,
                "inputTokens": None,
                "outputTokens": None,
            },
        }
    )


def _turn_payload() -> str:
    return json.dumps(
        {
            "answer": "A2A is for agent-to-agent exchange; MCP exposes tools and data.",
            "answerSource": {
                "sourceType": "modelKnowledge",
                "confidence": 0.7,
                "retrievalUsed": False,
                "citations": [],
            },
            "updateDecision": {
                "mode": "none",
                "reason": "No durable note update is needed.",
            },
            "autoPatch": [],
            "proposal": None,
            "relations": [],
            "suggestedTags": [],
            "suggestedTopics": [],
            "memoryPatch": {
                "confirmedUnderstanding": [],
                "openQuestions": [],
                "userPreferences": [],
            },
            "modelMeta": {
                "provider": "test",
                "model": "test-model",
                "latencyMs": None,
                "inputTokens": None,
                "outputTokens": None,
            },
        }
    )
