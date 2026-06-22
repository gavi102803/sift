from uuid import UUID

from fastapi import APIRouter, Request, status

from sift_backend.ai.litellm_client import LiteLLMClient
from sift_backend.ai.model_gateway import ConceptModelGateway
from sift_backend.concepts.service import ConceptService, LiteLLMConceptModelService
from sift_backend.config import Settings, load_settings
from sift_backend.schemas.concepts import (
    ConceptDTO,
    ConceptHistoryTurnDTO,
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


def get_concept_service(request: Request) -> ConceptService:
    service = getattr(request.app.state, "concept_service", None)
    if service is None:
        service = build_concept_service()
        request.app.state.concept_service = service
    return service


@router.get("/concepts", response_model=list[ConceptDTO], response_model_by_alias=True)
async def list_concepts(request: Request) -> list[ConceptDTO]:
    return get_concept_service(request).list_concepts()


@router.post("/concepts", response_model=ConceptDTO, response_model_by_alias=True)
async def create_concept(request: Request, payload: CreateConceptRequest) -> ConceptDTO:
    return get_concept_service(request).create_concept(payload)


@router.get("/concepts/{concept_id}", response_model=ConceptDTO, response_model_by_alias=True)
async def get_concept(request: Request, concept_id: UUID) -> ConceptDTO:
    return get_concept_service(request).get_concept(concept_id)


@router.get(
    "/concepts/{concept_id}/turns",
    response_model=list[ConceptHistoryTurnDTO],
    response_model_by_alias=True,
)
async def list_concept_turns(request: Request, concept_id: UUID) -> list[ConceptHistoryTurnDTO]:
    return get_concept_service(request).list_turns(concept_id)


@router.post(
    "/concepts/{concept_id}/turns",
    response_model=ConceptTurnResponse,
    response_model_by_alias=True,
)
async def submit_concept_turn(
    request: Request,
    concept_id: UUID,
    payload: ConceptTurnRequest,
) -> ConceptTurnResponse:
    return await get_concept_service(request).submit_turn(concept_id, payload)


@router.post(
    "/update-proposals/{proposal_id}/merge",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def merge_update_proposal(request: Request, proposal_id: UUID) -> ConceptDTO:
    return get_concept_service(request).merge_proposal(proposal_id)


@router.post("/update-proposals/{proposal_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_update_proposal(request: Request, proposal_id: UUID) -> None:
    get_concept_service(request).dismiss_proposal(proposal_id)
