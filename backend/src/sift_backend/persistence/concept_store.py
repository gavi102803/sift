import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, status
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sift_backend.ai.context_pack import RecentTurn
from sift_backend.concepts.service import CaptureAttemptDTO, IdempotencyRecordDTO
from sift_backend.persistence.models import (
    CaptureAttemptRecord,
    ClaimRecord,
    ConceptContinuitySummaryRecord,
    ConceptRecord,
    ConceptRelationRecord,
    ConceptTagRecord,
    ConceptTopicRecord,
    IdempotencyRecord,
    LearningStateEntryRecord,
    NoteBlockRecord,
    NoteRevisionRecord,
    SourceRecord,
    TagRecord,
    TopicRecord,
    TurnRecord,
    UpdateEventRecord,
    UpdateProposalRecord,
)
from sift_backend.schemas.common import (
    CaptureStatus,
    ClaimType,
    ConceptMaturity,
    EvidenceStatus,
    LearningStateField,
    LearningStateOrigin,
    NoteBlockSource,
    NoteBlockType,
    ProposalStatus,
    SourceType,
    TimeSensitivity,
)
from sift_backend.schemas.concepts import (
    AnswerSourceDTO,
    ClaimDTO,
    ConceptDTO,
    ConceptRelationDTO,
    LearningStateDTO,
    LearningStateEntryDTO,
    LearningStateUpdateDTO,
    NoteBlockDTO,
    NoteRevisionDTO,
    NoteRevisionSummaryDTO,
    SourceDTO,
    UpdateProposalDTO,
)
from sift_backend.schemas.patches import PatchOperation

patch_operations_adapter = TypeAdapter(list[PatchOperation])


