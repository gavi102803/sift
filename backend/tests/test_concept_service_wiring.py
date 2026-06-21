import pytest
from fastapi import HTTPException

from sift_backend.ai.model_gateway import ConceptModelGatewayError
from sift_backend.api.concepts import build_concept_service
from sift_backend.concepts.service import (
    ConceptService,
    LiteLLMConceptModelService,
    MockConceptModelService,
)
from sift_backend.config import Settings
from sift_backend.schemas.concepts import ConceptDTO, ConceptTurnRequest, CreateConceptRequest


class FailingModelService(MockConceptModelService):
    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
    ):
        raise ConceptModelGatewayError("invalid_schema", "Bad structured output.")


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
