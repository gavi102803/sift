from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import timedelta

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session, sessionmaker

from sift_backend.api.concepts import build_concept_service
from sift_backend.api.concepts import router as concepts_router
from sift_backend.api.model_runs import router as model_runs_router
from sift_backend.auth.principal import DevelopmentPrincipalProvider
from sift_backend.concepts.service import ConceptService, InMemoryConceptStore
from sift_backend.config import Settings, load_settings, write_provider_settings
from sift_backend.identity_access.api import router as beta_router
from sift_backend.identity_access.persistence import SqlAlchemyBetaAuthRepository
from sift_backend.identity_access.service import BetaAuthError, BetaAuthService
from sift_backend.model_runtime.model_runs import ModelRunCoordinator, ModelRunRepository
from sift_backend.persistence.database import create_session_factory
from sift_backend.runtime.capability_probe import probe_model_capabilities
from sift_backend.runtime.managed_api import ManagedProviderError
from sift_backend.runtime.managed_api import router as managed_runtime_router
from sift_backend.runtime.managed_connections import ManagedProviderConnectionRepository
from sift_backend.runtime.providers import (
    build_model_provider_registry,
    build_runtime_model_provider,
    normalize_runtime_provider,
    resolve_runtime_base_url,
    resolve_runtime_model,
)
from sift_backend.runtime.tools import build_web_provider_registry, web_provider_profiles
from sift_backend.runtime.types import SiftRuntimeError
from sift_backend.schemas.app_status import (
    AppStatusResponse,
    ModelDiagnosticResponse,
    ModelProviderSettingsResponse,
    ProviderModelDTO,
    ProviderModelListResponse,
    RuntimeProviderCatalogResponse,
    RuntimeProviderOptionDTO,
    UpdateModelProviderSettingsRequest,
    UpdateWebProviderSettingsRequest,
    WebProviderCatalogResponse,
    WebProviderOptionDTO,
    WebProviderSettingsResponse,
)


class HealthResponse(BaseModel):
    status: str
    env: str


