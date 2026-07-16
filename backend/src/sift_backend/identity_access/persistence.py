from datetime import datetime

from sqlalchemy import DateTime, String, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from sift_backend.identity_access.domain import BetaInvite, BetaSession
from sift_backend.persistence.models import Base, utc_now


class BetaOwnerRecord(Base):
    __tablename__ = "beta_owners"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class BetaInviteRecord(Base):
    __tablename__ = "beta_invites"

    code_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    owner_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    installation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class BetaSessionRecord(Base):
    __tablename__ = "beta_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    installation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class SqlAlchemyBetaAuthRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def seed_invite(self, code_hash: str) -> None:
        with self.session_factory.begin() as session:
            if session.get(BetaInviteRecord, code_hash) is None:
                session.add(BetaInviteRecord(code_hash=code_hash))

    def get_invite(self, code_hash: str) -> BetaInvite | None:
        with self.session_factory() as session:
            record = session.get(BetaInviteRecord, code_hash)
            return _invite(record) if record else None

    def consume_invite(
        self,
        code_hash: str,
        *,
        owner_id: str,
        installation_id: str,
        session: BetaSession,
    ) -> bool:
        with self.session_factory.begin() as database:
            invite = database.scalar(
                select(BetaInviteRecord)
                .where(BetaInviteRecord.code_hash == code_hash)
                .with_for_update()
            )
            if invite is None or invite.owner_id is not None:
                return False
            database.add(BetaOwnerRecord(id=owner_id))
            invite.owner_id = owner_id
            invite.installation_id = installation_id
            invite.consumed_at = utc_now()
            database.add(_session_record(session))
        return True

    def create_session(self, session: BetaSession) -> None:
        with self.session_factory.begin() as database:
            database.add(_session_record(session))

    def get_session(self, token_hash: str) -> BetaSession | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(BetaSessionRecord).where(BetaSessionRecord.token_hash == token_hash)
            )
            return _session(record) if record else None

    def replace_session(self, old_token_hash: str, session: BetaSession) -> bool:
        with self.session_factory.begin() as database:
            old = database.scalar(
                select(BetaSessionRecord).where(
                    BetaSessionRecord.token_hash == old_token_hash
                ).with_for_update()
            )
            if old is None or old.revoked_at is not None:
                return False
            old.revoked_at = utc_now()
            database.add(_session_record(session))
        return True

    def revoke_token(self, token_hash: str, revoked_at: datetime) -> None:
        with self.session_factory.begin() as session:
            session.execute(
                update(BetaSessionRecord)
                .where(BetaSessionRecord.token_hash == token_hash)
                .values(revoked_at=revoked_at)
            )

    def revoke_owner(self, owner_id: str, revoked_at: datetime) -> None:
        with self.session_factory.begin() as session:
            owner = session.get(BetaOwnerRecord, owner_id)
            if owner is not None:
                owner.revoked_at = revoked_at
            session.execute(
                update(BetaSessionRecord)
                .where(BetaSessionRecord.owner_id == owner_id)
                .values(revoked_at=revoked_at)
            )

    def owner_is_revoked(self, owner_id: str) -> bool:
        with self.session_factory() as session:
            owner = session.get(BetaOwnerRecord, owner_id)
            return owner is None or owner.revoked_at is not None


def _invite(record: BetaInviteRecord) -> BetaInvite:
    return BetaInvite(
        code_hash=record.code_hash,
        owner_id=record.owner_id,
        installation_id=record.installation_id,
        revoked_at=record.revoked_at,
    )


def _session(record: BetaSessionRecord) -> BetaSession:
    return BetaSession(
        id=record.id,
        token_hash=record.token_hash,
        owner_id=record.owner_id,
        installation_id=record.installation_id,
        expires_at=record.expires_at,
        revoked_at=record.revoked_at,
    )


def _session_record(session: BetaSession) -> BetaSessionRecord:
    return BetaSessionRecord(
        id=session.id,
        token_hash=session.token_hash,
        owner_id=session.owner_id,
        installation_id=session.installation_id,
        expires_at=session.expires_at,
        revoked_at=session.revoked_at,
    )
