from uuid import uuid4

from fastapi import APIRouter, Request
from pydantic import Field

from sift_backend.identity_access.service import BetaAuthService
from sift_backend.schemas.base import SiftBaseModel

router = APIRouter(prefix="/v1/beta", tags=["beta-access"])


class ActivateBetaRequest(SiftBaseModel):
    invite_code: str = Field(alias="inviteCode")
    installation_id: str = Field(alias="installationId")


class BetaSessionResponse(SiftBaseModel):
    beta_access_token: str = Field(alias="betaAccessToken")
    owner_id: str = Field(alias="ownerId")
    expires_at: str = Field(alias="expiresAt")


@router.post("/activate", response_model=BetaSessionResponse, response_model_by_alias=True)
async def activate_beta(request: Request, payload: ActivateBetaRequest) -> BetaSessionResponse:
    issued = _service(request).activate(payload.invite_code, payload.installation_id)
    return _response(issued)


@router.post("/session/refresh", response_model=BetaSessionResponse, response_model_by_alias=True)
async def refresh_beta_session(request: Request) -> BetaSessionResponse:
    token = _bearer_token(request)
    installation_id = request.headers.get("X-Sift-Installation", "")
    issued = _service(request).refresh(token, installation_id)
    return _response(issued)


def request_id(request: Request) -> str:
    return request.headers.get("X-Request-ID") or str(uuid4())


def _service(request: Request) -> BetaAuthService:
    return request.app.state.beta_auth_service


def _bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    return token if scheme.lower() == "bearer" else ""


def _response(issued) -> BetaSessionResponse:
    return BetaSessionResponse(
        betaAccessToken=issued.token,
        ownerId=issued.owner_id,
        expiresAt=issued.expires_at.isoformat(),
    )