def create_app(
    settings: Settings | None = None,
    concept_service: ConceptService | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    resolved_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        application.state.model_run_coordinator.start()
        try:
            yield
        finally:
            await application.state.model_run_coordinator.stop()

    app = FastAPI(
        title="Sift Backend",
        version="0.1.0",
        description="Backend API for Sift concept learning notes.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.concept_service = concept_service or build_concept_service(resolved_settings)
    if session_factory is not None:
        database_sessions = session_factory
    elif isinstance(app.state.concept_service.store, InMemoryConceptStore):
        database_sessions = create_session_factory("sqlite://")
    else:
        database_sessions = create_session_factory(
            resolved_settings.database_url,
            initialize_schema=resolved_settings.env != "production",
        )
    beta_repository = SqlAlchemyBetaAuthRepository(database_sessions)
    beta_auth_service = BetaAuthService(
        beta_repository,
        token_ttl=timedelta(days=resolved_settings.beta_token_ttl_days),
    )
    beta_auth_service.seed_invites(resolved_settings.beta_invite_codes)
    app.state.beta_auth_service = beta_auth_service
    app.state.managed_provider_connections = ManagedProviderConnectionRepository(
        database_sessions
    )
    app.state.model_run_repository = ModelRunRepository(database_sessions)
    app.state.model_run_coordinator = ModelRunCoordinator(
        app.state.model_run_repository,
        app.state.concept_service,
        managed=resolved_settings.auth_mode == "managed",
    )

    @app.exception_handler(BetaAuthError)
    async def beta_auth_error_handler(request: Request, error: BetaAuthError) -> JSONResponse:
        return _auth_error_response(
            error,
            getattr(request.state, "request_id", _new_request_id()),
        )

    @app.exception_handler(ManagedProviderError)
    async def managed_provider_error_handler(
        request: Request,
        error: ManagedProviderError,
    ) -> JSONResponse:
        return _public_error_response(
            error.code,
            error.message,
            error.status_code,
            getattr(request.state, "request_id", _new_request_id()),
        )

    @app.exception_handler(HTTPException)
    async def http_error_handler(request: Request, error: HTTPException) -> JSONResponse:
        if resolved_settings.auth_mode != "managed":
            return JSONResponse(
                status_code=error.status_code,
                content={"detail": error.detail},
                headers=error.headers,
            )
        code, message = _managed_http_error(error)
        return _public_error_response(
            code,
            message,
            error.status_code,
            getattr(request.state, "request_id", _new_request_id()),
        )

    @app.middleware("http")
    async def authenticate_request(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or _new_request_id()
        request.state.request_id = request_id
        if resolved_settings.auth_mode == "development":
            request.state.principal = DevelopmentPrincipalProvider(
                resolved_settings.user_id
            ).current_principal()
        elif request.url.path not in {"/health", "/v1/beta/activate"}:
            try:
                request.state.principal = beta_auth_service.authenticate(
                    _bearer_token(request),
                    request.headers.get("X-Sift-Installation", ""),
                )
            except BetaAuthError as error:
                return _auth_error_response(error, request_id)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", env=_settings(app).env)

    @app.get("/v1/app-status", response_model=AppStatusResponse, response_model_by_alias=True)
    async def app_status() -> AppStatusResponse:
        settings = _settings(app)
        managed = settings.auth_mode == "managed"
        return AppStatusResponse(
            env=settings.env,
            modelProvider="managed-byok" if managed else _runtime_provider(settings),
            explainModel="per-owner" if managed else resolve_runtime_model(
                settings.runtime_provider, settings.runtime_model
            ),
            webSearchEnabled=_effective_web_search_enabled(settings),
            databaseURL="managed" if managed else _redacted_database_url(settings.database_url),
            providerBaseURL=None if managed else resolve_runtime_base_url(
                settings.runtime_provider,
                settings.runtime_base_url,
            ),
            apiKeyConfigured=False if managed else settings.runtime_api_key != "",
            apiKeyPreview=None if managed else _api_key_preview(settings.runtime_api_key),
        )

    @app.get(
        "/v1/model-provider-settings",
        response_model=ModelProviderSettingsResponse,
        response_model_by_alias=True,
    )
    async def get_model_provider_settings() -> ModelProviderSettingsResponse:
        settings = _settings(app)
        _require_personal_settings(settings)
        return _provider_settings_response(settings)

    @app.get(
        "/v1/runtime/model-providers",
        response_model=RuntimeProviderCatalogResponse,
        response_model_by_alias=True,
    )
    async def list_runtime_model_providers() -> RuntimeProviderCatalogResponse:
        settings = _settings(app)
        managed = settings.auth_mode == "managed"
        return RuntimeProviderCatalogResponse(
            providers=[
                RuntimeProviderOptionDTO(
                    id=profile.name,
                    name=profile.display_name,
                    description=profile.description,
                    adapter=profile.adapter,
                    apiMode=profile.api_mode,
                    protocolDriver=profile.protocol_driver,
                    hermesPluginPath=profile.hermes_plugin_path,
                    exposureTier=profile.exposure_tier,
                    defaultBaseURL=profile.default_base_url,
                    defaultModel=profile.default_model,
                    requiresApiKey=profile.requires_api_key,
                    supportsModelListing=profile.supports_model_listing,
                    status=profile.status,
                    isAdvanced=profile.is_advanced,
                    configuredBaseURL=None if managed else settings.runtime_provider_settings.get(
                        profile.name, {}
                    ).get("base_url"),
                    configuredModel=None if managed else settings.runtime_provider_settings.get(
                        profile.name, {}
                    ).get("model"),
                    apiKeyConfigured=False if managed else (
                        settings.runtime_provider_settings.get(profile.name, {}).get("api_key", "")
                        != ""
                    ),
                    apiKeyPreview=None if managed else _api_key_preview(
                        settings.runtime_provider_settings.get(profile.name, {}).get("api_key", "")
                    ),
                )
                for profile in build_model_provider_registry().profiles()
                if profile.exposure_tier != "hidden"
            ]
        )

    @app.get(
        "/v1/runtime/web-providers",
        response_model=WebProviderCatalogResponse,
        response_model_by_alias=True,
    )
    async def list_runtime_web_providers() -> WebProviderCatalogResponse:
        settings = _settings(app)
        managed = settings.auth_mode == "managed"
        return WebProviderCatalogResponse(
            providers=[
                WebProviderOptionDTO(
                    id=profile.name,
                    name=profile.display_name,
                    description=profile.description,
                    requiresApiKey=profile.requires_api_key,
                    supportsSearch=profile.supports_search,
                    supportsExtract=profile.supports_extract,
                    status=profile.status,
                    isDefault=profile.is_default,
                    apiKeyConfigured=False if managed else (
                        settings.web_provider_settings.get(profile.name, {}).get(
                            "api_key",
                            "",
                        )
                        != ""
                    ),
                    apiKeyPreview=None if managed else _api_key_preview(
                        settings.web_provider_settings.get(profile.name, {}).get("api_key", "")
                    ),
                )
                for profile in web_provider_profiles()
            ]
        )

    @app.put(
        "/v1/model-provider-settings",
        response_model=ModelProviderSettingsResponse,
        response_model_by_alias=True,
    )
    async def update_model_provider_settings(
        request: Request,
        payload: UpdateModelProviderSettingsRequest,
    ) -> ModelProviderSettingsResponse:
        current = _settings(request.app)
        _require_personal_settings(current)
        try:
            provider_type = _normalize_runtime_provider(payload.provider_type)
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error
        registry = build_model_provider_registry()
        try:
            registry.profile(provider_type)
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(error),
            ) from error
        api_key = payload.api_key.strip() if payload.api_key is not None else None
        base_url = resolve_runtime_base_url(provider_type, payload.base_url)
        if provider_type != "mock" and not base_url:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Runtime base URL cannot be empty.",
            )
        explain_model = resolve_runtime_model(provider_type, payload.explain_model)
        provider_settings = {
            key: dict(value)
            for key, value in current.runtime_provider_settings.items()
        }
        provider_config = dict(provider_settings.get(provider_type, {}))
        provider_config["base_url"] = base_url
        provider_config["model"] = explain_model
        provider_config["api_key"] = (
            api_key if api_key is not None else provider_config.get("api_key", "")
        )
        provider_settings[provider_type] = provider_config

        updated = replace(
            current,
            runtime_provider=provider_type,
            runtime_base_url=base_url if provider_type != "mock" else current.runtime_base_url,
            runtime_api_key=provider_config.get("api_key", ""),
            runtime_model=explain_model,
            runtime_web_search_enabled=payload.web_search_enabled,
            runtime_provider_settings=provider_settings,
        )
        write_provider_settings(updated)
        request.app.state.settings = updated
        request.app.state.concept_service = build_concept_service(updated)
        return _provider_settings_response(updated)

    @app.get(
        "/v1/web-provider-settings",
        response_model=WebProviderSettingsResponse,
        response_model_by_alias=True,
    )
    async def get_web_provider_settings() -> WebProviderSettingsResponse:
        settings = _settings(app)
        _require_personal_settings(settings)
        return _web_provider_settings_response(settings)

    @app.put(
        "/v1/web-provider-settings",
        response_model=WebProviderSettingsResponse,
        response_model_by_alias=True,
    )
    async def update_web_provider_settings(
        request: Request,
        payload: UpdateWebProviderSettingsRequest,
    ) -> WebProviderSettingsResponse:
        current = _settings(request.app)
        _require_personal_settings(current)
        provider_type = payload.provider_type.strip().lower()
        known_provider_names = {profile.name for profile in web_provider_profiles()}
        if provider_type not in known_provider_names:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unsupported web provider.",
            )
        available_provider_names = set(
            build_web_provider_registry(tavily_api_key=current.web_search_api_key).available_names()
        )
        if provider_type not in available_provider_names:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Web provider is listed from Hermes upstream but not "
                    "implemented in Sift yet."
                ),
            )
        api_key = payload.api_key.strip() if payload.api_key is not None else None
        web_settings = {
            key: dict(value)
            for key, value in current.web_provider_settings.items()
        }
        web_config = dict(web_settings.get(provider_type, {}))
        web_config["api_key"] = api_key if api_key is not None else web_config.get("api_key", "")
        web_settings[provider_type] = web_config
        updated = replace(
            current,
            runtime_web_search_enabled=payload.web_search_enabled,
            web_search_provider=provider_type,
            web_search_api_key=web_config.get("api_key", ""),
            web_provider_settings=web_settings,
        )
        write_provider_settings(updated)
        request.app.state.settings = updated
        request.app.state.concept_service = build_concept_service(updated)
        return _web_provider_settings_response(updated)

    @app.get(
        "/v1/model-provider-settings/models",
        response_model=ProviderModelListResponse,
        response_model_by_alias=True,
    )
    async def list_provider_models(request: Request) -> ProviderModelListResponse:
        settings = _settings(request.app)
        _require_personal_settings(settings)
        if not settings.runtime_api_key or settings.runtime_provider == "mock":
            return ProviderModelListResponse(models=[])
        provider = build_runtime_model_provider(
            settings.runtime_provider,
            base_url=settings.runtime_base_url,
            api_key=settings.runtime_api_key,
            timeout=20,
        )
        try:
            models = await provider.list_models()
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error
        models = _filter_runtime_models(
            models,
            provider_name=settings.runtime_provider,
            preferred_model=resolve_runtime_model(
                settings.runtime_provider,
                settings.runtime_model,
            ),
        )
        return ProviderModelListResponse(
            models=[
                ProviderModelDTO(id=model, ownedBy=_runtime_provider(settings))
                for model in models
            ]
        )

    @app.post(
        "/v1/model-diagnostic",
        response_model=ModelDiagnosticResponse,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def model_diagnostic() -> ModelDiagnosticResponse:
        settings = _settings(app)
        _require_personal_settings(settings)
        return await _run_model_diagnostic(settings)

    @app.post(
        "/v1/web-search-diagnostic",
        response_model=ModelDiagnosticResponse,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def web_search_diagnostic() -> ModelDiagnosticResponse:
        settings = _settings(app)
        _require_personal_settings(settings)
        return await _run_web_search_diagnostic(settings)

    app.include_router(beta_router)
    app.include_router(managed_runtime_router)
    app.include_router(concepts_router)
    app.include_router(model_runs_router)

    return app


def _runtime_provider(settings: Settings) -> str:
    if settings.runtime_provider == "mock" or not settings.runtime_api_key:
        return "mock"
    try:
        return normalize_runtime_provider(settings.runtime_provider)
    except SiftRuntimeError:
        return settings.runtime_provider


def _settings(app: FastAPI) -> Settings:
    return app.state.settings


def _require_personal_settings(settings: Settings) -> None:
    if settings.auth_mode == "managed":
        raise ManagedProviderError(
            "managed_unsupported",
            "This endpoint is not available in the managed beta.",
            status.HTTP_404_NOT_FOUND,
        )


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" else ""


def _auth_error_response(error: BetaAuthError, request_id: str) -> JSONResponse:
    return _public_error_response(error.code, error.message, error.status_code, request_id)


def _public_error_response(
    code: str,
    message: str,
    status_code: int,
    request_id: str,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "requestId": request_id,
            }
        },
        headers={"X-Request-ID": request_id},
    )


