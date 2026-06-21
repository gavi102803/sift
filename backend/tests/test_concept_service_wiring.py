import json

import pytest
from fastapi import HTTPException

from sift_backend.ai.context_pack import RecentTurn
from sift_backend.ai.litellm_client import LiteLLMCompletionRequest, LiteLLMCompletionResponse
from sift_backend.ai.model_gateway import ConceptModelGateway, ConceptModelGatewayError
from sift_backend.api.concepts import build_concept_service
from sift_backend.concepts.service import (
    ConceptService,
    LiteLLMConceptModelService,
    MockConceptModelService,
)
from sift_backend.config import Settings
from sift_backend.schemas.common import AnswerSourceType, UpdateMode
from sift_backend.schemas.concepts import ConceptDTO, ConceptTurnRequest, CreateConceptRequest


class FailingModelService(MockConceptModelService):
    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ):
        raise ConceptModelGatewayError("invalid_schema", "Bad structured output.")


class RecordingLiteLLMClient:
    def __init__(self, responses: list[LiteLLMCompletionResponse]) -> None:
        self.responses = responses
        self.requests: list[LiteLLMCompletionRequest] = []

    async def create_chat_completion(
        self,
        request: LiteLLMCompletionRequest,
    ) -> LiteLLMCompletionResponse:
        self.requests.append(request)
        return self.responses.pop(0)


def valid_model_content(answer: str) -> str:
    return json.dumps(
        {
            "answer": answer,
            "answerSource": {
                "sourceType": AnswerSourceType.model_knowledge,
                "confidence": 0.8,
            },
            "updateDecision": {
                "mode": UpdateMode.none,
                "reason": "No durable note change needed.",
            },
            "relations": [],
            "suggestedTags": [],
            "suggestedTopics": [],
            "memoryPatch": {
                "confirmedUnderstanding": [],
                "openQuestions": [],
                "userPreferences": [],
            },
            "modelMeta": {"provider": "test", "model": "test-model"},
        }
    )


def test_build_concept_service_uses_mock_when_litellm_key_is_missing() -> None:
    service = build_concept_service(
        Settings(litellm_api_key="", litellm_base_url="http://localhost:4000")
    )

    assert isinstance(service.model_service, MockConceptModelService)


def test_build_concept_service_uses_litellm_when_key_is_present() -> None:
    service = build_concept_service(
        Settings(
            litellm_api_key="test-key",
            litellm_base_url="http://localhost:4000",
            model_explain="sift-explain-test",
        )
    )

    assert isinstance(service.model_service, LiteLLMConceptModelService)
    assert service.model_service.model_alias == "sift-explain-test"


@pytest.mark.asyncio
async def test_submit_turn_maps_model_gateway_error_to_bad_gateway() -> None:
    service = ConceptService(model_service=FailingModelService())
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    with pytest.raises(HTTPException) as error:
        await service.submit_turn(
            concept.id,
            ConceptTurnRequest(question="Explain it again."),
        )

    assert error.value.status_code == 502
    assert error.value.detail["code"] == "invalid_schema"


@pytest.mark.asyncio
async def test_submit_turn_reuses_recent_turns_for_same_concept_card() -> None:
    client = RecordingLiteLLMClient(
        responses=[
            LiteLLMCompletionResponse(
                content=valid_model_content("First answer."),
                provider="test",
                model="test-model",
                input_tokens=None,
                output_tokens=None,
            ),
            LiteLLMCompletionResponse(
                content=valid_model_content("Second answer."),
                provider="test",
                model="test-model",
                input_tokens=None,
                output_tokens=None,
            ),
        ]
    )
    service = ConceptService(
        model_service=LiteLLMConceptModelService(
            gateway=ConceptModelGateway(client),
            model_alias="sift-explain-test",
        )
    )
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    await service.submit_turn(concept.id, ConceptTurnRequest(question="What is RAG?"))
    await service.submit_turn(concept.id, ConceptTurnRequest(question="Give me an example."))

    second_request_contents = [message.content for message in client.requests[1].messages]
    assert "What is RAG?" in second_request_contents
    assert "First answer." in second_request_contents
    assert second_request_contents[-1] == "Give me an example."
