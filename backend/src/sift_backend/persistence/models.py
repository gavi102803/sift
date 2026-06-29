from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utc_now() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class ConceptRecord(Base):
    __tablename__ = "concepts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, default="local-dev")
    canonical_title: Mapped[str] = mapped_column(String(255), nullable=False)
    display_title: Mapped[str] = mapped_column(String(255), nullable=False)
    one_line_explanation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    initial_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    maturity: Mapped[str] = mapped_column(String(32), nullable=False)
    capture_status: Mapped[str] = mapped_column(String(32), nullable=False)
    note_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    answer_source_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    blocks: Mapped[list["NoteBlockRecord"]] = relationship(
        back_populates="concept",
        cascade="all, delete-orphan",
        order_by="NoteBlockRecord.position",
    )
    tag_assignments: Mapped[list["ConceptTagRecord"]] = relationship(
        back_populates="concept",
        cascade="all, delete-orphan",
        order_by="ConceptTagRecord.id",
    )
    topic_assignments: Mapped[list["ConceptTopicRecord"]] = relationship(
        back_populates="concept",
        cascade="all, delete-orphan",
        order_by="ConceptTopicRecord.id",
    )
    outgoing_relations: Mapped[list["ConceptRelationRecord"]] = relationship(
        foreign_keys="ConceptRelationRecord.source_concept_id",
        back_populates="source_concept",
        cascade="all, delete-orphan",
        order_by="ConceptRelationRecord.created_at",
    )
    incoming_relations: Mapped[list["ConceptRelationRecord"]] = relationship(
        foreign_keys="ConceptRelationRecord.target_concept_id",
        back_populates="target_concept",
        cascade="all, delete-orphan",
        order_by="ConceptRelationRecord.created_at",
    )


class CaptureAttemptRecord(Base):
    __tablename__ = "capture_attempts"
    __table_args__ = (
        UniqueConstraint("owner_id", "idempotency_key", name="uq_capture_attempt_owner_key"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    raw_capture: Mapped[str] = mapped_column(Text, nullable=False)
    locale: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    concept_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "owner_id",
            "endpoint",
            "idempotency_key",
            name="uq_idempotency_owner_endpoint_key",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    response_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class NoteBlockRecord(Base):
    __tablename__ = "note_blocks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    block_type: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    is_user_locked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    supported_claim_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    concept: Mapped[ConceptRecord] = relationship(back_populates="blocks")


class SourceRecord(Base):
    __tablename__ = "sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class ClaimRecord(Base):
    __tablename__ = "claims"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statement: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_status: Mapped[str] = mapped_column(String(32), nullable=False)
    time_sensitivity: Mapped[str] = mapped_column(String(32), nullable=False)
    source_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    superseded_by_claim_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class LearningStateEntryRecord(Base):
    __tablename__ = "learning_state_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    field: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class NoteRevisionRecord(Base):
    __tablename__ = "note_revisions"
    __table_args__ = (
        UniqueConstraint("concept_id", "revision", name="uq_note_revisions_concept_revision"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    merge_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class UpdateEventRecord(Base):
    __tablename__ = "update_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    proposal_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TagRecord(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    concept_assignments: Mapped[list["ConceptTagRecord"]] = relationship(back_populates="tag")


class ConceptTagRecord(Base):
    __tablename__ = "concept_tags"
    __table_args__ = (UniqueConstraint("concept_id", "tag_id", name="uq_concept_tags"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tags.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")

    concept: Mapped[ConceptRecord] = relationship(back_populates="tag_assignments")
    tag: Mapped[TagRecord] = relationship(back_populates="concept_assignments")


class TopicRecord(Base):
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    concept_assignments: Mapped[list["ConceptTopicRecord"]] = relationship(back_populates="topic")


class ConceptTopicRecord(Base):
    __tablename__ = "concept_topics"
    __table_args__ = (UniqueConstraint("concept_id", "topic_id", name="uq_concept_topics"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    topic_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("topics.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    confidence: Mapped[float] = mapped_column(nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")

    concept: Mapped[ConceptRecord] = relationship(back_populates="topic_assignments")
    topic: Mapped[TopicRecord] = relationship(back_populates="concept_assignments")


class ConceptRelationRecord(Base):
    __tablename__ = "concept_relations"
    __table_args__ = (
        UniqueConstraint(
            "source_concept_id",
            "target_concept_id",
            "relation_type",
            name="uq_concept_relations",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    confidence: Mapped[float] = mapped_column(nullable=False, default=1)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    source_concept: Mapped[ConceptRecord] = relationship(
        foreign_keys=[source_concept_id],
        back_populates="outgoing_relations",
    )
    target_concept: Mapped[ConceptRecord] = relationship(
        foreign_keys=[target_concept_id],
        back_populates="incoming_relations",
    )


class UpdateProposalRecord(Base):
    __tablename__ = "update_proposals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    base_note_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    patch_operations_json: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TurnRecord(Base):
    __tablename__ = "concept_turns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    concept_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    answer_source_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