def _managed_http_error(error: HTTPException) -> tuple[str, str]:
    detail_code = error.detail.get("code") if isinstance(error.detail, dict) else None
    if error.status_code == status.HTTP_404_NOT_FOUND:
        return "owner_scope_not_found", "Resource not found."
    if error.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
        if detail_code in {"provider_error", "provider_timeout"}:
            return "provider_unreachable", "The AI provider could not be reached."
        return "backend_unavailable", "Sift is temporarily unavailable."
    if error.status_code == status.HTTP_409_CONFLICT:
        return detail_code or "request_conflict", "The request conflicts with current state."
    if error.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY:
        return detail_code or "invalid_request", "The request is invalid."
    return detail_code or "request_rejected", "The request was rejected."


def _new_request_id() -> str:
    from uuid import uuid4

    return str(uuid4())


def _effective_web_search_enabled(settings: Settings) -> bool:
    return settings.runtime_web_search_enabled


def _api_key_preview(api_key: str) -> str | None:
    if not api_key:
        return None
    return f"***{api_key[-4:]}"


def _provider_settings_response(settings: Settings) -> ModelProviderSettingsResponse:
    return ModelProviderSettingsResponse(
        providerType=normalize_runtime_provider(settings.runtime_provider),
        baseURL=resolve_runtime_base_url(settings.runtime_provider, settings.runtime_base_url),
        apiKeyConfigured=settings.runtime_api_key != "",
        apiKeyPreview=_api_key_preview(settings.runtime_api_key),
        explainModel=resolve_runtime_model(settings.runtime_provider, settings.runtime_model),
        webSearchEnabled=_effective_web_search_enabled(settings),
        supportsWebSearch=True,
    )


