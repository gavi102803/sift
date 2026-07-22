import asyncio
import json
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict

from sift_backend.api.model_run_submission import submit_model_run
from sift_backend.concepts.service import (
    ConceptService,
    InMemoryConceptStore,
    SiftRuntimeConceptModelService,
)
from sift_backend.config import Settings, load_settings
from sift_backend.persistence.concept_store import PersistentConceptStore
from sift_backend.persistence.database import create_session_factory
from sift_backend.runtime.concept_runtime import LightweightHermesRuntime
from sift_backend.runtime.managed_api import require_managed_provider_connection
from sift_backend.runtime.providers import build_runtime_model_provider, resolve_runtime_model
from sift_backend.runtime.research_stack import SiftReadabilityExtractProvider
from sift_backend.runtime.tools import RuntimeWebProvider, build_web_provider_registry
from sift_backend.schemas.common import ProposalStatus
from sift_backend.schemas.concepts import (
    BatchConceptRequest,
    ConceptDTO,
    ConceptHistoryTurnDTO,
    ConceptTurnRequest,
    ConceptTurnResponse,
    CreateConceptRelationRequest,
    CreateConceptRequest,
    NoteRevisionDTO,
    NoteRevisionSummaryDTO,
    UpdateConceptNoteRequest,
    UpdateConceptOrganizationRequest,
    UpdateConceptSummaryRequest,
    UpdateNoteBlockRequest,
    UpdateProposalDTO,
)
from sift_backend.schemas.model_runs import ModelRunDTO, ModelRunKind, ModelRunStatus

router = APIRouter(prefix="/v1", tags=["concepts"])


class ConceptTurnStreamEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    delta: str | None = None
    response: ConceptTurnResponse | None = None


class ConceptInitialStreamEvent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    type: str
    delta: str | None = None
    concept: ConceptDTO | None = None


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
        web_extract_tool=SiftReadabilityExtractProvider(),
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


def get_concept_service(request: Request, *, requires_runtime: bool = False) -> ConceptService:
    service = getattr(request.app.state, "concept_service", None)
    if service is None:
        service = build_concept_service()
        request.app.state.concept_service = service
    principal = getattr(request.state, "principal", service.principal)
    settings = getattr(request.app.state, "settings", None)
    if settings is not None and settings.auth_mode == "managed" and requires_runtime:
        connection, api_key = require_managed_provider_connection(request)
        provider = build_runtime_model_provider(
            connection.provider_id,
            base_url=connection.base_url,
            api_key=api_key,
        )
        runtime = LightweightHermesRuntime(
            model_provider=provider,
            model=connection.model,
            web_search_tool=_build_web_provider(settings),
            web_extract_tool=SiftReadabilityExtractProvider(),
            web_search_enabled=settings.runtime_web_search_enabled,
        )
        return ConceptService(
            store=service.store,
            model_service=SiftRuntimeConceptModelService(runtime),
            principal=principal,
        )
    if principal == service.principal:
        return service
    return ConceptService(
        store=service.store,
        model_service=service.model_service,
        principal=principal,
    )


@router.get("/concepts", response_model=list[ConceptDTO], response_model_by_alias=True)
async def list_concepts(request: Request) -> list[ConceptDTO]:
    return get_concept_service(request).list_concepts()


@router.patch(
    "/concepts/archive",
    response_model=list[ConceptDTO],
    response_model_by_alias=True,
)
async def archive_concepts(
    request: Request,
    payload: BatchConceptRequest,
) -> list[ConceptDTO]:
    return get_concept_service(request).set_concepts_archived(
        payload.concept_ids,
        archived=True,
    )


@router.patch(
    "/concepts/restore",
    response_model=list[ConceptDTO],
    response_model_by_alias=True,
)
async def restore_concepts(
    request: Request,
    payload: BatchConceptRequest,
) -> list[ConceptDTO]:
    return get_concept_service(request).set_concepts_archived(
        payload.concept_ids,
        archived=False,
    )


@router.post("/concepts", response_model=ConceptDTO, response_model_by_alias=True)
async def create_concept(request: Request, payload: CreateConceptRequest) -> ConceptDTO:
    run = _submit_initial_run(request, payload)
    completed = await _wait_for_terminal_run(request, run)
    return ConceptDTO.model_validate(_run_result(completed, "concept"))


