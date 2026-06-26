from uuid import UUID

from fastapi import APIRouter, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from sift_backend.concepts.service import (
    ConceptService,
    ConceptTurnStreamDelta,
    ConceptTurnStreamResult,
    InMemoryConceptStore,
    SiftRuntimeConceptModelService,
)
from sift_backend.config import Settings, load_settings
from sift_backend.persistence.concept_store import PersistentConceptStore
from sift_backend.persistence.database import create_session_factory
from sift_backend.runtime.concept_runtime import LightweightHermesRuntime
from sift_backend.runtime.providers import build_runtime_model_provider, resolve_runtime_model
from sift_backend.runtime.tools import RuntimeWebProvider, build_web_provider_registry
from sift_backend.schemas.concepts import (
    ConceptDTO,
    ConceptHistoryTurnDTO,
    ConceptTurnRequest,
    ConceptTurnResponse,
    CreateConceptRelationRequest,
    CreateConceptRequest,
    UpdateConceptOrganizationRequest,
    UpdateConceptSummaryRequest,
    UpdateNoteBlockRequest,
)

router = APIRouter(prefix="/v1", tags=["concepts"])


class ConceptTurnStreamEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    delta: str | None = None
    response: ConceptTurnResponse | None = None


def build_concept_service(
    settings: Settings | None = None,
    store: InMemoryConceptStore | PersistentConceptStore | None = None,
) -> ConceptService:
    resolved = settings or load_settings()
    concept_store = store or PersistentConceptStore(create_session_factory(resolved.database_url))
    if resolved.runtime_provider == "mock" or not resolved.runtime_api_key:
        return ConceptService(store=concept_store)

    provider = build_runtime_model_provider(
        resolved.runtime_provider,
        base_url=resolved.runtime_base_url,
        api_key=resolved.runtime_api_key,
    )
    runtime = LightweightHermesRuntime(
        model_provider=provider,
        model=resolve_runtime_model(resolved.runtime_provider, resolved.runtime_model),
        web_search_tool=_build_web_provider(resolved),
        web_search_enabled=resolved.runtime_web_search_enabled,
    )
    return ConceptService(
        store=concept_store,
        model_service=SiftRuntimeConceptModelService(runtime),
    )


def _build_web_provider(settings: Settings) -> RuntimeWebProvider:
    registry = build_web_provider_registry(tavily_api_key=settings.web_search_api_key)
    if not settings.runtime_web_search_enabled:
        return registry.create("disabled")
    provider_name = settings.web_search_provider or "disabled"
    return registry.create(provider_name)


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
    return await get_concept_service(request).create_concept_async(payload)


@router.get("/concepts/{concept_id}", response_model=ConceptDTO, response_model_by_alias=True)
async def get_concept(request: Request, concept_id: UUID) -> ConceptDTO:
    return get_concept_service(request).get_concept(concept_id)


@router.patch("/concepts/{concept_id}", response_model=ConceptDTO, response_model_by_alias=True)
async def update_concept_summary(
    request: Request,
    concept_id: UUID,
    payload: UpdateConceptSummaryRequest,
) -> ConceptDTO:
    return get_concept_service(request).update_concept_summary(concept_id, payload)


@router.patch(
    "/concepts/{concept_id}/blocks/{block_id}",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def update_note_block(
    request: Request,
    concept_id: UUID,
    block_id: UUID,
    payload: UpdateNoteBlockRequest,
) -> ConceptDTO:
    return get_concept_service(request).update_note_block(concept_id, block_id, payload)


@router.patch(
    "/concepts/{concept_id}/organization",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def update_concept_organization(
    request: Request,
    concept_id: UUID,
    payload: UpdateConceptOrganizationRequest,
) -> ConceptDTO:
    return get_concept_service(request).update_concept_organization(concept_id, payload)


@router.post(
    "/concepts/{concept_id}/relations",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def add_concept_relation(
    request: Request,
    concept_id: UUID,
    payload: CreateConceptRelationRequest,
) -> ConceptDTO:
    return get_concept_service(request).add_relation(concept_id, payload)


@router.delete(
    "/concepts/{concept_id}/relations/{relation_id}",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def remove_concept_relation(
    request: Request,
    concept_id: UUID,
    relation_id: UUID,
) -> ConceptDTO:
    return get_concept_service(request).remove_relation(concept_id, relation_id)


@router.get(
    "/concepts/{concept_id}/turns",
    response_model=list[ConceptHistoryTurnDTO],
    response_model_by_alias=True,
    response_model_exclude_none=True,
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


@router.post("/concepts/{concept_id}/turns/stream")
async def stream_concept_turn(
    request: Request,
    concept_id: UUID,
    payload: ConceptTurnRequest,
) -> StreamingResponse:
    async def events():
        service = get_concept_service(request)
        yield _stream_line(ConceptTurnStreamEvent(type="started"))
        async for event in service.submit_turn_stream(concept_id, payload):
            if isinstance(event, ConceptTurnStreamDelta):
                yield _stream_line(ConceptTurnStreamEvent(type="delta", delta=event.content))
            if isinstance(event, ConceptTurnStreamResult):
                yield _stream_line(
                    ConceptTurnStreamEvent(type="completed", response=event.response)
                )

    return StreamingResponse(events(), media_type="application/x-ndjson")


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


def _stream_line(event: ConceptTurnStreamEvent) -> str:
    return event.model_dump_json(by_alias=True, exclude_none=True) + "\n"
