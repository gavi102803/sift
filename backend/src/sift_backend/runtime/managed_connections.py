from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from sift_backend.persistence.models import Base, utc_now


@dataclass(frozen=True)
class ManagedProviderConnection:
    owner_id: str
    provider_id: str
    base_url: str
    model: str


class ManagedProviderConnectionRecord(Base):
    __tablename__ = "managed_provider_connections"

    owner_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(512), nullable=False)
    model: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class ManagedProviderConnectionRepository:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory

    def get(self, owner_id: str) -> ManagedProviderConnection | None:
        with self.session_factory() as session:
            record = session.get(ManagedProviderConnectionRecord, owner_id)
            if record is None:
                return None
            return ManagedProviderConnection(
                owner_id=record.owner_id,
                provider_id=record.provider_id,
                base_url=record.base_url,
                model=record.model,
            )

    def save(self, connection: ManagedProviderConnection) -> ManagedProviderConnection:
        with self.session_factory.begin() as session:
            record = session.get(ManagedProviderConnectionRecord, connection.owner_id)
            if record is None:
                record = ManagedProviderConnectionRecord(owner_id=connection.owner_id)
                session.add(record)
            record.provider_id = connection.provider_id
            record.base_url = connection.base_url
            record.model = connection.model
        return connection