class PersistentConceptStore:
    """SQLAlchemy-backed concept store for local MVP persistence."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self.session_factory = session_factory
        self._transaction_session: ContextVar[Session | None] = ContextVar(
            f"concept-store-session-{id(self)}",
            default=None,
        )

    @contextmanager
    def transaction(self, session: Session) -> Iterator[None]:
        """Join store operations to a caller-owned transaction."""
        current = self._transaction_session.get()
        if current is not None and current is not session:
            raise RuntimeError("Concept store is already bound to another transaction.")
        token = self._transaction_session.set(session)
        try:
            yield
        finally:
            self._transaction_session.reset(token)

    @contextmanager
    def _session(self) -> Iterator[Session]:
        current = self._transaction_session.get()
        if current is not None:
            yield current
            return
        with self.session_factory() as session:
            yield session

    def _commit(self, session: Session) -> None:
        if self._transaction_session.get() is not session:
            session.commit()

    def save_concept(self, concept: ConceptDTO, owner_id: str | None = None) -> ConceptDTO:
        with self._session() as session:
            record = session.get(ConceptRecord, str(concept.id))
            if record is None:
                record = ConceptRecord(id=str(concept.id))
                session.add(record)

            if owner_id is not None:
                record.owner_id = owner_id
            elif not record.owner_id:
                record.owner_id = "local-dev"
            record.canonical_title = concept.canonical_title
            record.display_title = concept.display_title
            record.one_line_explanation = concept.one_line_explanation
            record.initial_answer = concept.initial_answer
            record.maturity = concept.maturity.value
            record.capture_status = concept.capture_status.value
            record.note_revision = concept.note_revision
            record.answer_source_json = (
                concept.answer_source.model_dump_json(by_alias=True)
                if concept.answer_source is not None
                else None
            )
            record.blocks = [
                _note_block_to_record(block, concept.id, position)
                for position, block in enumerate(concept.blocks)
            ]
            _replace_sources(session, record, concept.sources)
            _replace_claims(session, record, concept.claims)
            if concept.learning_state is not None:
                _replace_learning_state(session, record, concept.learning_state)
            _replace_tag_assignments(session, record, concept.tags)
            _replace_topic_assignments(session, record, concept.topics)
            self._commit(session)
            return self.get_concept(concept.id, owner_id=owner_id)

    def add_sources(self, concept_id: UUID, sources: list[SourceDTO]) -> list[SourceDTO]:
        if not sources:
            return []
        with self._session() as session:
            if session.get(ConceptRecord, str(concept_id)) is None:
                raise _not_found("Concept not found.")
            for source in sources:
                session.merge(_source_to_record(source))
            self._commit(session)
            return _source_records_to_dtos(
                session.scalars(
                    select(SourceRecord).where(SourceRecord.concept_id == str(concept_id))
                ).all()
            )

    def add_claims(self, concept_id: UUID, claims: list[ClaimDTO]) -> list[ClaimDTO]:
        if not claims:
            return []
        with self._session() as session:
            if session.get(ConceptRecord, str(concept_id)) is None:
                raise _not_found("Concept not found.")
            for claim in claims:
                session.merge(_claim_to_record(claim))
            self._commit(session)
            return _claim_records_to_dtos(
                session.scalars(
                    select(ClaimRecord).where(ClaimRecord.concept_id == str(concept_id))
                ).all()
            )

    def add_learning_state_updates(
        self,
        concept_id: UUID,
        updates: list[LearningStateUpdateDTO],
    ) -> LearningStateDTO:
        with self._session() as session:
            if session.get(ConceptRecord, str(concept_id)) is None:
                raise _not_found("Concept not found.")
            for update in updates:
                normalized = update.content.strip()
                if not normalized:
                    continue
                exists = session.scalar(
                    select(LearningStateEntryRecord).where(
                        LearningStateEntryRecord.concept_id == str(concept_id),
                        LearningStateEntryRecord.field == update.field.value,
                        LearningStateEntryRecord.content == normalized,
                    )
                )
                if exists is not None:
                    continue
                session.add(
                    LearningStateEntryRecord(
                        id=str(uuid4()),
                        concept_id=str(concept_id),
                        field=update.field.value,
                        content=normalized,
                        origin=update.origin.value,
                    )
                )
            self._commit(session)
            records = session.scalars(
                select(LearningStateEntryRecord)
                .where(LearningStateEntryRecord.concept_id == str(concept_id))
                .order_by(LearningStateEntryRecord.created_at)
            ).all()
            return _learning_state_from_records(concept_id, records)

    def list_concepts(self, owner_id: str | None = None) -> list[ConceptDTO]:
        with self._session() as session:
            statement = select(ConceptRecord).order_by(ConceptRecord.created_at)
            if owner_id is not None:
                statement = statement.where(ConceptRecord.owner_id == owner_id)
            records = session.scalars(statement).all()
            for record in records:
                _attach_knowledge_records(session, record)
            return [_record_to_concept(record) for record in records]

    def get_concept(self, concept_id: UUID, owner_id: str | None = None) -> ConceptDTO:
        with self._session() as session:
            record = session.get(ConceptRecord, str(concept_id))
            if record is None or (owner_id is not None and record.owner_id != owner_id):
                raise _not_found("Concept not found.")
            _attach_knowledge_records(session, record)
            return _record_to_concept(record)

    def set_concepts_archived(
        self,
        concept_ids: list[UUID],
        *,
        archived: bool,
        owner_id: str,
    ) -> list[ConceptDTO]:
        unique_ids = list(dict.fromkeys(str(concept_id) for concept_id in concept_ids))
        with self._session() as session:
            records = session.scalars(
                select(ConceptRecord).where(
                    ConceptRecord.id.in_(unique_ids),
                    ConceptRecord.owner_id == owner_id,
                )
            ).all()
            if len(records) != len(unique_ids):
                raise _not_found("Concept not found.")
            for record in records:
                if archived:
                    if record.capture_status != CaptureStatus.archived.value:
                        record.archived_from_status = record.capture_status
                    record.capture_status = CaptureStatus.archived.value
                else:
                    record.capture_status = record.archived_from_status or CaptureStatus.ready.value
                    record.archived_from_status = None
            self._commit(session)
            for record in records:
                session.refresh(record)
                _attach_knowledge_records(session, record)
            return [_record_to_concept(record) for record in records]

    def add_relation(
        self,
        source_concept_id: UUID,
        target_concept_id: UUID,
        relation_type: str = "related",
    ) -> ConceptDTO:
        relation_type = relation_type.strip()
        if not relation_type:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Relation type cannot be empty.",
            )
        if source_concept_id == target_concept_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="A concept cannot relate to itself.",
            )

        with self._session() as session:
            source = session.get(ConceptRecord, str(source_concept_id))
            target = session.get(ConceptRecord, str(target_concept_id))
            if source is None or target is None:
                raise _not_found("Concept not found.")

            existing = session.scalar(
                select(ConceptRelationRecord).where(
                    ConceptRelationRecord.source_concept_id == str(source_concept_id),
                    ConceptRelationRecord.target_concept_id == str(target_concept_id),
                    ConceptRelationRecord.relation_type == relation_type,
                )
            )
            if existing is None:
                session.add(
                    ConceptRelationRecord(
                        id=str(uuid4()),
                        source_concept_id=str(source_concept_id),
                        target_concept_id=str(target_concept_id),
                        relation_type=relation_type,
                        status="accepted",
                        confidence=1,
                        source="user",
                    )
                )
                self._commit(session)
            return self.get_concept(source_concept_id)

    def remove_relation(self, concept_id: UUID, relation_id: UUID) -> ConceptDTO:
        with self._session() as session:
            if session.get(ConceptRecord, str(concept_id)) is None:
                raise _not_found("Concept not found.")
            relation = session.get(ConceptRelationRecord, str(relation_id))
            if relation is None:
                raise _not_found("Concept relation not found.")
            if str(concept_id) not in {
                relation.source_concept_id,
                relation.target_concept_id,
            }:
                raise _not_found("Concept relation not found.")
            session.delete(relation)
            self._commit(session)
            return self.get_concept(concept_id)

    def record_note_audit(
        self,
        concept_id: UUID,
        event_type: str,
        actor: str,
        proposal_id: UUID | None = None,
    ) -> None:
        with self._session() as session:
            record = session.get(ConceptRecord, str(concept_id))
            if record is None:
                raise _not_found("Concept not found.")

            existing_revision = session.scalar(
                select(NoteRevisionRecord).where(
                    NoteRevisionRecord.concept_id == str(concept_id),
                    NoteRevisionRecord.revision == record.note_revision,
                )
            )
            if existing_revision is None:
                session.add(
                    NoteRevisionRecord(
                        id=str(uuid4()),
                        concept_id=str(concept_id),
                        revision=record.note_revision,
                        snapshot_json=_snapshot_json(record),
                        merge_mode=event_type,
                        snapshot_schema_version=2,
                    )
                )
            existing_event = session.scalar(
                select(UpdateEventRecord).where(
                    UpdateEventRecord.concept_id == str(concept_id),
                    UpdateEventRecord.note_revision == record.note_revision,
                    UpdateEventRecord.event_type == event_type,
                    UpdateEventRecord.actor == actor,
                )
            )
            if existing_event is None:
                session.add(
                    UpdateEventRecord(
                        id=str(uuid4()),
                        concept_id=str(concept_id),
                        note_revision=record.note_revision,
                        proposal_id=str(proposal_id) if proposal_id is not None else None,
                        event_type=event_type,
                        actor=actor,
                    )
                )
            self._commit(session)

    def save_proposal(
        self,
        proposal: UpdateProposalDTO,
        concept_id: UUID | None = None,
    ) -> UpdateProposalDTO:
        with self._session() as session:
            record = session.get(UpdateProposalRecord, str(proposal.id))
            if record is None:
                if concept_id is None:
                    raise _not_found("Update proposal concept mapping not found.")
                record = UpdateProposalRecord(id=str(proposal.id), concept_id=str(concept_id))
                session.add(record)
            elif concept_id is not None:
                record.concept_id = str(concept_id)

            record.base_note_revision = proposal.base_note_revision
            record.patch_operations_json = patch_operations_adapter.dump_json(
                proposal.patch_operations,
                by_alias=True,
            ).decode()
            record.rationale = proposal.rationale
            record.confidence = proposal.confidence
            record.status = proposal.status.value
            record.origin = proposal.origin
            record.source_run_id = str(proposal.source_run_id) if proposal.source_run_id else None
            if proposal.status != ProposalStatus.proposed and record.resolved_at is None:
                record.resolved_at = datetime.now(UTC)
            self._commit(session)
            return self.get_proposal(proposal.id)

    def get_proposal(self, proposal_id: UUID) -> UpdateProposalDTO:
        with self._session() as session:
            record = session.get(UpdateProposalRecord, str(proposal_id))
            if record is None:
                raise _not_found("Update proposal not found.")
            return _record_to_proposal(record)

    def get_proposal_concept_id(self, proposal_id: UUID) -> UUID:
        with self._session() as session:
            record = session.get(UpdateProposalRecord, str(proposal_id))
            if record is None:
                raise _not_found("Update proposal concept mapping not found.")
            return UUID(record.concept_id)

    def list_proposals(
        self, concept_id: UUID, owner_id: str, proposal_status: ProposalStatus | None = None
    ) -> list[UpdateProposalDTO]:
        self.get_concept(concept_id, owner_id=owner_id)
        with self._session() as session:
            query = select(UpdateProposalRecord).where(
                UpdateProposalRecord.concept_id == str(concept_id)
            )
            if proposal_status is not None:
                query = query.where(UpdateProposalRecord.status == proposal_status.value)
            return [
                _record_to_proposal(row)
                for row in session.scalars(query.order_by(UpdateProposalRecord.created_at)).all()
            ]

    def list_revisions(self, concept_id: UUID, owner_id: str) -> list[NoteRevisionSummaryDTO]:
        concept = self.get_concept(concept_id, owner_id=owner_id)
        with self._session() as session:
            rows = session.scalars(
                select(NoteRevisionRecord)
                .where(NoteRevisionRecord.concept_id == str(concept_id))
                .order_by(NoteRevisionRecord.revision.desc())
            ).all()
            return [
                NoteRevisionSummaryDTO(
                    revision=row.revision,
                    source=row.merge_mode,
                    createdAt=_dt_to_iso(row.created_at),
                    isCurrent=row.revision == concept.note_revision,
                    restoredFromRevision=row.restored_from_revision,
                )
                for row in rows
            ]

    def get_revision(self, concept_id: UUID, revision: int, owner_id: str) -> NoteRevisionDTO:
        concept = self.get_concept(concept_id, owner_id=owner_id)
        with self._session() as session:
            row = session.scalar(
                select(NoteRevisionRecord).where(
                    NoteRevisionRecord.concept_id == str(concept_id),
                    NoteRevisionRecord.revision == revision,
                )
            )
            if row is None:
                raise _not_found("Note revision not found.")
            return _revision_dto(row, current_revision=concept.note_revision)

    def restore_revision(self, concept_id: UUID, revision: int, owner_id: str) -> ConceptDTO:
        with self._session() as session:
            concept = session.get(ConceptRecord, str(concept_id))
            if concept is None or concept.owner_id != owner_id:
                raise _not_found("Concept not found.")
            source = session.scalar(
                select(NoteRevisionRecord).where(
                    NoteRevisionRecord.concept_id == str(concept_id),
                    NoteRevisionRecord.revision == revision,
                )
            )
            if source is None:
                raise _not_found("Note revision not found.")
            snapshot = json.loads(source.snapshot_json)
            concept.canonical_title = (
                snapshot.get("canonicalTitle")
                or snapshot.get("displayTitle")
                or concept.canonical_title
            )
            concept.display_title = snapshot.get("displayTitle") or concept.display_title
            concept.one_line_explanation = snapshot.get("oneLineExplanation", "")
            concept.note_revision += 1
            concept.blocks = [
                _snapshot_block_to_record(item, concept_id, position)
                for position, item in enumerate(snapshot.get("blocks", []))
            ]
            session.flush()
            new_revision = NoteRevisionRecord(
                id=str(uuid4()),
                concept_id=str(concept_id),
                revision=concept.note_revision,
                snapshot_json=_snapshot_json(concept),
                merge_mode="revisionRestore",
                snapshot_schema_version=2,
                restored_from_revision=revision,
            )
            session.add(new_revision)
            session.add(
                UpdateEventRecord(
                    id=str(uuid4()),
                    concept_id=str(concept_id),
                    note_revision=concept.note_revision,
                    event_type="revisionRestore",
                    actor="user",
                )
            )
            for proposal in session.scalars(
                select(UpdateProposalRecord).where(
                    UpdateProposalRecord.concept_id == str(concept_id),
                    UpdateProposalRecord.status == ProposalStatus.proposed.value,
                )
            ).all():
                proposal.status = ProposalStatus.stale.value
                proposal.resolved_at = datetime.now(UTC)
            self._commit(session)
        return self.get_concept(concept_id, owner_id=owner_id)

    def get_recent_turns(self, concept_id: UUID, limit: int = 10) -> list[RecentTurn]:
        with self._session() as session:
            records = session.scalars(
                select(TurnRecord)
                .where(TurnRecord.concept_id == str(concept_id))
                .order_by(TurnRecord.id.desc())
                .limit(limit)
            ).all()
            return [
                RecentTurn(
                    role=record.role,
                    content=record.content,
                    answer_source_json=record.answer_source_json,
                )
                for record in reversed(records)
            ]

    def get_continuity_context(self, concept_id: UUID) -> tuple[list[RecentTurn], str]:
        with self._session() as session:
            records = session.scalars(
                select(TurnRecord)
                .where(TurnRecord.concept_id == str(concept_id))
                .order_by(TurnRecord.id)
            ).all()
            summary = session.get(ConceptContinuitySummaryRecord, str(concept_id))
            if summary is not None and len(records) >= 6:
                source = records[:-6]
                digest = hashlib.sha256(
                    "\n".join(f"{row.id}:{row.role}:{row.content}" for row in source).encode()
                ).hexdigest()
                if digest == summary.source_turns_hash:
                    recent = records[-6:]
                    return [
                        RecentTurn(
                            role=row.role,
                            content=row.content,
                            answer_source_json=row.answer_source_json,
                        )
                        for row in recent
                    ], summary.summary_json
            recent = records[-10:]
            return [
                RecentTurn(
                    role=row.role, content=row.content, answer_source_json=row.answer_source_json
                )
                for row in recent
            ], ""

    def append_turn_pair(
        self,
        concept_id: UUID,
        user_query: str,
        answer: str,
        answer_source: AnswerSourceDTO | None = None,
        operation_key: str | None = None,
    ) -> None:
        with self._session() as session:
            if session.get(ConceptRecord, str(concept_id)) is None:
                raise _not_found("Concept not found.")
            if operation_key is not None and session.scalar(
                select(TurnRecord.id).where(
                    TurnRecord.concept_id == str(concept_id),
                    TurnRecord.operation_key == operation_key,
                )
            ) is not None:
                return
            session.add_all(
                [
                    TurnRecord(
                        concept_id=str(concept_id),
                        role="user",
                        content=user_query,
                        operation_key=operation_key,
                    ),
                    TurnRecord(
                        concept_id=str(concept_id),
                        role="assistant",
                        content=answer,
                        operation_key=operation_key,
                        answer_source_json=(
                            answer_source.model_dump_json(by_alias=True)
                            if answer_source is not None
                            else None
                        ),
                    ),
                ]
            )
            self._commit(session)

    def replace_turn_pair_from_index(
        self,
        concept_id: UUID,
        turn_index: int,
        user_query: str,
        answer: str,
        answer_source: AnswerSourceDTO | None = None,
        operation_key: str | None = None,
    ) -> None:
        with self._session() as session:
            if session.get(ConceptRecord, str(concept_id)) is None:
                raise _not_found("Concept not found.")
            if operation_key is not None and session.scalar(
                select(TurnRecord.id).where(
                    TurnRecord.concept_id == str(concept_id),
                    TurnRecord.operation_key == operation_key,
                )
            ) is not None:
                return
            records = session.scalars(
                select(TurnRecord)
                .where(TurnRecord.concept_id == str(concept_id))
                .order_by(TurnRecord.id)
            ).all()
            _validate_replacement_record(records, turn_index)
            for record in records[turn_index:]:
                session.delete(record)
            session.add_all(
                [
                    TurnRecord(
                        concept_id=str(concept_id),
                        role="user",
                        content=user_query,
                        operation_key=operation_key,
                    ),
                    TurnRecord(
                        concept_id=str(concept_id),
                        role="assistant",
                        content=answer,
                        operation_key=operation_key,
                        answer_source_json=(
                            answer_source.model_dump_json(by_alias=True)
                            if answer_source is not None
                            else None
                        ),
                    ),
                ]
            )
            self._commit(session)

    def list_turns(self, concept_id: UUID) -> list[RecentTurn]:
        self.get_concept(concept_id)
        with self._session() as session:
            records = session.scalars(
                select(TurnRecord)
                .where(TurnRecord.concept_id == str(concept_id))
                .order_by(TurnRecord.id)
            ).all()
            return [
                RecentTurn(
                    role=record.role,
                    content=record.content,
                    answer_source_json=record.answer_source_json,
                )
                for record in records
            ]

    def get_capture_attempt(
        self,
        owner_id: str,
        idempotency_key: str,
    ) -> CaptureAttemptDTO | None:
        with self._session() as session:
            record = session.scalar(
                select(CaptureAttemptRecord).where(
                    CaptureAttemptRecord.owner_id == owner_id,
                    CaptureAttemptRecord.idempotency_key == idempotency_key,
                )
            )
            return _record_to_capture_attempt(record) if record is not None else None

    def create_capture_attempt(
        self,
        owner_id: str,
        idempotency_key: str,
        payload_hash: str,
        raw_capture: str,
        locale: str,
    ) -> CaptureAttemptDTO:
        with self._session() as session:
            existing = session.scalar(
                select(CaptureAttemptRecord).where(
                    CaptureAttemptRecord.owner_id == owner_id,
                    CaptureAttemptRecord.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return _record_to_capture_attempt(existing)
            record = CaptureAttemptRecord(
                id=str(uuid4()),
                owner_id=owner_id,
                idempotency_key=idempotency_key,
                payload_hash=payload_hash,
                raw_capture=raw_capture,
                locale=locale,
                status="generating",
            )
            session.add(record)
            self._commit(session)
            return _record_to_capture_attempt(record)

    def update_capture_attempt(
        self,
        attempt_id: UUID,
        *,
        status: str,
        concept_id: UUID | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> CaptureAttemptDTO:
        with self._session() as session:
            record = session.get(CaptureAttemptRecord, str(attempt_id))
            if record is None:
                raise _not_found("Capture attempt not found.")
            record.status = status
            record.concept_id = str(concept_id) if concept_id is not None else None
            record.failure_code = failure_code
            record.failure_message = failure_message
            self._commit(session)
            return _record_to_capture_attempt(record)

    def get_idempotency_record(
        self,
        owner_id: str,
        endpoint: str,
        idempotency_key: str,
    ) -> IdempotencyRecordDTO | None:
        with self._session() as session:
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.owner_id == owner_id,
                    IdempotencyRecord.endpoint == endpoint,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            return _record_to_idempotency(record) if record is not None else None

    def save_idempotency_record(
        self,
        owner_id: str,
        endpoint: str,
        idempotency_key: str,
        payload_hash: str,
        response_json: str,
    ) -> IdempotencyRecordDTO:
        with self._session() as session:
            record = session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.owner_id == owner_id,
                    IdempotencyRecord.endpoint == endpoint,
                    IdempotencyRecord.idempotency_key == idempotency_key,
                )
            )
            if record is None:
                record = IdempotencyRecord(
                    id=str(uuid4()),
                    owner_id=owner_id,
                    endpoint=endpoint,
                    idempotency_key=idempotency_key,
                    payload_hash=payload_hash,
                    status="succeeded",
                )
                session.add(record)
            record.response_json = response_json
            record.payload_hash = payload_hash
            record.status = "succeeded"
            self._commit(session)
            return _record_to_idempotency(record)


def _note_block_to_record(
    block: NoteBlockDTO,
    concept_id: UUID,
    position: int,
) -> NoteBlockRecord:
    return NoteBlockRecord(
        id=str(block.id),
        concept_id=str(concept_id),
        block_type=block.block_type.value,
        content=block.content,
        source=block.source.value,
        is_user_locked=block.is_user_locked,
        revision=block.revision,
        supported_claim_ids_json=json.dumps(
            [str(claim_id) for claim_id in block.supported_claim_ids],
        ),
        position=position,
    )


def _record_to_concept(record: ConceptRecord) -> ConceptDTO:
    return ConceptDTO(
        id=UUID(record.id),
        canonicalTitle=record.canonical_title,
        displayTitle=record.display_title,
        oneLineExplanation=record.one_line_explanation,
        initialAnswer=record.initial_answer,
        maturity=ConceptMaturity(record.maturity),
        captureStatus=CaptureStatus(record.capture_status),
        noteRevision=record.note_revision,
        blocks=[
            NoteBlockDTO(
                id=UUID(block.id),
                blockType=NoteBlockType(block.block_type),
                content=block.content,
                source=NoteBlockSource(block.source),
                isUserLocked=block.is_user_locked,
                revision=block.revision,
                supportedClaimIds=[
                    UUID(claim_id) for claim_id in _json_list(block.supported_claim_ids_json)
                ],
                position=block.position,
            )
            for block in record.blocks
        ],
        tags=[assignment.tag.name for assignment in record.tag_assignments],
        topics=[assignment.topic.name for assignment in record.topic_assignments],
        answerSource=(
            AnswerSourceDTO.model_validate_json(record.answer_source_json)
            if record.answer_source_json
            else None
        ),
        relations=[
            *_relation_records_to_dtos(record.outgoing_relations),
            *_relation_records_to_dtos(record.incoming_relations),
        ],
        sources=_source_records_to_dtos(
            sorted(
                getattr(record, "_sift_sources", None) or [],
                key=lambda source: source.created_at,
            )
        ),
        claims=_claim_records_to_dtos(
            sorted(
                getattr(record, "_sift_claims", None) or [],
                key=lambda claim: claim.created_at,
            )
        ),
        learningState=_learning_state_from_records(
            UUID(record.id),
            sorted(
                getattr(record, "_sift_learning_entries", None) or [],
                key=lambda entry: entry.created_at,
            ),
        ),
        createdAt=_dt_to_iso(record.created_at),
        updatedAt=_dt_to_iso(record.updated_at),
    )


def _record_to_capture_attempt(record: CaptureAttemptRecord) -> CaptureAttemptDTO:
    return CaptureAttemptDTO(
        id=UUID(record.id),
        owner_id=record.owner_id,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        raw_capture=record.raw_capture,
        locale=record.locale,
        status=record.status,
        concept_id=UUID(record.concept_id) if record.concept_id is not None else None,
        failure_code=record.failure_code,
        failure_message=record.failure_message,
    )


def _record_to_idempotency(record: IdempotencyRecord) -> IdempotencyRecordDTO:
    return IdempotencyRecordDTO(
        id=UUID(record.id),
        owner_id=record.owner_id,
        endpoint=record.endpoint,
        idempotency_key=record.idempotency_key,
        payload_hash=record.payload_hash,
        status=record.status,
        response_json=record.response_json,
    )


def _snapshot_json(record: ConceptRecord) -> str:
    return json.dumps(
        {
            "conceptId": record.id,
            "canonicalTitle": record.canonical_title,
            "displayTitle": record.display_title,
            "oneLineExplanation": record.one_line_explanation,
            "noteRevision": record.note_revision,
            "blocks": [
                {
                    "id": block.id,
                    "blockType": block.block_type,
                    "content": block.content,
                    "source": block.source,
                    "isUserLocked": block.is_user_locked,
                    "revision": block.revision,
                    "supportedClaimIds": json.loads(block.supported_claim_ids_json),
                    "position": block.position,
                }
                for block in record.blocks
            ],
        },
        ensure_ascii=False,
    )


def _record_to_proposal(record: UpdateProposalRecord) -> UpdateProposalDTO:
    return UpdateProposalDTO(
        id=UUID(record.id),
        baseNoteRevision=record.base_note_revision,
        patchOperations=patch_operations_adapter.validate_json(record.patch_operations_json),
        rationale=record.rationale,
        confidence=record.confidence,
        status=ProposalStatus(record.status),
        origin=record.origin,
        sourceRunId=UUID(record.source_run_id) if record.source_run_id else None,
    )


def _revision_dto(record: NoteRevisionRecord, *, current_revision: int) -> NoteRevisionDTO:
    snapshot = json.loads(record.snapshot_json)
    blocks = [
        NoteBlockDTO(
            id=UUID(item["id"]),
            blockType=item.get("blockType", "explanation"),
            content=item.get("content", ""),
            source=item.get("source", "ai"),
            isUserLocked=item.get("isUserLocked", False),
            revision=max(1, item.get("revision", 1)),
            supportedClaimIds=item.get("supportedClaimIds", []),
            position=item.get("position", position),
        )
        for position, item in enumerate(snapshot.get("blocks", []))
    ]
    display_title = snapshot.get("displayTitle", "")
    return NoteRevisionDTO(
        revision=record.revision,
        source=record.merge_mode,
        createdAt=_dt_to_iso(record.created_at),
        isCurrent=record.revision == current_revision,
        restoredFromRevision=record.restored_from_revision,
        snapshotSchemaVersion=record.snapshot_schema_version or 1,
        displayTitle=display_title,
        canonicalTitle=snapshot.get("canonicalTitle", display_title),
        oneLineExplanation=snapshot.get("oneLineExplanation", ""),
        blocks=blocks,
    )


def _snapshot_block_to_record(
    item: dict, concept_id: UUID, fallback_position: int
) -> NoteBlockRecord:
    return NoteBlockRecord(
        id=item.get("id") or str(uuid4()),
        concept_id=str(concept_id),
        block_type=item.get("blockType", "explanation"),
        content=item.get("content", ""),
        source=item.get("source", "ai"),
        is_user_locked=item.get("isUserLocked", False),
        revision=max(1, item.get("revision", 1)),
        supported_claim_ids_json=json.dumps(item.get("supportedClaimIds", [])),
        position=item.get("position", fallback_position),
    )


def _attach_knowledge_records(session: Session, record: ConceptRecord) -> None:
    concept_id = record.id
    record._sift_sources = session.scalars(
        select(SourceRecord).where(SourceRecord.concept_id == concept_id)
    ).all()
    record._sift_claims = session.scalars(
        select(ClaimRecord).where(ClaimRecord.concept_id == concept_id)
    ).all()
    record._sift_learning_entries = session.scalars(
        select(LearningStateEntryRecord).where(LearningStateEntryRecord.concept_id == concept_id)
    ).all()


def _source_to_record(source: SourceDTO) -> SourceRecord:
    return SourceRecord(
        id=str(source.id),
        concept_id=str(source.concept_id),
        title=source.title,
        url=source.url,
        source_type=source.source_type.value,
        retrieved_at=_parse_dt(source.retrieved_at),
        published_at=_parse_dt(source.published_at),
        content_hash=source.content_hash,
    )


def _claim_to_record(claim: ClaimDTO) -> ClaimRecord:
    return ClaimRecord(
        id=str(claim.id),
        concept_id=str(claim.concept_id),
        statement=claim.statement,
        claim_type=claim.type.value,
        evidence_status=claim.evidence_status.value,
        time_sensitivity=claim.time_sensitivity.value,
        source_ids_json=json.dumps([str(source_id) for source_id in claim.source_ids]),
        verified_at=_parse_dt(claim.verified_at),
        superseded_by_claim_id=(
            str(claim.superseded_by_claim_id) if claim.superseded_by_claim_id is not None else None
        ),
    )


def _source_records_to_dtos(records: list[SourceRecord]) -> list[SourceDTO]:
    return [
        SourceDTO(
            id=UUID(record.id),
            conceptId=UUID(record.concept_id),
            title=record.title,
            url=record.url,
            sourceType=SourceType(record.source_type),
            retrievedAt=_dt_to_iso(record.retrieved_at),
            publishedAt=_dt_to_iso(record.published_at),
            contentHash=record.content_hash,
        )
        for record in records
    ]


def _claim_records_to_dtos(records: list[ClaimRecord]) -> list[ClaimDTO]:
    return [
        ClaimDTO(
            id=UUID(record.id),
            conceptId=UUID(record.concept_id),
            statement=record.statement,
            type=ClaimType(record.claim_type),
            evidenceStatus=EvidenceStatus(record.evidence_status),
            timeSensitivity=TimeSensitivity(record.time_sensitivity),
            sourceIds=[UUID(source_id) for source_id in _json_list(record.source_ids_json)],
            verifiedAt=_dt_to_iso(record.verified_at),
            supersededByClaimId=(
                UUID(record.superseded_by_claim_id)
                if record.superseded_by_claim_id is not None
                else None
            ),
        )
        for record in records
    ]


def _learning_state_from_records(
    concept_id: UUID,
    records: list[LearningStateEntryRecord],
) -> LearningStateDTO:
    grouped: dict[str, list[LearningStateEntryDTO]] = {
        LearningStateField.user_context.value: [],
        LearningStateField.confirmed_understanding.value: [],
        LearningStateField.open_questions.value: [],
        LearningStateField.recurring_confusions.value: [],
    }
    for record in records:
        entry = LearningStateEntryDTO(
            content=record.content,
            origin=LearningStateOrigin(record.origin),
            createdAt=_dt_to_iso(record.created_at),
        )
        grouped.setdefault(record.field, []).append(entry)
    return LearningStateDTO(
        conceptId=concept_id,
        userContext=grouped[LearningStateField.user_context.value],
        confirmedUnderstanding=grouped[LearningStateField.confirmed_understanding.value],
        openQuestions=grouped[LearningStateField.open_questions.value],
        recurringConfusions=grouped[LearningStateField.recurring_confusions.value],
    )


def _replace_sources(
    session: Session,
    concept: ConceptRecord,
    sources: list[SourceDTO],
) -> None:
    session.query(SourceRecord).filter(SourceRecord.concept_id == concept.id).delete()
    for source in sources:
        session.add(_source_to_record(source))


def _replace_claims(
    session: Session,
    concept: ConceptRecord,
    claims: list[ClaimDTO],
) -> None:
    session.query(ClaimRecord).filter(ClaimRecord.concept_id == concept.id).delete()
    for claim in claims:
        session.add(_claim_to_record(claim))


def _replace_learning_state(
    session: Session,
    concept: ConceptRecord,
    learning_state: LearningStateDTO,
) -> None:
    session.query(LearningStateEntryRecord).filter(
        LearningStateEntryRecord.concept_id == concept.id
    ).delete()
    entries = [
        (LearningStateField.user_context, learning_state.user_context),
        (LearningStateField.confirmed_understanding, learning_state.confirmed_understanding),
        (LearningStateField.open_questions, learning_state.open_questions),
        (LearningStateField.recurring_confusions, learning_state.recurring_confusions),
    ]
    for field, values in entries:
        for value in values:
            session.add(
                LearningStateEntryRecord(
                    id=str(uuid4()),
                    concept_id=concept.id,
                    field=field.value,
                    content=value.content,
                    origin=value.origin.value,
                    created_at=_parse_dt(value.created_at) or datetime.now(UTC),
                )
            )


def _relation_records_to_dtos(
    records: list[ConceptRelationRecord],
) -> list[ConceptRelationDTO]:
    return [
        ConceptRelationDTO(
            id=UUID(record.id),
            sourceConceptId=UUID(record.source_concept_id),
            targetConceptId=UUID(record.target_concept_id),
            relationType=record.relation_type,
            status=record.status,
            confidence=record.confidence,
            source=record.source,
        )
        for record in records
    ]


def _replace_tag_assignments(
    session: Session,
    concept: ConceptRecord,
    names: list[str],
) -> None:
    for assignment in list(concept.tag_assignments):
        session.delete(assignment)
    concept.tag_assignments.clear()
    session.flush()
    for name in _normalized_names(names):
        tag = _get_or_create_tag(session, name)
        concept.tag_assignments.append(ConceptTagRecord(tag=tag, confidence=1, source="user"))


def _replace_topic_assignments(
    session: Session,
    concept: ConceptRecord,
    names: list[str],
) -> None:
    for assignment in list(concept.topic_assignments):
        session.delete(assignment)
    concept.topic_assignments.clear()
    session.flush()
    for name in _normalized_names(names):
        topic = _get_or_create_topic(session, name)
        concept.topic_assignments.append(
            ConceptTopicRecord(topic=topic, confidence=1, source="user")
        )


def _json_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _get_or_create_tag(session: Session, name: str) -> TagRecord:
    tag = session.scalar(select(TagRecord).where(TagRecord.name == name))
    if tag is not None:
        return tag
    tag = TagRecord(name=name, source="user")
    session.add(tag)
    return tag


def _get_or_create_topic(session: Session, name: str) -> TopicRecord:
    topic = session.scalar(select(TopicRecord).where(TopicRecord.name == name))
    if topic is not None:
        return topic
    topic = TopicRecord(name=name, source="user")
    session.add(topic)
    return topic


def _normalized_names(names: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_name in names:
        name = raw_name.strip()
        if not name:
            continue
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(name[:80])
    return normalized


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _validate_replacement_record(records: list[TurnRecord], turn_index: int) -> None:
    if turn_index >= len(records) or records[turn_index].role != "user":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invalid_turn_replacement", "message": "Turn is not replaceable."},
        )
