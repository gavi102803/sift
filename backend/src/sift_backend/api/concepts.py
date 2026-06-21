from uuid import UUID

from fastapi import APIRouter, status

from sift_backend.ai.litellm_client import LiteLLMClient
from sift_backend.ai.model_gateway import ConceptModelGateway
from sift_backend.concepts.service import ConceptService, LiteLLMConceptModelService
from sift_backend.config import Settings, load_settings
from sift_backend.schemas.concepts import (
    ConceptDTO,
    ConceptTurnRequest,
    ConceptTurnResponse,
    CreateConceptRequest,
)

router = APIRouter(prefix="/v1", tags=["concepts"])


def build_concept_service(settings: Settings | None = None) -> ConceptService:
    resolved = settings or load_settings()
    if not resolved.litellm_api_key:
        return ConceptService()

    client = LiteLLMClient(
        base_url=resolved.litellm_base_url,
        api_key=resolved.litellm_api_key,
    )
    return ConceptService(
        model_service=LiteLLMConceptModelService(
            gateway=ConceptModelGateway(client),
            model_alias=resolved.model_explain,
        )
    )


service = build_concept_service()


@router.post("/concepts", response_model=ConceptDTO, response_model_by_alias=True)
async def create_concept(request: CreateConceptRequest) -> ConceptDTO:
    return service.create_concept(request)


@router.post(
    "/concepts/{concept_id}/turns",
    response_model=ConceptTurnResponse,
    response_model_by_alias=True,
)
async def submit_concept_turn(
    concept_id: UUID,
    request: ConceptTurnRequest,
) -> ConceptTurnResponse:
    return await service.submit_turn(concept_id, request)


@router.post(
    "/update-proposals/{proposal_id}/merge",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def merge_update_proposal(proposal_id: UUID) -> ConceptDTO:
    return service.merge_proposal(proposal_id)


@router.post("/update-proposals/{proposal_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_update_proposal(proposal_id: UUID) -> None:
    service.dismiss_proposal(proposal_id)
