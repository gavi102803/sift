import json
from uuid import uuid4

import pytest

from sift_backend.ai.context_pack import RecentTurn
from sift_backend.ai.litellm_client import (
    LiteLLMClientError,
    LiteLLMCompletionRequest,
    LiteLLMCompletionResponse,
)
from sift_backend.ai.model_gateway import ConceptModelGateway, ConceptModelGatewayError
from sift_backend.schemas.common import (
    AnswerSourceType,
    CaptureStatus,
    ConceptMaturity,
    NoteBlockSource,
    NoteBlockType,
    UpdateMode,
)
from sift_backend.schemas.concepts import ConceptDTO, NoteBlockDTO


class FakeLiteLLMClient:
    def __init__(
        self,
        response: LiteLLMCompletionResponse | None = None,
        error: Exception | None = None,
    ) -> None:
        self.response = response
        self.error = error
        self.requests: list[LiteLLMCompletionRequest] = []

    async def create_chat_completion(
        self,
        request: LiteLLMCompletionRequest,
    ) -> LiteLLMCompletionResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.response is None:
            raise AssertionError("FakeLiteLLMClient requires a response or error.")
        return self.response


def make_concept() -> ConceptDTO:
    return ConceptDTO(
        id=uuid4(),
        canonicalTitle="RAG",
        displayTitle="RAG",
        oneLineExplanation="Retrieval-augmented generation.",
        maturity=ConceptMaturity.growing,
        captureStatus=CaptureStatus.ready,
        noteRevision=2,
        blocks=[
            NoteBlockDTO(
                id=uuid4(),
                blockType=NoteBlockType.what_it_is,
                content="RAG retrieves external context before generation.",
                source=NoteBlockSource.merged,
                isUserLocked=False,
            )
        ],
    )


def valid_payload(block_id: str) -> dict:
    return {
        "answer": "RAG and fine-tuning solve different problems.",
        "answerSource": {
            "sourceType": AnswerSourceType.model_knowledge,
            "confidence": 0.78,
        },
        "updateDecision": {
            "mode": UpdateMode.auto_merge,
            "reason": "Adds a low-risk comparison.",
        },
        "autoPatch": [
            {
                "operation": "append",
                "targetBlockId": block_id,
                "content": "RAG retrieves context at query time.",
            }
        ],
        "relations": [],
        "suggestedTags": [{"name": "AI", "confidence": 0.9}],
        "suggestedTopics": [{"name": "AI Systems", "confidence": 0.82}],
        "memoryPatch": {
            "confirmedUnderstanding": ["RAG is query-time retrieval."],
            "openQuestions": [],
            "userPreferences": ["Use product examples."],
        },
        "modelMeta": {
            "provider": "model-claimed-provider",
            "model": "model-claimed-name",
            "latencyMs": 1,
            "inputTokens": 1,
            "outputTokens": 1,
        },
    }


@pytest.mark.asyncio
async def test_gateway_builds_request_and_validates_structured_output() -> None:
    concept = make_concept()
    client = FakeLiteLLMClient(
        response=LiteLLMCompletionResponse(
            content=json.dumps(valid_payload(str(concept.blocks[0].id))),
            provider="openai",
            model="gpt-4.1-mini",
            input_tokens=420,
            output_tokens=160,
        )
    )
    gateway = ConceptModelGateway(client)

    result = await gateway.answer_concept_turn(
        concept=concept,
        card_memory="User prefers practical examples.",
        recent_turns=[RecentTurn(role="user", content="What is RAG?")],
        user_query="How is RAG different from fine-tuning?",
        model_alias="sift-explain",
    )

    assert result.update_mode == UpdateMode.auto_merge
    assert result.model_meta.provider == "openai"
    assert result.model_meta.model == "gpt-4.1-mini"
    assert result.model_meta.input_tokens == 420
    assert result.model_meta.output_tokens == 160
    assert result.model_meta.latency_ms is not None

    request = client.requests[0]
    assert request.model_alias == "sift-explain"
    assert request.response_format is not None
    assert request.response_format["type"] == "json_schema"
    assert "User prefers practical examples" in request.messages[1].content
    assert request.messages[-1].content == "How is RAG different from fine-tuning?"


@pytest.mark.asyncio
async def test_gateway_rejects_invalid_json() -> None:
    gateway = ConceptModelGateway(
        FakeLiteLLMClient(
            response=LiteLLMCompletionResponse(
                content="not-json",
                provider="openai",
                model="gpt-4.1-mini",
                input_tokens=None,
                output_tokens=None,
            )
        )
    )

    with pytest.raises(ConceptModelGatewayError) as error:
        await gateway.answer_concept_turn(
            concept=make_concept(),
            card_memory="",
            recent_turns=[],
            user_query="Explain RAG.",
        )

    assert error.value.code == "invalid_json"


@pytest.mark.asyncio
async def test_gateway_rejects_schema_mismatch() -> None:
    gateway = ConceptModelGateway(
        FakeLiteLLMClient(
            response=LiteLLMCompletionResponse(
                content=json.dumps({"answer": "Missing required fields."}),
                provider="openai",
                model="gpt-4.1-mini",
                input_tokens=None,
                output_tokens=None,
            )
        )
    )

    with pytest.raises(ConceptModelGatewayError) as error:
        await gateway.answer_concept_turn(
            concept=make_concept(),
            card_memory="",
            recent_turns=[],
            user_query="Explain RAG.",
        )

    assert error.value.code == "invalid_schema"


@pytest.mark.asyncio
async def test_gateway_maps_litellm_failures() -> None:
    gateway = ConceptModelGateway(
        FakeLiteLLMClient(error=LiteLLMClientError("request failed"))
    )

    with pytest.raises(ConceptModelGatewayError) as error:
        await gateway.answer_concept_turn(
            concept=make_concept(),
            card_memory="",
            recent_turns=[],
            user_query="Explain RAG.",
        )

    assert error.value.code == "provider_error"