@router.post("/concepts/stream")
async def stream_create_concept(
    request: Request,
    payload: CreateConceptRequest,
) -> StreamingResponse:
    run = _submit_initial_run(request, payload)
    should_reconstruct_delta = run.status in {ModelRunStatus.queued, ModelRunStatus.running}

    async def events():
        yield _stream_line(ConceptInitialStreamEvent(type="started"))
        emitted_delta = False
        async for content in _bridge_model_run_deltas(request, run):
            emitted_delta = True
            yield _stream_line(ConceptInitialStreamEvent(type="delta", delta=content))
        completed = request.app.state.model_run_repository.get(run.id, _owner(request))
        if completed.status == ModelRunStatus.succeeded:
            concept = ConceptDTO.model_validate(_run_result(completed, "concept"))
            if should_reconstruct_delta and not emitted_delta:
                yield _stream_line(
                    ConceptInitialStreamEvent(
                        type="delta",
                        delta=concept.initial_answer or concept.one_line_explanation,
                    )
                )
            yield _stream_line(ConceptInitialStreamEvent(type="completed", concept=concept))
        else:
            yield _stream_failure_line(completed)

    return StreamingResponse(events(), media_type="application/x-ndjson")


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


@router.put(
    "/concepts/{concept_id}/note",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def update_concept_note(
    request: Request,
    concept_id: UUID,
    payload: UpdateConceptNoteRequest,
) -> ConceptDTO:
    return get_concept_service(request).update_concept_note(concept_id, payload)


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
    run = _submit_turn_run(request, concept_id, payload)
    completed = await _wait_for_terminal_run(request, run)
    return ConceptTurnResponse.model_validate(_run_result(completed, "response"))


@router.post("/concepts/{concept_id}/turns/stream")
async def stream_concept_turn(
    request: Request,
    concept_id: UUID,
    payload: ConceptTurnRequest,
) -> StreamingResponse:
    run = _submit_turn_run(request, concept_id, payload)
    should_reconstruct_delta = run.status in {ModelRunStatus.queued, ModelRunStatus.running}

    async def events():
        yield _stream_line(ConceptTurnStreamEvent(type="started"))
        emitted_delta = False
        async for content in _bridge_model_run_deltas(request, run):
            emitted_delta = True
            yield _stream_line(ConceptTurnStreamEvent(type="delta", delta=content))
        completed = request.app.state.model_run_repository.get(run.id, _owner(request))
        if completed.status == ModelRunStatus.succeeded:
            response = ConceptTurnResponse.model_validate(_run_result(completed, "response"))
            if should_reconstruct_delta and not emitted_delta:
                yield _stream_line(ConceptTurnStreamEvent(type="delta", delta=response.answer))
            yield _stream_line(ConceptTurnStreamEvent(type="completed", response=response))
        else:
            yield _stream_failure_line(completed)

    return StreamingResponse(events(), media_type="application/x-ndjson")


@router.post(
    "/update-proposals/{proposal_id}/merge",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def merge_update_proposal(request: Request, proposal_id: UUID) -> ConceptDTO:
    service = get_concept_service(request)
    concept = service.merge_proposal(
        proposal_id,
        idempotency_key=_idempotency_key(request),
    )
    request.app.state.model_run_coordinator.reconsider_review(concept.id, service)
    return concept


@router.post("/update-proposals/{proposal_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_update_proposal(request: Request, proposal_id: UUID) -> None:
    service = get_concept_service(request)
    concept_id = service.store.get_proposal_concept_id(proposal_id)
    service.dismiss_proposal(proposal_id)
    request.app.state.model_run_coordinator.reconsider_review(concept_id, service)


@router.get(
    "/concepts/{concept_id}/proposals",
    response_model=list[UpdateProposalDTO],
    response_model_by_alias=True,
)
async def list_update_proposals(
    request: Request, concept_id: UUID, status: ProposalStatus | None = None
) -> list[UpdateProposalDTO]:
    return get_concept_service(request).list_proposals(concept_id, status)


@router.get(
    "/concepts/{concept_id}/revisions",
    response_model=list[NoteRevisionSummaryDTO],
    response_model_by_alias=True,
)
async def list_note_revisions(request: Request, concept_id: UUID) -> list[NoteRevisionSummaryDTO]:
    return get_concept_service(request).list_revisions(concept_id)


@router.get(
    "/concepts/{concept_id}/revisions/{revision}",
    response_model=NoteRevisionDTO,
    response_model_by_alias=True,
)
async def get_note_revision(request: Request, concept_id: UUID, revision: int) -> NoteRevisionDTO:
    return get_concept_service(request).get_revision(concept_id, revision)


@router.post(
    "/concepts/{concept_id}/revisions/{revision}/restore",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def restore_note_revision(request: Request, concept_id: UUID, revision: int) -> ConceptDTO:
    return get_concept_service(request).restore_revision(concept_id, revision)


def _stream_line(event: ConceptTurnStreamEvent | ConceptInitialStreamEvent) -> str:
    response = getattr(event, "response", None)
    if response is not None:
        return (
            json.dumps(
                {
                    "type": event.type,
                    "response": response.model_dump(mode="json", by_alias=True),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
    concept = getattr(event, "concept", None)
    if concept is not None:
        return (
            json.dumps(
                {
                    "type": event.type,
                    "concept": concept.model_dump(mode="json", by_alias=True),
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\n"
        )
    return event.model_dump_json(by_alias=True, exclude_none=True) + "\n"


def _owner(request: Request) -> str:
    return request.state.principal.user_id


def _runtime_service_for_run(request: Request) -> tuple[ConceptService | None, bool]:
    managed = request.app.state.settings.auth_mode == "managed"
    has_credential = bool(request.headers.get("X-Sift-Provider-Key", "").strip())
    if managed and not has_credential:
        return None, True
    return get_concept_service(request, requires_runtime=True), False


def _submit_initial_run(request: Request, payload: CreateConceptRequest) -> ModelRunDTO:
    service, waiting = _runtime_service_for_run(request)
    return submit_model_run(
        request,
        kind=ModelRunKind.initial_concept,
        payload={"capture": payload.model_dump(mode="json", by_alias=True)},
        service=service,
        idempotency_key=_idempotency_key(request),
        waiting_for_credential=waiting,
    )


def _submit_turn_run(
    request: Request,
    concept_id: UUID,
    payload: ConceptTurnRequest,
) -> ModelRunDTO:
    get_concept_service(request).get_concept(concept_id)
    service, waiting = _runtime_service_for_run(request)
    return submit_model_run(
        request,
        kind=ModelRunKind.follow_up,
        payload={"turn": payload.model_dump(mode="json", by_alias=True)},
        service=service,
        idempotency_key=_idempotency_key(request),
        concept_id=concept_id,
        waiting_for_credential=waiting,
    )


async def _wait_for_terminal_run(request: Request, run: ModelRunDTO) -> ModelRunDTO:
    current = run
    while current.status in {ModelRunStatus.queued, ModelRunStatus.running}:
        await asyncio.sleep(0.01)
        current = request.app.state.model_run_repository.get(run.id, _owner(request))
    if current.status == ModelRunStatus.waiting_for_credential:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "credential_required",
                "message": "Reconnect with a provider credential to resume this model run.",
                "runId": str(current.id),
            },
        )
    if current.status != ModelRunStatus.succeeded:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": current.error_code or "model_run_failed",
                "message": current.error_message or "The model run could not be completed.",
                "runId": str(current.id),
            },
        )
    return current


async def _bridge_model_run_deltas(request: Request, run: ModelRunDTO):
    current = run
    after_sequence = 0
    while current.status in {ModelRunStatus.queued, ModelRunStatus.running}:
        for event in request.app.state.model_run_repository.events(
            run.id, _owner(request), after_sequence
        ):
            after_sequence = max(after_sequence, event.sequence)
            if event.type == "delta" and event.data and event.data.get("content"):
                yield str(event.data["content"])
        await asyncio.sleep(0.01)
        current = request.app.state.model_run_repository.get(run.id, _owner(request))


def _run_result(run: ModelRunDTO, key: str) -> object:
    if run.result is None or key not in run.result:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={"code": "model_run_incomplete", "message": "Model run result is missing."},
        )
    return run.result[key]


def _stream_failure_line(run: ModelRunDTO) -> str:
    return (
        json.dumps(
            {
                "type": "failed",
                "errorCode": run.error_code or "model_run_failed",
                "errorMessage": run.error_message or "The model run could not be completed.",
                "runId": str(run.id),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        + "\n"
    )


def _idempotency_key(request: Request) -> str | None:
    value = request.headers.get("idempotency-key")
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None
