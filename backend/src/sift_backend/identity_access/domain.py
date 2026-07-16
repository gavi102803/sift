from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class BetaInvite:
    code_hash: str
    owner_id: str | None
    installation_id: str | None
    revoked_at: datetime | None


@dataclass(frozen=True)
class BetaSession:
    id: str
    token_hash: str
    owner_id: str
    installation_id: str
    expires_at: datetime
    revoked_at: datetime | None


class BetaAuthRepository(Protocol):
    def seed_invite(self, code_hash: str) -> None:
        ...

    def get_invite(self, code_hash: str) -> BetaInvite | None:
        ...

    def consume_invite(
        self,
        code_hash: str,
        *,
        owner_id: str,
        installation_id: str,
        session: BetaSession,
    ) -> bool:
        ...

    def create_session(self, session: BetaSession) -> None:
        ...

    def get_session(self, token_hash: str) -> BetaSession | None:
        ...

    def replace_session(self, old_token_hash: str, session: BetaSession) -> bool:
        ...

    def revoke_token(self, token_hash: str, revoked_at: datetime) -> None:
        ...

    def revoke_owner(self, owner_id: str, revoked_at: datetime) -> None:
        ...

    def owner_is_revoked(self, owner_id: str) -> bool:
        ...
