import json

import pytest

from sift_backend.api.concepts import build_concept_service
from sift_backend.concepts.service import InMemoryConceptStore
from sift_backend.config import Settings
from sift_backend.runtime.concept_runtime import LightweightHermesRuntime
from sift_backend.runtime.providers import OpenAICompatibleRuntimeProvider
from sift_backend.runtime.research_stack import SiftReadabilityExtractProvider
from sift_backend.runtime.tools import RuntimeCitation, RuntimeExtractedDocument, TavilyWebProvider
from sift_backend.runtime.types import RuntimeModelRequest, RuntimeModelResponse
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

        user_message = next(
            message["content"]
            for message in reversed(messages)
            if message["role"] == "user"
        )
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

    async def fake_readability_extract(
        self: SiftReadabilityExtractProvider,
        urls: list[str],
    ) -> list[RuntimeExtractedDocument]:
        assert urls == ["https://example.com/a2a"]
        return [
            RuntimeExtractedDocument(
                url="https://example.com/a2a",
                title="A2A Protocol",
                content="A2A is verified extracted source text.",
            )
        ]

    monkeypatch.setattr(OpenAICompatibleRuntimeProvider, "_request", fake_model_request)
    monkeypatch.setattr(TavilyWebProvider, "_request", fake_tavily_request)
    monkeypatch.setattr(SiftReadabilityExtractProvider, "extract", fake_readability_extract)

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
    assert concept.answer_source.source_type == AnswerSourceType.source_verified
    assert concept.answer_source.retrieval_used is True
    assert concept.answer_source.citations[0].url == "https://example.com/a2a"
    assert turn.answer_source.source_type == AnswerSourceType.source_verified
    assert turn.answer_source.retrieval_used is True
    assert turn.answer_source.citations[0].title == "A2A Protocol"


@pytest.mark.asyncio
async def test_runtime_search_only_results_are_not_promoted_to_verified_sources() -> None:
    runtime = LightweightHermesRuntime(
        model_provider=PayloadModelProvider(_initial_concept_payload()),
        model="test-model",
        web_search_tool=SearchOnlyProvider(),
        web_extract_tool=FailingExtractProvider(),
        web_search_enabled=True,
    )

    result = await runtime.generate_initial_concept("What is A2A protocol?", "en")

    assert result.answer_source.source_type == AnswerSourceType.search_discovered
    assert result.answer_source.retrieval_used is True
    assert result.answer_source.citations[0].url == "https://example.com/a2a"


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


class PayloadModelProvider:
    provider_name = "test"

    def __init__(self, payload: str) -> None:
        self.payload = payload

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        return RuntimeModelResponse(
            content=self.payload,
            provider=self.provider_name,
            model=request.model,
        )

    async def stream(self, request: RuntimeModelRequest):
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        return ["test-model"]


class SearchOnlyProvider:
    name = "search-only"
    display_name = "Search Only"

    def is_available(self) -> bool:
        return True

    async def search(self, query: str) -> list[RuntimeCitation]:
        return [
            RuntimeCitation(
                title="A2A Protocol",
                url="https://example.com/a2a",
                snippet="Search snippet only.",
            )
        ]

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        return []


class FailingExtractProvider:
    name = "failing-extract"

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        raise RuntimeError("extract failed")
