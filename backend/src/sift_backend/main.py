from dataclasses import replace

from fastapi import FastAPI, HTTPException, Request, status
from pydantic import BaseModel

from sift_backend.api.concepts import build_concept_service
from sift_backend.api.concepts import router as concepts_router
from sift_backend.concepts.service import ConceptService
from sift_backend.config import Settings, load_settings, write_provider_settings
from sift_backend.runtime.providers import (
    build_model_provider_registry,
    build_runtime_model_provider,
    normalize_runtime_provider,
    resolve_runtime_base_url,
    resolve_runtime_model,
)
from sift_backend.runtime.tools import build_web_provider_registry, web_provider_profiles
from sift_backend.runtime.types import RuntimeMessage, RuntimeModelRequest, SiftRuntimeError
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
) -> FastAPI:
    resolved_settings = settings or load_settings()
    app = FastAPI(
        title="Sift Backend",
        version="0.1.0",
        description="Backend API for Sift concept learning notes.",
    )
    app.state.settings = resolved_settings
    app.state.concept_service = concept_service or build_concept_service(resolved_settings)

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", env=_settings(app).env)

    @app.get("/v1/app-status", response_model=AppStatusResponse, response_model_by_alias=True)
    async def app_status() -> AppStatusResponse:
        settings = _settings(app)
        return AppStatusResponse(
            env=settings.env,
            modelProvider=_runtime_provider(settings),
            explainModel=resolve_runtime_model(settings.runtime_provider, settings.runtime_model),
            webSearchEnabled=_effective_web_search_enabled(settings),
            databaseURL=_redacted_database_url(settings.database_url),
            providerBaseURL=resolve_runtime_base_url(
                settings.runtime_provider,
                settings.runtime_base_url,
            ),
            apiKeyConfigured=settings.runtime_api_key != "",
            apiKeyPreview=_api_key_preview(settings.runtime_api_key),
        )

    @app.get(
        "/v1/model-provider-settings",
        response_model=ModelProviderSettingsResponse,
        response_model_by_alias=True,
    )
    async def get_model_provider_settings() -> ModelProviderSettingsResponse:
        return _provider_settings_response(_settings(app))

    @app.get(
        "/v1/runtime/model-providers",
        response_model=RuntimeProviderCatalogResponse,
        response_model_by_alias=True,
    )
    async def list_runtime_model_providers() -> RuntimeProviderCatalogResponse:
        settings = _settings(app)
        return RuntimeProviderCatalogResponse(
            providers=[
                RuntimeProviderOptionDTO(
                    id=profile.name,
                    name=profile.display_name,
                    description=profile.description,
                    adapter=profile.adapter,
                    defaultBaseURL=profile.default_base_url,
                    defaultModel=profile.default_model,
                    requiresApiKey=profile.requires_api_key,
                    supportsModelListing=profile.supports_model_listing,
                    status=profile.status,
                    isAdvanced=profile.is_advanced,
                    configuredBaseURL=settings.runtime_provider_settings.get(
                        profile.name, {}
                    ).get("base_url"),
                    configuredModel=settings.runtime_provider_settings.get(
                        profile.name, {}
                    ).get("model"),
                    apiKeyConfigured=(
                        settings.runtime_provider_settings.get(profile.name, {}).get("api_key", "")
                        != ""
                    ),
                    apiKeyPreview=_api_key_preview(
                        settings.runtime_provider_settings.get(profile.name, {}).get("api_key", "")
                    ),
                )
                for profile in build_model_provider_registry().profiles()
            ]
        )

    @app.get(
        "/v1/runtime/web-providers",
        response_model=WebProviderCatalogResponse,
        response_model_by_alias=True,
    )
    async def list_runtime_web_providers() -> WebProviderCatalogResponse:
        settings = _settings(app)
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
                    apiKeyConfigured=(
                        settings.web_provider_settings.get(profile.name, {}).get(
                            "api_key",
                            "",
                        )
                        != ""
                    ),
                    apiKeyPreview=_api_key_preview(
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
        return _web_provider_settings_response(_settings(app))

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
        return await _run_model_diagnostic(_settings(app))

    @app.post(
        "/v1/web-search-diagnostic",
        response_model=ModelDiagnosticResponse,
        response_model_by_alias=True,
        response_model_exclude_none=True,
    )
    async def web_search_diagnostic() -> ModelDiagnosticResponse:
        return await _run_web_search_diagnostic(_settings(app))

    app.include_router(concepts_router)

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
        response = await provider.complete(
            RuntimeModelRequest(
                model=model,
                messages=(
                    RuntimeMessage(
                        role="user",
                        content="Reply with exactly: ok",
                    ),
                ),
                temperature=0,
            )
        )
    except SiftRuntimeError as error:
        return ModelDiagnosticResponse(
            ok=False,
            provider=provider_name,
            model=model,
            message=str(error),
        )

    return ModelDiagnosticResponse(
        ok=True,
        provider=provider_name,
        model=response.model,
        message="Sift runtime model responded.",
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
                "requires SIFT_WEB_SEARCH_API_KEY."
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
