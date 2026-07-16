import hashlib
import secrets
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sift_backend.auth.principal import CurrentPrincipal
from sift_backend.identity_access.domain import BetaAuthRepository, BetaSession


class BetaAuthError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class IssuedBetaSession:
    token: str
    owner_id: str
    expires_at: datetime


class BetaAuthService:
    def __init__(
        self,
        repository: BetaAuthRepository,
        *,
        token_ttl: timedelta = timedelta(days=30),
        clock: Callable[[], datetime] | None = None,
        token_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self.token_ttl = token_ttl
        self.clock = clock or (lambda: datetime.now(UTC))
        self.token_factory = token_factory or (lambda: secrets.token_urlsafe(32))

    def seed_invites(self, invite_codes: tuple[str, ...]) -> None:
        for code in invite_codes:
            normalized = code.strip()
            if normalized:
                self.repository.seed_invite(_hash_secret(normalized))

    def activate(self, invite_code: str, installation_id: str) -> IssuedBetaSession:
        code = invite_code.strip()
        installation = installation_id.strip()
        if not code or not installation:
            raise BetaAuthError("invite_invalid", "The invite code is invalid.", 400)

        code_hash = _hash_secret(code)
        invite = self.repository.get_invite(code_hash)
        if invite is None or invite.revoked_at is not None:
            raise BetaAuthError("invite_invalid", "The invite code is invalid.", 400)
        if invite.installation_id and invite.installation_id != installation:
            raise BetaAuthError("invite_consumed", "The invite code has already been used.", 409)

        owner_id = invite.owner_id or str(uuid4())
        issued, session = self._new_session(owner_id, installation)
        if invite.owner_id is None:
            consumed = self.repository.consume_invite(
                code_hash,
                owner_id=owner_id,
                installation_id=installation,
                session=session,
            )
            if not consumed:
                current = self.repository.get_invite(code_hash)
                if (
                    current is None
                    or current.owner_id is None
                    or current.installation_id != installation
                ):
                    raise BetaAuthError(
                        "invite_consumed",
                        "The invite code has already been used.",
                        409,
                    )
                issued, session = self._new_session(current.owner_id, installation)
                self.repository.create_session(session)
        else:
            self.repository.create_session(session)
        return issued

    def authenticate(self, token: str, installation_id: str) -> CurrentPrincipal:
        session = self._valid_session(token, installation_id)
        return CurrentPrincipal(
            user_id=session.owner_id,
            auth_method="beta_bearer",
            installation_id=session.installation_id,
        )

    def refresh(self, token: str, installation_id: str) -> IssuedBetaSession:
        session = self._valid_session(token, installation_id)
        issued, replacement = self._new_session(session.owner_id, session.installation_id)
        if not self.repository.replace_session(session.token_hash, replacement):
            raise BetaAuthError("beta_token_revoked", "Beta access has been revoked.", 401)
        return issued

    def revoke_token(self, token: str) -> None:
        self.repository.revoke_token(_hash_secret(token), self.clock())

    def revoke_owner(self, owner_id: str) -> None:
        self.repository.revoke_owner(owner_id, self.clock())

    def _valid_session(self, token: str, installation_id: str) -> BetaSession:
        raw_token = token.strip()
        installation = installation_id.strip()
        if not raw_token or not installation:
            raise BetaAuthError("authentication_required", "Beta activation is required.", 401)
        session = self.repository.get_session(_hash_secret(raw_token))
        if session is None:
            raise BetaAuthError("authentication_required", "Beta activation is required.", 401)
        if session.revoked_at is not None or self.repository.owner_is_revoked(session.owner_id):
            raise BetaAuthError("beta_token_revoked", "Beta access has been revoked.", 401)
        if _as_utc(session.expires_at) <= _as_utc(self.clock()):
            raise BetaAuthError("beta_token_expired", "Beta access has expired.", 401)
        if session.installation_id != installation:
            raise BetaAuthError(
                "beta_token_revoked",
                "Beta access is not valid on this device.",
                401,
            )
        return session

    def _new_session(
        self,
        owner_id: str,
        installation_id: str,
    ) -> tuple[IssuedBetaSession, BetaSession]:
        now = _as_utc(self.clock())
        expires_at = now + self.token_ttl
        token = self.token_factory()
        session = BetaSession(
            id=str(uuid4()),
            token_hash=_hash_secret(token),
            owner_id=owner_id,
            installation_id=installation_id,
            expires_at=expires_at,
            revoked_at=None,
        )
        return IssuedBetaSession(token=token, owner_id=owner_id, expires_at=expires_at), session


def _hash_secret(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