def _web_provider_settings_response(settings: Settings) -> WebProviderSettingsResponse:
    return WebProviderSettingsResponse(
        providerType=settings.web_search_provider,
        apiKeyConfigured=settings.web_search_api_key != "",
        apiKeyPreview=_api_key_preview(settings.web_search_api_key),
        webSearchEnabled=settings.runtime_web_search_enabled,
    )


def _redacted_database_url(database_url: str) -> str:
    if "://" not in database_url or "@" not in database_url:
        return database_url
    scheme, rest = database_url.split("://", 1)
    _, host = rest.rsplit("@", 1)
    return f"{scheme}://***@{host}"


def _filter_runtime_models(
    models: list[str],
    *,
    provider_name: str,
    preferred_model: str,
) -> list[str]:
    unique_models = _dedupe_models(models)
    filtered = [
        model
        for model in unique_models
        if _looks_like_chat_runtime_model(model, provider_name=provider_name)
    ]
    if not filtered:
        filtered = unique_models
    return sorted(
        filtered,
        key=lambda model: (
            model != preferred_model,
            _model_sort_rank(model),
            model.casefold(),
        ),
    )


def _dedupe_models(models: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for raw_model in models:
        model = raw_model.strip()
        if not model:
            continue
        key = model.casefold()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(model)
    return deduped


def _looks_like_chat_runtime_model(model: str, *, provider_name: str) -> bool:
    lowered = model.casefold()
    blocked_fragments = (
        "embedding",
        "embed",
        "audio",
        "transcribe",
        "tts",
        "whisper",
        "image",
        "vision-preview",
        "moderation",
        "omni-moderation",
        "rerank",
        "search-preview",
        "search-api",
        "dall-e",
        "realtime",
        "instruct",
        "test",
        "eval",
        "codex",
        "deep-research",
    )
    if any(fragment in lowered for fragment in blocked_fragments):
        return False
    if provider_name in {"openai", "custom"}:
        if not lowered.startswith(("gpt-", "o")):
            return False
        if _has_dated_model_suffix(lowered):
            return False
    return True


def _model_sort_rank(model: str) -> int:
    lowered = model.casefold()
    if lowered.startswith("gpt-5"):
        return 0
    if lowered.startswith("gpt-4.1") or lowered.startswith("gpt-4o"):
        return 1
    if lowered.startswith("o"):
        return 2
    return 10


def _has_dated_model_suffix(model: str) -> bool:
    parts = model.rsplit("-", maxsplit=3)
    if len(parts) < 4:
        return False
    year, month, day = parts[-3:]
    return (
        len(year) == 4
        and len(month) == 2
        and len(day) == 2
        and year.isdigit()
        and month.isdigit()
        and day.isdigit()
    )


async def _run_model_diagnostic(settings: Settings) -> ModelDiagnosticResponse:
    provider_name = _runtime_provider(settings)
    if provider_name == "mock":
        return ModelDiagnosticResponse(
            ok=True,
            provider=provider_name,
            model="mock-runtime",
            message="No runtime key configured; mock runtime is active.",
        )

    provider = build_runtime_model_provider(
        provider_name,
        base_url=settings.runtime_base_url,
        api_key=settings.runtime_api_key,
        timeout=20,
    )
    model = resolve_runtime_model(settings.runtime_provider, settings.runtime_model)
    try:
        probe = await probe_model_capabilities(
            provider,
            provider_name=provider_name,
            model=model,
        )
    except SiftRuntimeError as error:
        return ModelDiagnosticResponse(
            ok=False,
            provider=provider_name,
            model=model,
            message=str(error),
        )
    except Exception as error:
        return ModelDiagnosticResponse(
            ok=False,
            provider=provider_name,
            model=model,
            message=f"Capability probe failed: {error}",
        )

    if not probe.plain_completion.ok:
        return ModelDiagnosticResponse(
            ok=False,
            provider=provider_name,
            model=model,
            message=probe.plain_completion.message,
        )

    return ModelDiagnosticResponse(
        ok=True,
        provider=provider_name,
        model=model,
        message=(
            "Sift runtime model responded. "
            f"Structured output: {probe.selected_structured_output or 'unavailable'}."
        ),
    )


async def _run_web_search_diagnostic(settings: Settings) -> ModelDiagnosticResponse:
    if not settings.runtime_web_search_enabled:
        return ModelDiagnosticResponse(
            ok=False,
            provider=_runtime_provider(settings),
            model=settings.runtime_model,
            message="Runtime web search is disabled.",
        )
    if settings.web_search_provider == "disabled":
        return ModelDiagnosticResponse(
            ok=False,
            provider=_runtime_provider(settings),
            model=settings.runtime_model,
            message="Runtime web search is enabled but no search tool provider is configured.",
        )
    registry = build_web_provider_registry(tavily_api_key=settings.web_search_api_key)
    try:
        web_provider = registry.create(settings.web_search_provider)
    except SiftRuntimeError as error:
        return ModelDiagnosticResponse(
            ok=False,
            provider=_runtime_provider(settings),
            model=settings.runtime_model,
            message=str(error),
        )
    provider_profile = next(
        (
            profile
            for profile in web_provider_profiles()
            if profile.name == settings.web_search_provider
        ),
        None,
    )
    if provider_profile and provider_profile.requires_api_key and not settings.web_search_api_key:
        return ModelDiagnosticResponse(
            ok=False,
            provider=_runtime_provider(settings),
            model=settings.runtime_model,
            message=(
                f"Runtime web search provider {settings.web_search_provider} "
                "requires an API key configured from Profile."
            ),
        )
    if not web_provider.is_available():
        return ModelDiagnosticResponse(
            ok=False,
            provider=_runtime_provider(settings),
            model=settings.runtime_model,
            message=f"Runtime web search provider {settings.web_search_provider} is unavailable.",
        )
    return ModelDiagnosticResponse(
        ok=True,
        provider=_runtime_provider(settings),
        model=settings.runtime_model,
        message=f"Runtime web search tool configured: {settings.web_search_provider}.",
        webSearchUsed=False,
        citationCount=0,
    )


def _normalize_runtime_provider(provider_type: str) -> str:
    registry = build_model_provider_registry()
    normalized = registry.normalize(provider_type)
    registry.profile(normalized)
    return normalized


app = create_app()
