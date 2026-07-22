from uuid import UUID

from fastapi import APIRouter, Header, Request

from sift_backend.api.concepts import get_concept_service
from sift_backend.api.model_run_submission import provider_snapshot, submit_model_run
from sift_backend.schemas.model_runs import (
    CreateConceptRunRequest,
    CreateTurnRunRequest,
    ModelRunDTO,
    ModelRunEventDTO,
    ModelRunKind,
)

router = APIRouter(prefix="/v1", tags=["model-runs"])


def _owner(request: Request) -> str:
    return request.state.principal.user_id


@router.post("/concept-runs", response_model=ModelRunDTO, response_model_by_alias=True)
async def create_concept_run(
    request: Request,
    payload: CreateConceptRunRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ModelRunDTO:
    managed = request.app.state.settings.auth_mode == "managed"
    has_credential = bool(request.headers.get("X-Sift-Provider-Key", "").strip())
    service = (
        None
        if managed and not has_credential
        else get_concept_service(request, requires_runtime=True)
    )
    return submit_model_run(
        request,
        kind=ModelRunKind.initial_concept,
        payload=payload.model_dump(mode="json", by_alias=True),
        service=service,
        idempotency_key=idempotency_key,
        client_draft_id=payload.client_draft_id,
        waiting_for_credential=managed and not has_credential,
    )


@router.post(
    "/concepts/{concept_id}/turn-runs", response_model=ModelRunDTO, response_model_by_alias=True
)
async def create_turn_run(
    request: Request,
    concept_id: UUID,
    payload: CreateTurnRunRequest,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> ModelRunDTO:
    managed = request.app.state.settings.auth_mode == "managed"
    has_credential = bool(request.headers.get("X-Sift-Provider-Key", "").strip())
    read_service = get_concept_service(request)
    read_service.get_concept(concept_id)
    service = (
        None
        if managed and not has_credential
        else get_concept_service(request, requires_runtime=True)
    )
    return submit_model_run(
        request,
        kind=ModelRunKind.follow_up,
        payload=payload.model_dump(mode="json", by_alias=True),
        service=service,
        idempotency_key=idempotency_key,
        concept_id=concept_id,
        waiting_for_credential=managed and not has_credential,
    )


@router.get("/model-runs", response_model=list[ModelRunDTO], response_model_by_alias=True)
async def list_model_runs(request: Request, active: bool = False) -> list[ModelRunDTO]:
    return request.app.state.model_run_repository.list(_owner(request), active=active)


@router.get("/model-runs/{run_id}", response_model=ModelRunDTO, response_model_by_alias=True)
async def get_model_run(request: Request, run_id: UUID) -> ModelRunDTO:
    return request.app.state.model_run_repository.get(run_id, _owner(request))


@router.get(
    "/model-runs/{run_id}/events",
    response_model=list[ModelRunEventDTO],
    response_model_by_alias=True,
)
async def get_model_run_events(
    request: Request, run_id: UUID, afterSequence: int = 0
) -> list[ModelRunEventDTO]:
    return request.app.state.model_run_repository.events(run_id, _owner(request), afterSequence)


@router.post(
    "/model-runs/{run_id}/resume", response_model=ModelRunDTO, response_model_by_alias=True
)
async def resume_model_run(request: Request, run_id: UUID) -> ModelRunDTO:
    service = get_concept_service(request, requires_runtime=True)
    existing = request.app.state.model_run_repository.get(run_id, _owner(request))
    current_snapshot = provider_snapshot(service)
    if existing.provider_snapshot and existing.provider_snapshot != current_snapshot:
        request.app.state.model_run_repository.fail(
            run_id,
            "provider_configuration_changed",
            "Provider configuration changed; start a new model run.",
        )
        return request.app.state.model_run_repository.get(run_id, _owner(request))
    if not existing.provider_snapshot:
        request.app.state.model_run_repository.set_provider_snapshot(
            run_id, _owner(request), current_snapshot
        )
    run = request.app.state.model_run_repository.mark_queued(run_id, _owner(request))
    request.app.state.model_run_coordinator.enqueue(run, service)
    return run
