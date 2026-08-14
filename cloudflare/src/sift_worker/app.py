from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Header, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sift_worker.d1 import D1WorkerStore
from sift_worker.errors import PublicError
from sift_worker.models import (
    ActivateBetaRequest,
    AppStatusResponse,
    BatchConceptRequest,
    BetaSessionResponse,
    ConceptHistoryTurnResponse,
    ConceptResponse,
    CreateConceptRelationRequest,
    CreateConceptRunRequest,
    CreateTurnRunRequest,
    HealthResponse,
    ModelDiagnosticResponse,
    ModelRunEventResponse,
    ModelRunResponse,
    NoteRevisionResponse,
    NoteRevisionSummaryResponse,
    ProviderConnectionRequest,
    ProviderConnectionResponse,
    ProviderModelListResponse,
    ProviderModelResponse,
    ProviderTestResponse,
    RuntimeProviderCatalogResponse,
    RuntimeProviderOptionResponse,
    UpdateConceptNoteRequest,
    UpdateConceptOrganizationRequest,
    UpdateConceptSummaryRequest,
    UpdateNoteBlockRequest,
    UpdateProposalResponse,
    UpdateWebProviderSettingsRequest,
    WebProviderCatalogResponse,
    WebProviderOptionResponse,
    WebProviderSettingsResponse,
    normalize_uuid_string,
)
from sift_worker.runtime import (
    PROVIDER_PROFILES,
    WorkerProviderClient,
    validate_provider_connection,
)
from sift_worker.services import (
    AuthService,
    ConceptMutationService,
    ModelRunService,
    ProviderClientFactory,
    ProviderConnectionService,
)
from sift_worker.store import WorkerStore
from sift_worker.web_search import WEB_PROVIDER_PROFILES, WorkerWebSearchClient

StoreFactory = Callable[[Request], WorkerStore]


