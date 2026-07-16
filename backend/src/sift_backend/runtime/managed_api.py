from fastapi import APIRouter, Request
from pydantic import Field

from sift_backend.runtime.managed_connections import ManagedProviderConnection
from sift_backend.runtime.providers import (
    build_model_provider_registry,
    build_runtime_model_provider,
)
from sift_backend.runtime.types import RuntimeMessage, RuntimeModelRequest, SiftRuntimeError
from sift_backend.schemas.base import SiftBaseModel

router = APIRouter(prefix="/v1", tags=["managed-runtime"])


class ManagedProviderError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


class ProviderConnectionRequest(SiftBaseModel):
    provider_id: str = Field(alias="providerId")
    base_url: str | None = Field(default=None, alias="baseURL")
    model: str


class ProviderConnectionResponse(SiftBaseModel):
    provider_id: str = Field(alias="providerId")
    base_url: str = Field(alias="baseURL")
    model: str


class ProviderTestResponse(SiftBaseModel):
    ok: bool


@router.get(
    "/provider-connection",
    response_model=ProviderConnectionResponse,
    response_model_by_alias=True,
)
async def get_provider_connection(request: Request) -> ProviderConnectionResponse:
    connection = _repository(request).get(_owner_id(request))
    if connection is None:
        raise ManagedProviderError(
            "provider_not_configured",
            "Connect an AI provider before continuing.",
            404,
        )
    return _response(connection)


@router.put(
    "/provider-connection",
    response_model=ProviderConnectionResponse,
    response_model_by_alias=True,
)
async def put_provider_connection(
    request: Request,
    payload: ProviderConnectionRequest,
) -> ProviderConnectionResponse:
    connection = _validated_connection(request, payload)
    return _response(_repository(request).save(connection))


@router.post(
    "/providers/test",
    response_model=ProviderTestResponse,
    response_model_by_alias=True,
)
async def test_provider_connection(
    request: Request,
    payload: ProviderConnectionRequest,
) -> ProviderTestResponse:
    api_key = _provider_key(request)
    connection = _validated_connection(request, payload)
    provider = build_runtime_model_provider(
        connection.provider_id,
        base_url=connection.base_url,
        api_key=api_key,
        timeout=15,
    )
    try:
        await provider.complete(
            RuntimeModelRequest(
                model=connection.model,
                messages=(RuntimeMessage(role="user", content="Reply with exactly: ok"),),
            )
        )
    except SiftRuntimeError as error:
        raise _safe_provider_error(error) from error
    _repository(request).save(connection)
    return ProviderTestResponse(ok=True)


def require_managed_provider_connection(request: Request) -> tuple[ManagedProviderConnection, str]:
    connection = _repository(request).get(_owner_id(request))
    if connection is None:
        raise ManagedProviderError(
            "provider_not_configured",
            "Connect an AI provider before continuing.",
            409,
        )
    return connection, _provider_key(request)


def _validated_connection(
    request: Request,
    payload: ProviderConnectionRequest,
) -> ManagedProviderConnection:
    registry = build_model_provider_registry()
    provider_id = registry.normalize(payload.provider_id)
    try:
        profile = registry.profile(provider_id)
    except SiftRuntimeError as error:
        raise ManagedProviderError(
            "provider_unreachable",
            "The selected provider is not supported.",
            502,
        ) from error
    if profile.exposure_tier == "hidden" or profile.adapter == "mock":
        raise ManagedProviderError(
            "provider_unreachable",
            "The selected provider is not available for the beta.",
            502,
        )
    base_url = registry.resolve_base_url(provider_id, payload.base_url or "")
    model = registry.resolve_model(provider_id, payload.model)
    return ManagedProviderConnection(
        owner_id=_owner_id(request),
        provider_id=provider_id,
        base_url=base_url,
        model=model,
    )


def _provider_key(request: Request) -> str:
    key = request.headers.get("X-Sift-Provider-Key", "").strip()
    if not key:
        raise ManagedProviderError(
            "invalid_provider_key",
            "Check your provider API key.",
            401,
        )
    return key


def _safe_provider_error(error: SiftRuntimeError) -> ManagedProviderError:
    if error.code == "provider_timeout":
        return ManagedProviderError(
            "provider_unreachable",
            "The provider did not respond. Try again.",
            502,
        )
    return ManagedProviderError(
        "invalid_provider_key",
        "The provider rejected the connection. Check the API key and model.",
        401,
    )


def _owner_id(request: Request) -> str:
    return request.state.principal.user_id


def _repository(request: Request):
    return request.app.state.managed_provider_connections


def _response(connection: ManagedProviderConnection) -> ProviderConnectionResponse:
    return ProviderConnectionResponse(
        providerId=connection.provider_id,
        baseURL=connection.base_url,
        model=connection.model,
    )
