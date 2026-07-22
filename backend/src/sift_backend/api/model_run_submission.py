from typing import Any
from uuid import UUID, uuid4

from fastapi import Request

from sift_backend.schemas.model_runs import ModelRunDTO, ModelRunKind


def provider_snapshot(service: object | None) -> dict[str, str]:
    model_service = getattr(service, "model_service", None)
    runtime = getattr(model_service, "runtime", None)
    provider = getattr(runtime, "model_provider", None)
    if runtime is None or provider is None:
        return {}
    snapshot = {
        "provider": str(getattr(provider, "provider_name", provider.__class__.__name__)),
        "model": str(getattr(runtime, "model", "")),
    }
    base_url = getattr(provider, "base_url", None)
    if base_url:
        snapshot["baseURL"] = str(base_url)
    return snapshot


def submit_model_run(
    request: Request,
    *,
    kind: ModelRunKind,
    payload: dict[str, Any],
    service: object | None,
    idempotency_key: str | None,
    concept_id: UUID | None = None,
    client_draft_id: str | None = None,
    waiting_for_credential: bool = False,
) -> ModelRunDTO:
    run, created = request.app.state.model_run_repository.create(
        owner_id=request.state.principal.user_id,
        kind=kind,
        idempotency_key=idempotency_key or str(uuid4()),
        payload=payload,
        concept_id=concept_id,
        client_draft_id=client_draft_id,
        provider_snapshot=provider_snapshot(service),
        waiting_for_credential=waiting_for_credential,
    )
    if created:
        request.app.state.model_run_coordinator.enqueue(run, service)
    return run