def create_app(
    store_factory: StoreFactory | None = None,
    provider_client_factory: ProviderClientFactory | None = None,
) -> FastAPI:
    worker_app = FastAPI(
        title="Sift Cloudflare Backend",
        version="0.1.0",
        description="Cloudflare Workers deployment target for Sift.",
    )
    resolved_store_factory = store_factory or _d1_store
    resolved_provider_client_factory = provider_client_factory or WorkerProviderClient

    @worker_app.exception_handler(PublicError)
    async def public_error_handler(request: Request, error: PublicError) -> JSONResponse:
        return _error_response(
            request,
            error.code,
            error.message,
            error.status_code,
            extra=error.extra,
        )

    @worker_app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request,
        _error: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(request, "invalid_request", "The request is invalid.", 422)

    @worker_app.middleware("http")
    async def authenticate_request(request: Request, call_next):
        request.scope["path"] = _normalize_uuid_path(request.scope["path"])
        request.scope["raw_path"] = request.scope["path"].encode()
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
        if request.url.path not in {"/health", "/v1/beta/activate"}:
            store = resolved_store_factory(request)
            auth = AuthService(
                store,
                token_ttl_days=_int_env(request, "SIFT_BETA_TOKEN_TTL_DAYS", 30),
            )
            try:
                request.state.principal = await auth.authenticate(
                    _bearer_token(request),
                    request.headers.get("X-Sift-Installation", ""),
                )
            except PublicError as error:
                return _error_response(
                    request,
                    error.code,
                    error.message,
                    error.status_code,
                )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @worker_app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        return HealthResponse(
            status="ok",
            env=_text_env(request, "SIFT_ENV", "development"),
            runtime="cloudflare-workers",
        )

    @worker_app.post(
        "/v1/beta/activate",
        response_model=BetaSessionResponse,
        response_model_by_alias=True,
    )
    async def activate_beta(
        request: Request,
        payload: ActivateBetaRequest,
    ) -> BetaSessionResponse:
        service = AuthService(
            resolved_store_factory(request),
            token_ttl_days=_int_env(request, "SIFT_BETA_TOKEN_TTL_DAYS", 30),
        )
        issued = await service.activate(payload.invite_code, payload.installation_id)
        return BetaSessionResponse(
            betaAccessToken=issued.token,
            ownerId=issued.owner_id,
            expiresAt=issued.expires_at,
        )

    @worker_app.post(
        "/v1/beta/session/refresh",
        response_model=BetaSessionResponse,
        response_model_by_alias=True,
    )
    async def refresh_beta_session(request: Request) -> BetaSessionResponse:
        issued = await AuthService(
            resolved_store_factory(request),
            token_ttl_days=_int_env(request, "SIFT_BETA_TOKEN_TTL_DAYS", 30),
        ).refresh(
            _bearer_token(request),
            request.headers.get("X-Sift-Installation", ""),
        )
        return BetaSessionResponse(
            betaAccessToken=issued.token,
            ownerId=issued.owner_id,
            expiresAt=issued.expires_at,
        )

    @worker_app.get(
        "/v1/app-status",
        response_model=AppStatusResponse,
        response_model_by_alias=True,
    )
    async def app_status(request: Request) -> AppStatusResponse:
        store = resolved_store_factory(request)
        connection = await store.get_provider_connection(
            request.state.principal.owner_id
        )
        web_settings = await store.get_web_provider_settings(
            request.state.principal.owner_id
        )
        return AppStatusResponse(
            env=_text_env(request, "SIFT_ENV", "development"),
            modelProvider=str(connection["provider_id"]) if connection else "unconfigured",
            explainModel=str(connection["model"]) if connection else "unconfigured",
            webSearchEnabled=bool(web_settings.get("web_search_enabled", 1)),
            databaseURL="d1",
            providerBaseURL=str(connection["base_url"]) if connection else None,
            apiKeyConfigured=False,
            apiKeyPreview=None,
        )

    @worker_app.get(
        "/v1/runtime/model-providers",
        response_model=RuntimeProviderCatalogResponse,
        response_model_by_alias=True,
    )
    async def runtime_model_providers() -> RuntimeProviderCatalogResponse:
        names = {
            "openai": ("OpenAI", "OpenAI models through the Responses-compatible API."),
            "anthropic": ("Anthropic", "Claude models through the Anthropic Messages API."),
            "gemini": (
                "Google Gemini",
                "Gemini models through the Google Generative Language API.",
            ),
            "deepseek": ("DeepSeek", "DeepSeek's OpenAI-compatible API."),
            "openrouter": ("OpenRouter", "Models routed through OpenRouter."),
            "nous": ("Nous Research", "Hermes models through the Nous inference API."),
            "kimi": ("Kimi", "Moonshot Kimi models through its OpenAI-compatible API."),
            "custom": ("Custom", "A compatible HTTPS endpoint you control."),
        }
        providers = []
        for profile in PROVIDER_PROFILES.values():
            name, description = names[profile.id]
            providers.append(
                RuntimeProviderOptionResponse(
                    id=profile.id,
                    name=name,
                    description=description,
                    adapter=profile.adapter,
                    protocolDriver=profile.adapter,
                    exposureTier="advanced" if profile.id == "custom" else "plannedStable",
                    defaultBaseURL=profile.default_base_url,
                    defaultModel=profile.default_model,
                    requiresApiKey=True,
                    supportsModelListing=True,
                    status="available",
                    isAdvanced=profile.id == "custom",
                )
            )
        return RuntimeProviderCatalogResponse(providers=providers)

    @worker_app.get(
        "/v1/runtime/web-providers",
        response_model=WebProviderCatalogResponse,
        response_model_by_alias=True,
    )
    async def runtime_web_providers() -> WebProviderCatalogResponse:
        return WebProviderCatalogResponse(
            providers=[
                WebProviderOptionResponse(
                    id=provider_id,
                    name=profile[0],
                    description=profile[1],
                    requiresApiKey=profile[2],
                    supportsSearch=True,
                    supportsExtract=profile[3],
                    status="available",
                    isDefault=profile[4],
                )
                for provider_id, profile in WEB_PROVIDER_PROFILES.items()
            ]
        )

    @worker_app.get(
        "/v1/web-provider-settings",
        response_model=WebProviderSettingsResponse,
        response_model_by_alias=True,
    )
    async def get_web_provider_settings(request: Request) -> WebProviderSettingsResponse:
        settings = await resolved_store_factory(request).get_web_provider_settings(
            request.state.principal.owner_id
        )
        return WebProviderSettingsResponse(
            providerType=str(settings["provider_type"]),
            apiKeyConfigured=False,
            apiKeyPreview=None,
            webSearchEnabled=bool(settings["web_search_enabled"]),
        )

    @worker_app.put(
        "/v1/web-provider-settings",
        response_model=WebProviderSettingsResponse,
        response_model_by_alias=True,
    )
    async def update_web_provider_settings(
        request: Request,
        payload: UpdateWebProviderSettingsRequest,
    ) -> WebProviderSettingsResponse:
        if payload.provider_type not in WEB_PROVIDER_PROFILES:
            raise PublicError(
                "managed_unsupported",
                "The selected web provider is not supported.",
                422,
            )
        settings = await resolved_store_factory(request).save_web_provider_settings(
            owner_id=request.state.principal.owner_id,
            provider_type=payload.provider_type,
            web_search_enabled=payload.web_search_enabled,
            now=datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        )
        return WebProviderSettingsResponse(
            providerType=str(settings["provider_type"]),
            apiKeyConfigured=False,
            apiKeyPreview=None,
            webSearchEnabled=bool(settings["web_search_enabled"]),
        )

    @worker_app.post(
        "/v1/web-search-diagnostic",
        response_model=ModelDiagnosticResponse,
        response_model_by_alias=True,
    )
    async def web_search_diagnostic(request: Request) -> ModelDiagnosticResponse:
        settings = await resolved_store_factory(request).get_web_provider_settings(
            request.state.principal.owner_id
        )
        if not bool(settings.get("web_search_enabled", 1)):
            return ModelDiagnosticResponse(
                ok=False,
                provider="ddgs",
                model="managed",
                message="Web search is disabled.",
                webSearchUsed=False,
                citationCount=0,
            )
        provider_id = str(settings.get("provider_type", "ddgs"))
        provider_key = request.headers.get("X-Sift-Web-Provider-Key", "").strip()
        results = await WorkerWebSearchClient(
            provider_id=provider_id,
            api_key=provider_key,
        ).search(
            "Cloudflare Workers documentation"
        )
        return ModelDiagnosticResponse(
            ok=True,
            provider=provider_id,
            model="managed",
            message="Managed beta web search is ready.",
            webSearchUsed=True,
            citationCount=len(results),
        )

    @worker_app.post(
        "/v1/concept-runs",
        response_model=ModelRunResponse,
        response_model_by_alias=True,
        status_code=202,
    )
    async def create_concept_run(
        request: Request,
        payload: CreateConceptRunRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ModelRunResponse:
        service = ModelRunService(resolved_store_factory(request))
        provider_key = request.headers.get("X-Sift-Provider-Key", "").strip()
        run, created = await service.submit_initial(
            request.state.principal,
            payload,
            idempotency_key=idempotency_key,
            has_provider_credential=bool(provider_key),
        )
        # New clients omit the request-only BYOK key here, then resume the
        # durable run while polling persisted events. Keep the one-request path
        # for already-installed clients that still send the key on submission.
        if created and provider_key:
            return await service.execute_initial(
                run.id,
                request.state.principal,
                provider_key,
                web_provider_key=request.headers.get(
                    "X-Sift-Web-Provider-Key", ""
                ).strip(),
                client_factory=resolved_provider_client_factory,
            )
        return run

    @worker_app.post(
        "/v1/concepts/{concept_id}/turn-runs",
        response_model=ModelRunResponse,
        response_model_by_alias=True,
        status_code=202,
    )
    async def create_turn_run(
        request: Request,
        concept_id: str,
        payload: CreateTurnRunRequest,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ModelRunResponse:
        service = ModelRunService(resolved_store_factory(request))
        provider_key = request.headers.get("X-Sift-Provider-Key", "").strip()
        run, created = await service.submit_follow_up(
            request.state.principal,
            concept_id,
            payload,
            idempotency_key=idempotency_key,
            has_provider_credential=bool(provider_key),
        )
        if created and provider_key:
            return await service.execute_follow_up(
                run.id,
                request.state.principal,
                provider_key,
                web_provider_key=request.headers.get(
                    "X-Sift-Web-Provider-Key", ""
                ).strip(),
                client_factory=resolved_provider_client_factory,
            )
        return run

    @worker_app.get(
        "/v1/provider-connection",
        response_model=ProviderConnectionResponse,
        response_model_by_alias=True,
    )
    async def get_provider_connection(request: Request) -> ProviderConnectionResponse:
        service = ProviderConnectionService(resolved_store_factory(request))
        connection = await service.get(request.state.principal.owner_id)
        return service.response(connection)

    @worker_app.put(
        "/v1/provider-connection",
        response_model=ProviderConnectionResponse,
        response_model_by_alias=True,
    )
    async def put_provider_connection(
        request: Request,
        payload: ProviderConnectionRequest,
    ) -> ProviderConnectionResponse:
        service = ProviderConnectionService(resolved_store_factory(request))
        connection = await service.save(
            request.state.principal.owner_id,
            payload.provider_id,
            payload.base_url,
            payload.model,
            allow_local_http=_text_env(request, "SIFT_ENV", "production")
            == "development",
        )
        return service.response(connection)

    @worker_app.post(
        "/v1/providers/test",
        response_model=ProviderTestResponse,
        response_model_by_alias=True,
    )
    async def test_provider_connection(
        request: Request,
        payload: ProviderConnectionRequest,
    ) -> ProviderTestResponse:
        provider_key = request.headers.get("X-Sift-Provider-Key", "").strip()
        if not provider_key:
            raise PublicError("invalid_provider_key", "Check your provider API key.", 401)
        connection = validate_provider_connection(
            request.state.principal.owner_id,
            payload.provider_id,
            payload.base_url,
            payload.model,
            allow_local_http=_text_env(request, "SIFT_ENV", "production")
            == "development",
        )
        await resolved_provider_client_factory(connection, provider_key).test()
        return ProviderTestResponse(ok=True)

    @worker_app.post(
        "/v1/providers/models",
        response_model=ProviderModelListResponse,
        response_model_by_alias=True,
    )
    async def list_provider_models(
        request: Request,
        payload: ProviderConnectionRequest,
    ) -> ProviderModelListResponse:
        provider_key = request.headers.get("X-Sift-Provider-Key", "").strip()
        if not provider_key:
            raise PublicError("invalid_provider_key", "Check your provider API key.", 401)
        connection = validate_provider_connection(
            request.state.principal.owner_id,
            payload.provider_id,
            payload.base_url,
            payload.model,
            allow_local_http=_text_env(request, "SIFT_ENV", "production")
            == "development",
        )
        models = await resolved_provider_client_factory(connection, provider_key).list_models()
        return ProviderModelListResponse(
            models=[
                ProviderModelResponse(id=model, ownedBy=connection.provider_id)
                for model in models
            ]
        )

    @worker_app.get(
        "/v1/model-runs",
        response_model=list[ModelRunResponse],
        response_model_by_alias=True,
    )
    async def list_model_runs(request: Request, active: bool = False) -> list[ModelRunResponse]:
        return await ModelRunService(resolved_store_factory(request)).list(
            request.state.principal.owner_id,
            active=active,
        )

    @worker_app.get(
        "/v1/model-runs/{run_id}",
        response_model=ModelRunResponse,
        response_model_by_alias=True,
    )
    async def get_model_run(request: Request, run_id: str) -> ModelRunResponse:
        return await ModelRunService(resolved_store_factory(request)).get(
            run_id,
            request.state.principal.owner_id,
        )

    @worker_app.post(
        "/v1/model-runs/{run_id}/cancel",
        response_model=ModelRunResponse,
        response_model_by_alias=True,
    )
    async def cancel_model_run(request: Request, run_id: str) -> ModelRunResponse:
        return await ModelRunService(resolved_store_factory(request)).cancel(
            run_id,
            request.state.principal.owner_id,
        )

    @worker_app.get(
        "/v1/model-runs/{run_id}/events",
        response_model=list[ModelRunEventResponse],
        response_model_by_alias=True,
    )
    async def get_model_run_events(
        request: Request,
        run_id: str,
        afterSequence: int = 0,
    ) -> list[ModelRunEventResponse]:
        return await ModelRunService(resolved_store_factory(request)).events(
            run_id,
            request.state.principal.owner_id,
            afterSequence,
        )

    @worker_app.post(
        "/v1/model-runs/{run_id}/resume",
        response_model=ModelRunResponse,
        response_model_by_alias=True,
    )
    async def resume_model_run(request: Request, run_id: str) -> ModelRunResponse:
        provider_key = request.headers.get("X-Sift-Provider-Key", "").strip()
        if not provider_key:
            raise PublicError("invalid_provider_key", "Check your provider API key.", 401)
        service = ModelRunService(resolved_store_factory(request))
        run = await service.get(run_id, request.state.principal.owner_id)
        if run.kind == "initialConcept":
            return await service.execute_initial(
                run_id,
                request.state.principal,
                provider_key,
                web_provider_key=request.headers.get(
                    "X-Sift-Web-Provider-Key", ""
                ).strip(),
                client_factory=resolved_provider_client_factory,
            )
        if run.kind == "followUp":
            return await service.execute_follow_up(
                run_id,
                request.state.principal,
                provider_key,
                web_provider_key=request.headers.get("X-Sift-Web-Provider-Key", "").strip(),
                client_factory=resolved_provider_client_factory,
            )
        raise PublicError("request_conflict", "The model run cannot be resumed.", 409)

    @worker_app.get(
        "/v1/concepts",
        response_model=list[ConceptResponse],
        response_model_by_alias=True,
    )
    async def list_concepts(request: Request) -> list[ConceptResponse]:
        return await ModelRunService(resolved_store_factory(request)).list_concepts(
            request.state.principal.owner_id
        )

    @worker_app.patch(
        "/v1/concepts/archive",
        response_model=list[ConceptResponse],
        response_model_by_alias=True,
    )
    async def archive_concepts(
        request: Request,
        payload: BatchConceptRequest,
    ) -> list[ConceptResponse]:
        return await ConceptMutationService(resolved_store_factory(request)).set_archived(
            payload.concept_ids,
            request.state.principal.owner_id,
            archived=True,
        )

    @worker_app.patch(
        "/v1/concepts/restore",
        response_model=list[ConceptResponse],
        response_model_by_alias=True,
    )
    async def restore_concepts(
        request: Request,
        payload: BatchConceptRequest,
    ) -> list[ConceptResponse]:
        return await ConceptMutationService(resolved_store_factory(request)).set_archived(
            payload.concept_ids,
            request.state.principal.owner_id,
            archived=False,
        )

    @worker_app.get(
        "/v1/concepts/{concept_id}",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def get_concept(request: Request, concept_id: str) -> ConceptResponse:
        return await ModelRunService(resolved_store_factory(request)).get_concept(
            concept_id,
            request.state.principal.owner_id,
        )

    @worker_app.patch(
        "/v1/concepts/{concept_id}",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def update_concept_summary(
        request: Request,
        concept_id: str,
        payload: UpdateConceptSummaryRequest,
    ) -> ConceptResponse:
        return await ConceptMutationService(resolved_store_factory(request)).update_summary(
            concept_id,
            request.state.principal.owner_id,
            payload,
        )

    @worker_app.patch(
        "/v1/concepts/{concept_id}/blocks/{block_id}",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def update_note_block(
        request: Request,
        concept_id: str,
        block_id: str,
        payload: UpdateNoteBlockRequest,
    ) -> ConceptResponse:
        return await ConceptMutationService(resolved_store_factory(request)).update_block(
            concept_id,
            block_id,
            request.state.principal.owner_id,
            payload,
        )

    @worker_app.put(
        "/v1/concepts/{concept_id}/note",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def update_concept_note(
        request: Request,
        concept_id: str,
        payload: UpdateConceptNoteRequest,
    ) -> ConceptResponse:
        return await ConceptMutationService(resolved_store_factory(request)).update_note(
            concept_id,
            request.state.principal.owner_id,
            payload,
        )

    @worker_app.patch(
        "/v1/concepts/{concept_id}/organization",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def update_concept_organization(
        request: Request,
        concept_id: str,
        payload: UpdateConceptOrganizationRequest,
    ) -> ConceptResponse:
        return await ConceptMutationService(
            resolved_store_factory(request)
        ).update_organization(
            concept_id,
            request.state.principal.owner_id,
            payload,
        )

    @worker_app.post(
        "/v1/concepts/{concept_id}/relations",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def add_concept_relation(
        request: Request,
        concept_id: str,
        payload: CreateConceptRelationRequest,
    ) -> ConceptResponse:
        return await ConceptMutationService(resolved_store_factory(request)).add_relation(
            concept_id,
            request.state.principal.owner_id,
            payload,
        )

    @worker_app.delete(
        "/v1/concepts/{concept_id}/relations/{relation_id}",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def remove_concept_relation(
        request: Request,
        concept_id: str,
        relation_id: str,
    ) -> ConceptResponse:
        return await ConceptMutationService(
            resolved_store_factory(request)
        ).remove_relation(
            concept_id,
            relation_id,
            request.state.principal.owner_id,
        )

    @worker_app.get(
        "/v1/concepts/{concept_id}/turns",
        response_model=list[ConceptHistoryTurnResponse],
        response_model_by_alias=True,
    )
    async def list_concept_turns(
        request: Request,
        concept_id: str,
    ) -> list[ConceptHistoryTurnResponse]:
        return await ModelRunService(resolved_store_factory(request)).list_turns(
            concept_id,
            request.state.principal.owner_id,
        )

    @worker_app.get(
        "/v1/concepts/{concept_id}/proposals",
        response_model=list[UpdateProposalResponse],
        response_model_by_alias=True,
    )
    async def list_update_proposals(
        request: Request,
        concept_id: str,
        status: str | None = None,
    ) -> list[UpdateProposalResponse]:
        return await ModelRunService(resolved_store_factory(request)).list_proposals(
            concept_id,
            request.state.principal.owner_id,
            status,
        )

    @worker_app.post(
        "/v1/update-proposals/{proposal_id}/merge",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def merge_update_proposal(
        request: Request,
        proposal_id: str,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> ConceptResponse:
        return await ConceptMutationService(
            resolved_store_factory(request)
        ).merge_proposal(
            proposal_id,
            request.state.principal.owner_id,
            idempotency_key=idempotency_key,
        )

    @worker_app.post(
        "/v1/update-proposals/{proposal_id}/dismiss",
        status_code=204,
    )
    async def dismiss_update_proposal(
        request: Request,
        proposal_id: str,
    ) -> None:
        await ModelRunService(resolved_store_factory(request)).dismiss_proposal(
            proposal_id,
            request.state.principal.owner_id,
        )

    @worker_app.get(
        "/v1/concepts/{concept_id}/revisions",
        response_model=list[NoteRevisionSummaryResponse],
        response_model_by_alias=True,
    )
    async def list_note_revisions(
        request: Request,
        concept_id: str,
    ) -> list[NoteRevisionSummaryResponse]:
        return await ModelRunService(resolved_store_factory(request)).list_revisions(
            concept_id,
            request.state.principal.owner_id,
        )

    @worker_app.get(
        "/v1/concepts/{concept_id}/revisions/{revision}",
        response_model=NoteRevisionResponse,
        response_model_by_alias=True,
    )
    async def get_note_revision(
        request: Request,
        concept_id: str,
        revision: int,
    ) -> NoteRevisionResponse:
        return await ModelRunService(resolved_store_factory(request)).get_revision(
            concept_id,
            revision,
            request.state.principal.owner_id,
        )

    @worker_app.post(
        "/v1/concepts/{concept_id}/revisions/{revision}/restore",
        response_model=ConceptResponse,
        response_model_by_alias=True,
    )
    async def restore_note_revision(
        request: Request,
        concept_id: str,
        revision: int,
    ) -> ConceptResponse:
        return await ConceptMutationService(
            resolved_store_factory(request)
        ).restore_revision(
            concept_id,
            revision,
            request.state.principal.owner_id,
        )

    return worker_app


def _normalize_uuid_path(path: str) -> str:
    return "/".join(normalize_uuid_string(segment) for segment in path.split("/"))


def _d1_store(request: Request) -> WorkerStore:
    environment = request.scope.get("env")
    if environment is None or not hasattr(environment, "DB"):
        raise PublicError("backend_unavailable", "Sift is temporarily unavailable.", 503)
    return D1WorkerStore(environment.DB)


def _text_env(request: Request, name: str, default: str) -> str:
    environment = request.scope.get("env")
    value: Any = getattr(environment, name, None) if environment is not None else None
    return str(value) if value not in {None, ""} else default


def _int_env(request: Request, name: str, default: int) -> int:
    try:
        return int(_text_env(request, name, str(default)))
    except ValueError:
        return default


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" else ""


def _error_response(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    *,
    extra: dict[str, Any] | None = None,
) -> JSONResponse:
    error = {
        "code": code,
        "message": message,
        "requestId": getattr(request.state, "request_id", str(uuid4())),
    }
    if extra:
        error.update(extra)
    return JSONResponse(
        status_code=status_code,
        content={"error": error},
        headers={"X-Request-ID": error["requestId"]},
    )


app = create_app()
