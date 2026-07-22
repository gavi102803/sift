import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any
from uuid import UUID, uuid4

from fastapi import HTTPException, status

from sift_backend.ai.context_pack import RecentTurn
from sift_backend.auth.principal import CurrentPrincipal, DevelopmentPrincipalProvider
from sift_backend.notes.patch_engine import (
    NoteSnapshot,
    PatchApplicationError,
    PatchErrorCode,
    apply_patch_operations,
    content_hash,
)
from sift_backend.runtime.concept_runtime import (
    ConceptInitialRuntimeResult,
    ConceptRuntimeDelta,
    ConceptRuntimeResult,
    LightweightHermesRuntime,
)
from sift_backend.runtime.types import SiftRuntimeError
from sift_backend.schemas.common import (
    AnswerSourceType,
    CandidateUpdateOperation,
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
    UpdateMode,
)
from sift_backend.schemas.concepts import (
    AnswerSourceDTO,
    ClaimDTO,
    ConceptDTO,
    ConceptHistoryTurnDTO,
    ConceptRelationDTO,
    ConceptTurnRequest,
    ConceptTurnResponse,
    CreateConceptRelationRequest,
    CreateConceptRequest,
    LearningStateDTO,
    LearningStateEntryDTO,
    LearningStateUpdateDTO,
    NoteBlockDTO,
    NoteRevisionDTO,
    NoteRevisionSummaryDTO,
    SourceDTO,
    UpdateConceptNoteRequest,
    UpdateConceptOrganizationRequest,
    UpdateConceptSummaryRequest,
    UpdateDecisionDTO,
    UpdateNoteBlockRequest,
    UpdateProposalDTO,
)
from sift_backend.schemas.model_outputs import (
    CandidateUpdate,
    ConceptInitialResult,
    ConceptTurnResult,
    ContinuitySummaryEntry,
    ContinuitySummaryResult,
    MemoryPatch,
    ModelMeta,
    ModelUpdateProposal,
)
from sift_backend.schemas.patches import (
    AddRelationPatchOperation,
    AppendPatchOperation,
    ReplacePatchOperation,
)


@dataclass(frozen=True)
class ConceptTurnStreamDelta:
    content: str


@dataclass(frozen=True)
class ConceptTurnStreamResult:
    response: ConceptTurnResponse


@dataclass(frozen=True)
class PreparedTurnResult:
    base_note_revision: int
    turn_result: ConceptTurnResult | None = None
    regenerated_concept: ConceptDTO | None = None


@dataclass(frozen=True)
class ConceptInitialStreamResult:
    concept: ConceptDTO


@dataclass(frozen=True)
class CaptureAttemptDTO:
    id: UUID
    owner_id: str
    idempotency_key: str
    payload_hash: str | None
    raw_capture: str
    locale: str
    status: str
    concept_id: UUID | None = None
    failure_code: str | None = None
    failure_message: str | None = None


@dataclass(frozen=True)
class IdempotencyRecordDTO:
    id: UUID
    owner_id: str
    endpoint: str
    idempotency_key: str
    payload_hash: str | None
    status: str
    response_json: str | None = None


ConceptTurnStreamEvent = ConceptTurnStreamDelta | ConceptTurnStreamResult
ConceptInitialStreamEvent = ConceptTurnStreamDelta | ConceptInitialStreamResult

LOCAL_DEV_OWNER_ID = "local-dev"


class InMemoryConceptStore:
    """Temporary store for API contract development before PostgreSQL lands."""

    def __init__(self) -> None:
        self.concepts: dict[UUID, ConceptDTO] = {}
        self.relations: dict[UUID, ConceptRelationDTO] = {}
        self.proposals: dict[UUID, UpdateProposalDTO] = {}
        self.proposal_concept_ids: dict[UUID, UUID] = {}
        self.turns: dict[UUID, list[RecentTurn]] = {}
        self.turn_operation_keys: set[tuple[UUID, str]] = set()
        self.concept_owner_ids: dict[UUID, str] = {}
        self.archived_from_status: dict[UUID, CaptureStatus] = {}
        self.capture_attempts: dict[tuple[str, str], CaptureAttemptDTO] = {}
        self.idempotency_records: dict[tuple[str, str, str], IdempotencyRecordDTO] = {}
        self.revisions: dict[UUID, list[tuple[ConceptDTO, str, int | None, str]]] = {}

    def save_concept(self, concept: ConceptDTO, owner_id: str | None = None) -> ConceptDTO:
        now = datetime.now(UTC).isoformat()
        existing = self.concepts.get(concept.id)
        self.concepts[concept.id] = concept.model_copy(
            update={
                "relations": [],
                "created_at": concept.created_at or (existing.created_at if existing else now),
                "updated_at": now,
            }
        )
        if owner_id is not None:
            self.concept_owner_ids[concept.id] = owner_id
        else:
            self.concept_owner_ids.setdefault(concept.id, LOCAL_DEV_OWNER_ID)
        return self.get_concept(concept.id)

    def add_sources(self, concept_id: UUID, sources: list[SourceDTO]) -> list[SourceDTO]:
        concept = self.get_concept(concept_id)
        existing = {source.id: source for source in concept.sources}
        for source in sources:
            existing[source.id] = source
        self.concepts[concept_id] = concept.model_copy(
            update={"sources": list(existing.values()), "relations": []}
        )
        return self.concepts[concept_id].sources

    def add_claims(self, concept_id: UUID, claims: list[ClaimDTO]) -> list[ClaimDTO]:
        concept = self.get_concept(concept_id)
        existing = {claim.id: claim for claim in concept.claims}
        for claim in claims:
            existing[claim.id] = claim
        self.concepts[concept_id] = concept.model_copy(
            update={"claims": list(existing.values()), "relations": []}
        )
        return self.concepts[concept_id].claims

    def add_learning_state_updates(
        self,
        concept_id: UUID,
        updates: list[LearningStateUpdateDTO],
    ) -> LearningStateDTO:
        concept = self.get_concept(concept_id)
        learning_state = concept.learning_state or LearningStateDTO(conceptId=concept_id)
        data = learning_state.model_copy(deep=True)
        targets = {
            LearningStateField.user_context: data.user_context,
            LearningStateField.confirmed_understanding: data.confirmed_understanding,
            LearningStateField.open_questions: data.open_questions,
            LearningStateField.recurring_confusions: data.recurring_confusions,
        }
        for update in updates:
            normalized = update.content.strip()
            if not normalized:
                continue
            target = targets[update.field]
            if any(existing.content == normalized for existing in target):
                continue
            target.append(LearningStateEntryDTO(content=normalized, origin=update.origin))
        self.concepts[concept_id] = concept.model_copy(
            update={"learning_state": data, "relations": []}
        )
        return data

    def list_concepts(self, owner_id: str | None = None) -> list[ConceptDTO]:
        return [
            self._concept_with_relations(concept)
            for concept in self.concepts.values()
            if owner_id is None or self.concept_owner_ids.get(concept.id) == owner_id
        ]

    def get_concept(self, concept_id: UUID, owner_id: str | None = None) -> ConceptDTO:
        try:
            concept = self.concepts[concept_id]
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Concept not found.",
            ) from error
        if owner_id is not None and self.concept_owner_ids.get(concept_id) != owner_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Concept not found.",
            )
        return self._concept_with_relations(concept)

    def set_concepts_archived(
        self,
        concept_ids: list[UUID],
        *,
        archived: bool,
        owner_id: str,
    ) -> list[ConceptDTO]:
        unique_ids = list(dict.fromkeys(concept_ids))
        concepts = [self.get_concept(concept_id, owner_id=owner_id) for concept_id in unique_ids]
        now = datetime.now(UTC).isoformat()
        for concept in concepts:
            if archived:
                if concept.capture_status != CaptureStatus.archived:
                    self.archived_from_status[concept.id] = concept.capture_status
                status_value = CaptureStatus.archived
            else:
                status_value = self.archived_from_status.pop(concept.id, CaptureStatus.ready)
            self.concepts[concept.id] = concept.model_copy(
                update={"capture_status": status_value, "updated_at": now, "relations": []}
            )
        return [self.get_concept(concept_id, owner_id=owner_id) for concept_id in unique_ids]

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
        self.get_concept(source_concept_id)
        self.get_concept(target_concept_id)

        for relation in self.relations.values():
            if (
                relation.source_concept_id == source_concept_id
                and relation.target_concept_id == target_concept_id
                and relation.relation_type == relation_type
            ):
                return self.get_concept(source_concept_id)

        relation = ConceptRelationDTO(
            id=uuid4(),
            sourceConceptId=source_concept_id,
            targetConceptId=target_concept_id,
            relationType=relation_type,
            status="accepted",
            confidence=1,
            source="user",
        )
        self.relations[relation.id] = relation
        return self.get_concept(source_concept_id)

    def remove_relation(self, concept_id: UUID, relation_id: UUID) -> ConceptDTO:
        self.get_concept(concept_id)
        relation = self.relations.get(relation_id)
        if relation is None or concept_id not in {
            relation.source_concept_id,
            relation.target_concept_id,
        }:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Concept relation not found.",
            )
        del self.relations[relation_id]
        return self.get_concept(concept_id)

    def record_note_audit(
        self,
        concept_id: UUID,
        event_type: str,
        actor: str,
        proposal_id: UUID | None = None,
    ) -> None:
        concept = self.get_concept(concept_id)
        rows = self.revisions.setdefault(concept_id, [])
        if not any(snapshot.note_revision == concept.note_revision for snapshot, _, _, _ in rows):
            rows.append(
                (concept.model_copy(deep=True), event_type, None, datetime.now(UTC).isoformat())
            )

    def save_proposal(
        self,
        proposal: UpdateProposalDTO,
        concept_id: UUID | None = None,
    ) -> UpdateProposalDTO:
        self.proposals[proposal.id] = proposal
        if concept_id is not None:
            self.proposal_concept_ids[proposal.id] = concept_id
        return proposal

    def get_proposal(self, proposal_id: UUID) -> UpdateProposalDTO:
        try:
            return self.proposals[proposal_id]
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Update proposal not found.",
            ) from error

    def get_proposal_concept_id(self, proposal_id: UUID) -> UUID:
        try:
            return self.proposal_concept_ids[proposal_id]
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Update proposal concept mapping not found.",
            ) from error

    def list_proposals(
        self, concept_id: UUID, owner_id: str, proposal_status: ProposalStatus | None = None
    ) -> list[UpdateProposalDTO]:
        self.get_concept(concept_id, owner_id=owner_id)
        return [
            proposal
            for proposal_id, proposal in self.proposals.items()
            if self.proposal_concept_ids.get(proposal_id) == concept_id
            and (proposal_status is None or proposal.status == proposal_status)
        ]

    def list_revisions(self, concept_id: UUID, owner_id: str) -> list[NoteRevisionSummaryDTO]:
        current = self.get_concept(concept_id, owner_id=owner_id)
        return [
            NoteRevisionSummaryDTO(
                revision=snapshot.note_revision,
                source=source,
                createdAt=created_at,
                isCurrent=snapshot.note_revision == current.note_revision,
                restoredFromRevision=restored,
            )
            for snapshot, source, restored, created_at in reversed(
                self.revisions.get(concept_id, [])
            )
        ]

    def get_revision(self, concept_id: UUID, revision: int, owner_id: str) -> NoteRevisionDTO:
        current = self.get_concept(concept_id, owner_id=owner_id)
        for snapshot, source, restored, created_at in self.revisions.get(concept_id, []):
            if snapshot.note_revision == revision:
                return NoteRevisionDTO(
                    revision=revision,
                    source=source,
                    createdAt=created_at,
                    isCurrent=revision == current.note_revision,
                    restoredFromRevision=restored,
                    snapshotSchemaVersion=2,
                    displayTitle=snapshot.display_title,
                    canonicalTitle=snapshot.canonical_title,
                    oneLineExplanation=snapshot.one_line_explanation,
                    blocks=snapshot.blocks,
                )
        raise HTTPException(status_code=404, detail="Note revision not found.")

    def restore_revision(self, concept_id: UUID, revision: int, owner_id: str) -> ConceptDTO:
        current = self.get_concept(concept_id, owner_id=owner_id)
        source = self.get_revision(concept_id, revision, owner_id)
        updated = current.model_copy(
            update={
                "canonical_title": source.canonical_title,
                "display_title": source.display_title,
                "one_line_explanation": source.one_line_explanation,
                "blocks": source.blocks,
                "note_revision": current.note_revision + 1,
            }
        )
        self.save_concept(updated, owner_id=owner_id)
        created_at = datetime.now(UTC).isoformat()
        self.revisions.setdefault(concept_id, []).append(
            (updated.model_copy(deep=True), "revisionRestore", revision, created_at)
        )
        for proposal_id, proposal in list(self.proposals.items()):
            if (
                self.proposal_concept_ids.get(proposal_id) == concept_id
                and proposal.status == ProposalStatus.proposed
            ):
                self.proposals[proposal_id] = proposal.model_copy(
                    update={"status": ProposalStatus.stale}
                )
        return self.get_concept(concept_id, owner_id=owner_id)

    def get_recent_turns(self, concept_id: UUID, limit: int = 10) -> list[RecentTurn]:
        return self.turns.get(concept_id, [])[-limit:]

    def get_continuity_context(self, concept_id: UUID) -> tuple[list[RecentTurn], str]:
        return self.get_recent_turns(concept_id, 10), ""

    def append_turn_pair(
        self,
        concept_id: UUID,
        user_query: str,
        answer: str,
        answer_source: AnswerSourceDTO | None = None,
        operation_key: str | None = None,
    ) -> None:
        if operation_key is not None and (concept_id, operation_key) in self.turn_operation_keys:
            return
        concept_turns = self.turns.setdefault(concept_id, [])
        concept_turns.extend(
            [
                RecentTurn(role="user", content=user_query),
                RecentTurn(
                    role="assistant",
                    content=answer,
                    answer_source_json=(
                        answer_source.model_dump_json(by_alias=True)
                        if answer_source is not None
                        else None
                    ),
                ),
            ]
        )
        if operation_key is not None:
            self.turn_operation_keys.add((concept_id, operation_key))

    def replace_turn_pair_from_index(
        self,
        concept_id: UUID,
        turn_index: int,
        user_query: str,
        answer: str,
        answer_source: AnswerSourceDTO | None = None,
        operation_key: str | None = None,
    ) -> None:
        if operation_key is not None and (concept_id, operation_key) in self.turn_operation_keys:
            return
        concept_turns = self.turns.setdefault(concept_id, [])
        _validate_replacement_turn(concept_turns, turn_index)
        del concept_turns[turn_index:]
        self.append_turn_pair(
            concept_id,
            user_query,
            answer,
            answer_source=answer_source,
            operation_key=operation_key,
        )

    def list_turns(self, concept_id: UUID) -> list[RecentTurn]:
        self.get_concept(concept_id)
        return self.turns.get(concept_id, [])

    def get_capture_attempt(
        self,
        owner_id: str,
        idempotency_key: str,
    ) -> CaptureAttemptDTO | None:
        return self.capture_attempts.get((owner_id, idempotency_key))

    def create_capture_attempt(
        self,
        owner_id: str,
        idempotency_key: str,
        payload_hash: str,
        raw_capture: str,
        locale: str,
    ) -> CaptureAttemptDTO:
        attempt = CaptureAttemptDTO(
            id=uuid4(),
            owner_id=owner_id,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            raw_capture=raw_capture,
            locale=locale,
            status="generating",
        )
        self.capture_attempts[(owner_id, idempotency_key)] = attempt
        return attempt

    def update_capture_attempt(
        self,
        attempt_id: UUID,
        *,
        status: str,
        concept_id: UUID | None = None,
        failure_code: str | None = None,
        failure_message: str | None = None,
    ) -> CaptureAttemptDTO:
        for key, attempt in self.capture_attempts.items():
            if attempt.id == attempt_id:
                updated = CaptureAttemptDTO(
                    id=attempt.id,
                    owner_id=attempt.owner_id,
                    idempotency_key=attempt.idempotency_key,
                    payload_hash=attempt.payload_hash,
                    raw_capture=attempt.raw_capture,
                    locale=attempt.locale,
                    status=status,
                    concept_id=concept_id,
                    failure_code=failure_code,
                    failure_message=failure_message,
                )
                self.capture_attempts[key] = updated
                return updated
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Capture attempt not found.",
        )

    def get_idempotency_record(
        self,
        owner_id: str,
        endpoint: str,
        idempotency_key: str,
    ) -> IdempotencyRecordDTO | None:
        return self.idempotency_records.get((owner_id, endpoint, idempotency_key))

    def save_idempotency_record(
        self,
        owner_id: str,
        endpoint: str,
        idempotency_key: str,
        payload_hash: str,
        response_json: str,
    ) -> IdempotencyRecordDTO:
        record = IdempotencyRecordDTO(
            id=uuid4(),
            owner_id=owner_id,
            endpoint=endpoint,
            idempotency_key=idempotency_key,
            payload_hash=payload_hash,
            status="succeeded",
            response_json=response_json,
        )
        self.idempotency_records[(owner_id, endpoint, idempotency_key)] = record
        return record

    def _concept_with_relations(self, concept: ConceptDTO) -> ConceptDTO:
        relations = [
            relation
            for relation in self.relations.values()
            if concept.id in {relation.source_concept_id, relation.target_concept_id}
        ]
        return concept.model_copy(update={"relations": relations})


class MockConceptModelService:
    """Deterministic stand-in for the Sift runtime while local configuration is absent."""

    async def create_initial_concept(
        self,
        title: str,
        locale: str,
    ) -> ConceptDTO:
        return _fallback_initial_concept(title)

    async def stream_initial_concept(
        self,
        title: str,
        locale: str,
    ) -> AsyncIterator[ConceptRuntimeDelta | ConceptInitialRuntimeResult]:
        concept = await self.create_initial_concept(title, locale)
        answer = (concept.initial_answer or concept.one_line_explanation).strip()
        for chunk in _chunk_text(answer):
            yield ConceptRuntimeDelta(chunk)
        payload = _initial_result_from_concept(concept)
        yield ConceptInitialRuntimeResult(payload)

    def initial_blocks(self, title: str) -> list[NoteBlockDTO]:
        return [
            NoteBlockDTO(
                id=uuid4(),
                blockType=NoteBlockType.what_it_is,
                content=f"{title} is ready for a first explanation.",
                source=NoteBlockSource.ai,
                isUserLocked=False,
            ),
            NoteBlockDTO(
                id=uuid4(),
                blockType=NoteBlockType.why_it_matters,
                content="Sift keeps this card available for future follow-up.",
                source=NoteBlockSource.ai,
                isUserLocked=False,
            ),
        ]

    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ) -> ConceptTurnResult:
        first_block = concept.blocks[0] if concept.blocks else None
        answer_source = AnswerSourceDTO(
            sourceType=AnswerSourceType.model_knowledge,
            confidence=0.5,
            uncertaintyNote="Mock backend response; no external sources cited.",
        )
        model_meta = ModelMeta(provider="mock", model="sift-explain")

        if "define" in request.question.lower() and first_block is not None:
            return ConceptTurnResult(
                answer=f"Draft answer for: {request.question}",
                answerSource=answer_source,
                updateDecision=UpdateDecisionDTO(
                    mode=UpdateMode.needs_confirmation,
                    reason="Changing the definition requires confirmation.",
                ),
                proposal=ModelUpdateProposal(
                    baseNoteRevision=concept.note_revision,
                    patchOperations=[
                        ReplacePatchOperation(
                            operation="replace",
                            targetBlockId=first_block.id,
                            oldValueHash=content_hash(first_block.content),
                            newContent=(
                                f"{concept.display_title} is a concept being refined by Sift."
                            ),
                        )
                    ],
                    rationale="This changes the primary explanation block.",
                ),
                memoryPatch=MemoryPatch(openQuestions=[request.question]),
                modelMeta=model_meta,
            )

        if first_block is not None:
            return ConceptTurnResult(
                answer=f"Draft answer for: {request.question}",
                answerSource=answer_source,
                updateDecision=UpdateDecisionDTO(
                    mode=UpdateMode.auto_merge,
                    reason="Adds a low-risk follow-up note.",
                ),
                autoPatch=[
                    AppendPatchOperation(
                        operation="append",
                        targetBlockId=first_block.id,
                        content=f"Follow-up captured: {request.question}",
                    )
                ],
                memoryPatch=MemoryPatch(openQuestions=[request.question]),
                modelMeta=model_meta,
            )

        return ConceptTurnResult(
            answer=f"Draft answer for: {request.question}",
            answerSource=answer_source,
            updateDecision=UpdateDecisionDTO(
                mode=UpdateMode.none,
                reason="No note block exists to update.",
            ),
            memoryPatch=MemoryPatch(openQuestions=[request.question]),
            modelMeta=model_meta,
        )

    async def stream_turn_answer(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ) -> AsyncIterator[ConceptRuntimeDelta | ConceptRuntimeResult]:
        result = await self.answer_turn(
            concept=concept,
            request=request,
            recent_turns=recent_turns,
            card_memory=card_memory,
        )
        for chunk in _chunk_text(result.answer):
            yield ConceptRuntimeDelta(chunk)
        yield ConceptRuntimeResult(result)

    async def answer_maintenance_review(
        self,
        concept: ConceptDTO,
        recent_turns: list[RecentTurn],
        card_memory: str,
    ) -> ConceptTurnResult:
        return await self.answer_turn(
            concept,
            ConceptTurnRequest(
                question=(
                    "Review this card using only the supplied card and conversation. "
                    "Return an append or replace proposal for unlocked blocks only when needed."
                )
            ),
            recent_turns=recent_turns,
            card_memory=card_memory,
        )

    async def summarize_continuity(
        self,
        concept: ConceptDTO,
        source_turns: list[tuple[int, RecentTurn]],
    ) -> ContinuitySummaryResult:
        prior_answers: list[ContinuitySummaryEntry] = []
        for index in range(0, len(source_turns), 2):
            pair = source_turns[index : index + 2]
            prior_answers.append(
                ContinuitySummaryEntry(
                    content="\n".join(f"{turn.role}: {turn.content}" for _, turn in pair),
                    sourceTurnIds=[turn_id for turn_id, _ in pair],
                )
            )
        return ContinuitySummaryResult(priorAnswers=prior_answers)


class SiftRuntimeConceptModelService:
    """Concept model service backed by Sift's lightweight Hermes-style runtime."""

    def __init__(
        self,
        runtime: LightweightHermesRuntime,
    ) -> None:
        self.runtime = runtime
        self._fallback_initial_blocks = MockConceptModelService()

    def initial_blocks(self, title: str) -> list[NoteBlockDTO]:
        return self._fallback_initial_blocks.initial_blocks(title)

    async def create_initial_concept(
        self,
        title: str,
        locale: str,
    ) -> ConceptDTO:
        result = await self.runtime.generate_initial_concept(
            raw_capture=title,
            locale=locale,
        )
        return _concept_from_initial_result(title, result)

    async def stream_initial_concept(
        self,
        title: str,
        locale: str,
    ) -> AsyncIterator[ConceptRuntimeDelta | ConceptInitialRuntimeResult]:
        async for event in self.runtime.stream_initial_concept(
            raw_capture=title,
            locale=locale,
        ):
            yield event

    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ) -> ConceptTurnResult:
        return await self.runtime.answer_concept_turn(
            concept=concept,
            card_memory=card_memory,
            recent_turns=recent_turns or [],
            user_query=request.question,
        )

    async def stream_turn_answer(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ) -> AsyncIterator[ConceptRuntimeDelta | ConceptRuntimeResult]:
        async for event in self.runtime.stream_concept_turn_answer(
            concept=concept,
            card_memory=card_memory,
            recent_turns=recent_turns or [],
            user_query=request.question,
        ):
            yield event

    async def answer_maintenance_review(
        self,
        concept: ConceptDTO,
        recent_turns: list[RecentTurn],
        card_memory: str,
    ) -> ConceptTurnResult:
        maintenance_runtime = LightweightHermesRuntime(
            model_provider=self.runtime.model_provider,
            model=self.runtime.model,
            web_search_tool=self.runtime.web_search_tool,
            web_extract_tool=self.runtime.web_extract_tool,
            web_search_enabled=False,
        )
        return await maintenance_runtime.answer_concept_turn(
            concept=concept,
            card_memory=card_memory,
            recent_turns=recent_turns,
            user_query=(
                "Perform the scheduled knowledge review using only this card and these turns. "
                "Propose append or replace operations for existing unlocked blocks only. "
                "Return no proposal when no durable update is needed."
            ),
        )

    async def summarize_continuity(
        self,
        concept: ConceptDTO,
        source_turns: list[tuple[int, RecentTurn]],
    ) -> ContinuitySummaryResult:
        maintenance_runtime = LightweightHermesRuntime(
            model_provider=self.runtime.model_provider,
            model=self.runtime.model,
            web_search_tool=None,
            web_extract_tool=None,
            web_search_enabled=False,
        )
        return await maintenance_runtime.summarize_concept_continuity(
            concept,
            source_turns,
        )


class ConceptService:
    def __init__(
        self,
        store: Any | None = None,
        model_service: (MockConceptModelService | SiftRuntimeConceptModelService | None) = None,
        principal: CurrentPrincipal | None = None,
    ) -> None:
        self.store = store or InMemoryConceptStore()
        self.model_service = model_service or MockConceptModelService()
        self.principal = principal or DevelopmentPrincipalProvider().current_principal()

    def create_concept(
        self,
        request: CreateConceptRequest,
        idempotency_key: str | None = None,
    ) -> ConceptDTO:
        title = request.raw_capture.strip()
        if idempotency_key:
            payload_hash = _idempotency_payload_hash(request)
            existing = self._existing_capture_result(idempotency_key, payload_hash)
            if existing is not None:
                return existing
            attempt = self.store.create_capture_attempt(
                self.owner_id,
                idempotency_key,
                payload_hash,
                title,
                request.locale,
            )
        else:
            attempt = None
        concept = self._save_concept_with_audit(
            _fallback_initial_concept(title),
            event_type="initialGeneration",
            actor="ai",
        )
        self._append_initial_turn(concept, title)
        if attempt is not None:
            self.store.update_capture_attempt(
                attempt.id,
                status="succeeded",
                concept_id=concept.id,
            )
        return concept

    async def create_concept_async(
        self,
        request: CreateConceptRequest,
        idempotency_key: str | None = None,
    ) -> ConceptDTO:
        title = request.raw_capture.strip()
        if idempotency_key:
            payload_hash = _idempotency_payload_hash(request)
            existing = self._existing_capture_result(idempotency_key, payload_hash)
            if existing is not None:
                return existing
            attempt = self.store.create_capture_attempt(
                self.owner_id,
                idempotency_key,
                payload_hash,
                title,
                request.locale,
            )
        else:
            attempt = None
        try:
            concept = await self.model_service.create_initial_concept(
                title=title,
                locale=request.locale,
            )
        except SiftRuntimeError as error:
            if attempt is not None:
                self.store.update_capture_attempt(
                    attempt.id,
                    status="failed",
                    failure_code=error.code,
                    failure_message=str(error),
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error
        saved = self._save_concept_with_audit(
            concept,
            event_type="initialGeneration",
            actor="ai",
        )
        self._append_initial_turn(saved, title)
        if attempt is not None:
            self.store.update_capture_attempt(
                attempt.id,
                status="succeeded",
                concept_id=saved.id,
            )
        return saved

    async def create_concept_stream(
        self,
        request: CreateConceptRequest,
        idempotency_key: str | None = None,
    ) -> AsyncIterator[ConceptInitialStreamEvent]:
        title = request.raw_capture.strip()
        if idempotency_key:
            payload_hash = _idempotency_payload_hash(request)
            existing = self._existing_capture_result(idempotency_key, payload_hash)
            if existing is not None:
                yield ConceptInitialStreamResult(existing)
                return
            attempt = self.store.create_capture_attempt(
                self.owner_id,
                idempotency_key,
                payload_hash,
                title,
                request.locale,
            )
        else:
            attempt = None
        final_result = None
        try:
            async for event in self.model_service.stream_initial_concept(
                title=title,
                locale=request.locale,
            ):
                if isinstance(event, ConceptRuntimeDelta):
                    yield ConceptTurnStreamDelta(event.content)
                if isinstance(event, ConceptInitialRuntimeResult):
                    final_result = event.result
        except SiftRuntimeError as error:
            if attempt is not None:
                self.store.update_capture_attempt(
                    attempt.id,
                    status="failed",
                    failure_code=error.code,
                    failure_message=str(error),
                )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error

        if final_result is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "stream_incomplete", "message": "Model stream ended early."},
            )
        concept = _concept_from_initial_result(title, final_result)
        saved = self._save_concept_with_audit(
            concept,
            event_type="initialGeneration",
            actor="ai",
        )
        self._append_initial_turn(saved, title)
        if attempt is not None:
            self.store.update_capture_attempt(
                attempt.id,
                status="succeeded",
                concept_id=saved.id,
            )
        yield ConceptInitialStreamResult(saved)

    async def prepare_initial_concept_stream(
        self,
        request: CreateConceptRequest,
    ) -> AsyncIterator[ConceptTurnStreamDelta | ConceptDTO]:
        """Run the fallible model call without mutating durable concept state."""
        title = request.raw_capture.strip()
        final_result: ConceptInitialResult | None = None
        try:
            async for event in self.model_service.stream_initial_concept(
                title=title,
                locale=request.locale,
            ):
                if isinstance(event, ConceptRuntimeDelta):
                    yield ConceptTurnStreamDelta(event.content)
                elif isinstance(event, ConceptInitialRuntimeResult):
                    final_result = event.result
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error
        if final_result is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "stream_incomplete", "message": "Model stream ended early."},
            )
        yield _concept_from_initial_result(title, final_result)

    def commit_prepared_initial_concept(
        self,
        request: CreateConceptRequest,
        concept: ConceptDTO,
        idempotency_key: str,
    ) -> ConceptDTO:
        """Idempotently commit a checkpointed initial model result."""
        payload_hash = _idempotency_payload_hash(request)
        attempt = self.store.get_capture_attempt(self.owner_id, idempotency_key)
        if attempt is not None:
            _raise_if_idempotency_payload_conflict(attempt.payload_hash, payload_hash)
            if attempt.status == "succeeded" and attempt.concept_id is not None:
                return self.store.get_concept(attempt.concept_id, owner_id=self.owner_id)
            try:
                already_saved = self.store.get_concept(concept.id, owner_id=self.owner_id)
            except HTTPException as error:
                if error.status_code != status.HTTP_404_NOT_FOUND:
                    raise
            else:
                self._append_initial_turn(
                    already_saved,
                    request.raw_capture.strip(),
                    operation_key=idempotency_key,
                )
                self.store.update_capture_attempt(
                    attempt.id, status="succeeded", concept_id=already_saved.id
                )
                return already_saved
        else:
            attempt = self.store.create_capture_attempt(
                self.owner_id,
                idempotency_key,
                payload_hash,
                request.raw_capture.strip(),
                request.locale,
            )
        saved = self._save_concept_with_audit(
            concept,
            event_type="initialGeneration",
            actor="ai",
        )
        self._append_initial_turn(saved, request.raw_capture.strip(), operation_key=idempotency_key)
        self.store.update_capture_attempt(attempt.id, status="succeeded", concept_id=saved.id)
        return saved

    def list_concepts(self) -> list[ConceptDTO]:
        return self.store.list_concepts(owner_id=self.owner_id)

    def get_concept(self, concept_id: UUID) -> ConceptDTO:
        return self.store.get_concept(concept_id, owner_id=self.owner_id)

    def set_concepts_archived(
        self,
        concept_ids: list[UUID],
        *,
        archived: bool,
    ) -> list[ConceptDTO]:
        return self.store.set_concepts_archived(
            concept_ids,
            archived=archived,
            owner_id=self.owner_id,
        )

    def update_concept_summary(
        self,
        concept_id: UUID,
        request: UpdateConceptSummaryRequest,
    ) -> ConceptDTO:
        concept = self.store.get_concept(concept_id, owner_id=self.owner_id)
        display_title = request.display_title.strip()
        if not display_title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Concept title cannot be empty.",
            )

        updated = concept.model_copy(
            update={
                "canonical_title": display_title,
                "display_title": display_title,
                "one_line_explanation": request.one_line_explanation.strip(),
                "note_revision": concept.note_revision + 1,
            }
        )
        return self._save_concept_with_audit(
            updated,
            event_type="manualEdit",
            actor="user",
        )

    def update_note_block(
        self,
        concept_id: UUID,
        block_id: UUID,
        request: UpdateNoteBlockRequest,
    ) -> ConceptDTO:
        concept = self.store.get_concept(concept_id, owner_id=self.owner_id)
        content = request.content.strip()
        if not content:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Note block content cannot be empty.",
            )

        found = False
        blocks: list[NoteBlockDTO] = []
        for block in concept.blocks:
            if block.id == block_id:
                found = True
                blocks.append(
                    block.model_copy(
                        update={
                            "content": content,
                            "source": NoteBlockSource.user,
                            "is_user_locked": True,
                        }
                    )
                )
            else:
                blocks.append(block)

        if not found:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Note block not found.",
            )

        updated = concept.model_copy(
            update={
                "maturity": ConceptMaturity.growing,
                "note_revision": concept.note_revision + 1,
                "blocks": blocks,
            }
        )
        return self._save_concept_with_audit(
            updated,
            event_type="manualEdit",
            actor="user",
        )

    def update_concept_note(
        self,
        concept_id: UUID,
        request: UpdateConceptNoteRequest,
    ) -> ConceptDTO:
        concept = self.store.get_concept(concept_id, owner_id=self.owner_id)
        display_title = request.display_title.strip()
        if not display_title:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Concept title cannot be empty.",
            )

        existing_by_id = {block.id: block for block in concept.blocks}
        blocks: list[NoteBlockDTO] = []
        for position, block_request in enumerate(request.blocks):
            content = block_request.content.strip()
            if not content:
                continue
            if block_request.id is None:
                blocks.append(
                    NoteBlockDTO(
                        id=uuid4(),
                        blockType=block_request.block_type,
                        content=content,
                        source=NoteBlockSource.user,
                        isUserLocked=True,
                        revision=1,
                        supportedClaimIds=[],
                        position=position,
                    )
                )
                continue

            existing = existing_by_id.get(block_request.id)
            if existing is None:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Note block does not belong to this concept.",
                )
            changed = existing.content != content or existing.block_type != block_request.block_type
            if changed:
                blocks.append(
                    existing.model_copy(
                        update={
                            "block_type": block_request.block_type,
                            "content": content,
                            "source": NoteBlockSource.user,
                            "is_user_locked": True,
                            "revision": existing.revision + 1,
                            "position": position,
                        }
                    )
                )
            else:
                blocks.append(existing.model_copy(update={"position": position}))

        updated = concept.model_copy(
            update={
                "canonical_title": display_title,
                "display_title": display_title,
                "one_line_explanation": request.one_line_explanation.strip(),
                "maturity": ConceptMaturity.growing,
                "note_revision": concept.note_revision + 1,
                "blocks": blocks,
                "tags": _normalized_names(request.tags),
                "topics": _normalized_names(request.topics),
            }
        )
        return self._save_concept_with_audit(
            updated,
            event_type="manualEdit",
            actor="user",
        )

    def update_concept_organization(
        self,
        concept_id: UUID,
        request: UpdateConceptOrganizationRequest,
    ) -> ConceptDTO:
        concept = self.store.get_concept(concept_id, owner_id=self.owner_id)
        updated = concept.model_copy(
            update={
                "tags": _normalized_names(request.tags),
                "topics": _normalized_names(request.topics),
                "note_revision": concept.note_revision + 1,
            }
        )
        return self._save_concept_with_audit(
            updated,
            event_type="manualEdit",
            actor="user",
        )

    def add_relation(
        self,
        concept_id: UUID,
        request: CreateConceptRelationRequest,
    ) -> ConceptDTO:
        self.store.get_concept(concept_id, owner_id=self.owner_id)
        self.store.get_concept(request.target_concept_id, owner_id=self.owner_id)
        return self.store.add_relation(
            source_concept_id=concept_id,
            target_concept_id=request.target_concept_id,
            relation_type=request.relation_type,
        )

    def remove_relation(self, concept_id: UUID, relation_id: UUID) -> ConceptDTO:
        self.store.get_concept(concept_id, owner_id=self.owner_id)
        return self.store.remove_relation(concept_id, relation_id)

    def list_turns(self, concept_id: UUID) -> list[ConceptHistoryTurnDTO]:
        self.store.get_concept(concept_id, owner_id=self.owner_id)
        return [
            ConceptHistoryTurnDTO(
                role=turn.role,
                content=turn.content,
                answerSource=_answer_source_from_recent_turn(turn),
            )
            for turn in self.store.list_turns(concept_id)
        ]

    @property
    def owner_id(self) -> str:
        return self.principal.user_id

    async def submit_turn(
        self,
        concept_id: UUID,
        request: ConceptTurnRequest,
        idempotency_key: str | None = None,
    ) -> ConceptTurnResponse:
        endpoint = _turn_idempotency_scope(concept_id)
        if idempotency_key:
            payload_hash = _idempotency_payload_hash(request)
            existing = self._existing_turn_result(endpoint, idempotency_key, payload_hash)
            if existing is not None:
                return existing
        concept = self.store.get_concept(concept_id, owner_id=self.owner_id)
        if request.replacing_turn_index == 0:
            response = await self._regenerate_initial_concept(concept, request)
            if idempotency_key:
                self.store.save_idempotency_record(
                    self.owner_id,
                    endpoint,
                    idempotency_key,
                    payload_hash,
                    response.model_dump_json(by_alias=True),
                )
            return response
        recent_turns, card_memory = self._context_before_replacement(concept.id, request)
        try:
            result = await self.model_service.answer_turn(
                concept,
                request,
                recent_turns=recent_turns,
                card_memory=card_memory,
            )
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error

        response = self._finalize_turn_response(concept, request, result)
        if idempotency_key:
            self.store.save_idempotency_record(
                self.owner_id,
                endpoint,
                idempotency_key,
                payload_hash,
                response.model_dump_json(by_alias=True),
            )
        return response

    async def submit_turn_stream(
        self,
        concept_id: UUID,
        request: ConceptTurnRequest,
        idempotency_key: str | None = None,
    ) -> AsyncIterator[ConceptTurnStreamEvent]:
        endpoint = _turn_idempotency_scope(concept_id)
        if idempotency_key:
            payload_hash = _idempotency_payload_hash(request)
            existing = self._existing_turn_result(endpoint, idempotency_key, payload_hash)
            if existing is not None:
                yield ConceptTurnStreamResult(existing)
                return
        concept = self.store.get_concept(concept_id, owner_id=self.owner_id)
        if request.replacing_turn_index == 0:
            async for event in self._regenerate_initial_concept_stream(concept, request):
                if isinstance(event, ConceptTurnStreamResult) and idempotency_key:
                    self.store.save_idempotency_record(
                        self.owner_id,
                        endpoint,
                        idempotency_key,
                        payload_hash,
                        event.response.model_dump_json(by_alias=True),
                    )
                yield event
            return
        recent_turns, card_memory = self._context_before_replacement(concept.id, request)
        final_result: ConceptTurnResult | None = None
        try:
            async for event in self.model_service.stream_turn_answer(
                concept,
                request,
                recent_turns=recent_turns,
                card_memory=card_memory,
            ):
                if isinstance(event, ConceptRuntimeDelta):
                    yield ConceptTurnStreamDelta(event.content)
                if isinstance(event, ConceptRuntimeResult):
                    final_result = event.result
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error

        if final_result is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "stream_incomplete", "message": "Model stream ended early."},
            )

        response = self._finalize_turn_response(concept, request, final_result)
        if idempotency_key:
            self.store.save_idempotency_record(
                self.owner_id,
                endpoint,
                idempotency_key,
                payload_hash,
                response.model_dump_json(by_alias=True),
            )
        yield ConceptTurnStreamResult(response)

    async def prepare_turn_stream(
        self,
        concept_id: UUID,
        request: ConceptTurnRequest,
    ) -> AsyncIterator[ConceptTurnStreamDelta | PreparedTurnResult]:
        """Run a follow-up model call without writing turns, proposals, or notes."""
        concept = self.store.get_concept(concept_id, owner_id=self.owner_id)
        if request.replacing_turn_index == 0:
            final_result: ConceptInitialResult | None = None
            try:
                async for event in self.model_service.stream_initial_concept(
                    title=request.question.strip(),
                    locale="en",
                ):
                    if isinstance(event, ConceptRuntimeDelta):
                        yield ConceptTurnStreamDelta(event.content)
                    elif isinstance(event, ConceptInitialRuntimeResult):
                        final_result = event.result
            except SiftRuntimeError as error:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={"code": error.code, "message": str(error)},
                ) from error
            if final_result is None:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail={"code": "stream_incomplete", "message": "Model stream ended early."},
                )
            regenerated = _concept_from_initial_result(
                request.question.strip(), final_result
            ).model_copy(update={"id": concept.id, "note_revision": concept.note_revision + 1})
            yield PreparedTurnResult(
                base_note_revision=concept.note_revision,
                regenerated_concept=regenerated,
            )
            return

        recent_turns, card_memory = self._context_before_replacement(concept.id, request)
        final_result: ConceptTurnResult | None = None
        try:
            async for event in self.model_service.stream_turn_answer(
                concept,
                request,
                recent_turns=recent_turns,
                card_memory=card_memory,
            ):
                if isinstance(event, ConceptRuntimeDelta):
                    yield ConceptTurnStreamDelta(event.content)
                elif isinstance(event, ConceptRuntimeResult):
                    final_result = event.result
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error
        if final_result is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "stream_incomplete", "message": "Model stream ended early."},
            )
        yield PreparedTurnResult(
            base_note_revision=concept.note_revision,
            turn_result=final_result,
        )

    def commit_prepared_turn(
        self,
        concept_id: UUID,
        request: ConceptTurnRequest,
        prepared: PreparedTurnResult,
        idempotency_key: str,
    ) -> ConceptTurnResponse:
        """Idempotently apply a checkpointed follow-up result."""
        endpoint = _turn_idempotency_scope(concept_id)
        payload_hash = _idempotency_payload_hash(request)
        existing = self._existing_turn_result(endpoint, idempotency_key, payload_hash)
        if existing is not None:
            return existing
        concept = self.store.get_concept(concept_id, owner_id=self.owner_id)
        if concept.note_revision != prepared.base_note_revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "concept_revision_changed",
                    "message": "The card changed after model generation; start a new follow-up.",
                },
            )
        if prepared.regenerated_concept is not None:
            saved = self._save_concept_with_audit(
                prepared.regenerated_concept,
                event_type="retryGeneration",
                actor="ai",
            )
            answer = (saved.initial_answer or saved.one_line_explanation).strip()
            answer_source = saved.answer_source or _fallback_answer_source()
            self.store.replace_turn_pair_from_index(
                saved.id,
                0,
                request.question,
                answer,
                answer_source=answer_source,
                operation_key=idempotency_key,
            )
            response = ConceptTurnResponse(
                answer=answer,
                answerSource=answer_source,
                updateMode=UpdateMode.none,
                concept=saved,
                proposal=None,
            )
        else:
            if prepared.turn_result is None:
                raise ValueError("Prepared turn has no result.")
            response = self._finalize_turn_response(
                concept,
                request,
                prepared.turn_result,
                operation_key=idempotency_key,
            )
        self.store.save_idempotency_record(
            self.owner_id,
            endpoint,
            idempotency_key,
            payload_hash,
            response.model_dump_json(by_alias=True),
        )
        return response

    def merge_proposal(
        self,
        proposal_id: UUID,
        idempotency_key: str | None = None,
    ) -> ConceptDTO:
        endpoint = _proposal_merge_idempotency_scope(proposal_id)
        if idempotency_key:
            payload_hash = _idempotency_payload_hash({"proposalId": str(proposal_id)})
            existing = self._existing_concept_result(endpoint, idempotency_key, payload_hash)
            if existing is not None:
                return existing
        proposal = self.store.get_proposal(proposal_id)
        concept = self.store.get_concept(
            self.store.get_proposal_concept_id(proposal_id),
            owner_id=self.owner_id,
        )
        if proposal.status != ProposalStatus.proposed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Update proposal is not mergeable.",
            )

        try:
            updated = self._apply_patch_operations(
                concept,
                proposal.base_note_revision,
                proposal.patch_operations,
                event_type="confirmedMerge",
                actor="user",
                proposal_id=proposal.id,
            )
        except PatchApplicationError as error:
            self.store.save_proposal(proposal.model_copy(update={"status": ProposalStatus.stale}))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": str(error)},
            ) from error

        self.store.save_proposal(proposal.model_copy(update={"status": ProposalStatus.accepted}))
        if idempotency_key:
            self.store.save_idempotency_record(
                self.owner_id,
                endpoint,
                idempotency_key,
                payload_hash,
                updated.model_dump_json(by_alias=True),
            )
        return updated

    def dismiss_proposal(self, proposal_id: UUID) -> None:
        proposal = self.store.get_proposal(proposal_id)
        self.store.get_concept(
            self.store.get_proposal_concept_id(proposal_id),
            owner_id=self.owner_id,
        )
        self.store.save_proposal(proposal.model_copy(update={"status": ProposalStatus.dismissed}))

    def list_proposals(
        self, concept_id: UUID, proposal_status: ProposalStatus | None = None
    ) -> list[UpdateProposalDTO]:
        return self.store.list_proposals(concept_id, self.owner_id, proposal_status)

    def list_revisions(self, concept_id: UUID) -> list[NoteRevisionSummaryDTO]:
        return self.store.list_revisions(concept_id, self.owner_id)

    def get_revision(self, concept_id: UUID, revision: int) -> NoteRevisionDTO:
        return self.store.get_revision(concept_id, revision, self.owner_id)

    def restore_revision(self, concept_id: UUID, revision: int) -> ConceptDTO:
        return self.store.restore_revision(concept_id, revision, self.owner_id)

    def _finalize_turn_response(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        result: ConceptTurnResult,
        operation_key: str | None = None,
    ) -> ConceptTurnResponse:
        self._persist_answer_sources(concept.id, result.answer_source)
        if request.replacing_turn_index is None:
            self.store.append_turn_pair(
                concept.id,
                request.question,
                result.answer,
                answer_source=result.answer_source,
                operation_key=operation_key,
            )
        else:
            self.store.replace_turn_pair_from_index(
                concept.id,
                request.replacing_turn_index,
                request.question,
                result.answer,
                answer_source=result.answer_source,
                operation_key=operation_key,
            )

        return ConceptTurnResponse(
            answer=result.answer,
            answerSource=result.answer_source,
            updateMode=UpdateMode.none,
            concept=concept,
            proposal=None,
        )

    def _recent_turns_before_replacement(
        self,
        concept_id: UUID,
        request: ConceptTurnRequest,
    ) -> list[RecentTurn]:
        if request.replacing_turn_index is None:
            return self.store.get_recent_turns(concept_id)
        turns = self.store.list_turns(concept_id)
        _validate_replacement_turn(turns, request.replacing_turn_index)
        return turns[: request.replacing_turn_index][-10:]

    def _context_before_replacement(
        self,
        concept_id: UUID,
        request: ConceptTurnRequest,
    ) -> tuple[list[RecentTurn], str]:
        if request.replacing_turn_index is None and hasattr(self.store, "get_continuity_context"):
            return self.store.get_continuity_context(concept_id)
        return self._recent_turns_before_replacement(concept_id, request), ""

    async def _regenerate_initial_concept(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
    ) -> ConceptTurnResponse:
        try:
            generated = await self.model_service.create_initial_concept(
                title=request.question.strip(),
                locale="en",
            )
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error
        regenerated = generated.model_copy(
            update={"id": concept.id, "note_revision": concept.note_revision + 1}
        )
        saved = self._save_concept_with_audit(
            regenerated,
            event_type="retryGeneration",
            actor="ai",
        )
        answer = (saved.initial_answer or saved.one_line_explanation).strip()
        answer_source = saved.answer_source or _fallback_answer_source()
        self.store.replace_turn_pair_from_index(
            saved.id,
            0,
            request.question,
            answer,
            answer_source=answer_source,
        )
        return ConceptTurnResponse(
            answer=answer,
            answerSource=answer_source,
            updateMode=UpdateMode.none,
            concept=saved,
            proposal=None,
        )

    async def _regenerate_initial_concept_stream(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
    ) -> AsyncIterator[ConceptTurnStreamEvent]:
        final_result = None
        try:
            async for event in self.model_service.stream_initial_concept(
                title=request.question.strip(),
                locale="en",
            ):
                if isinstance(event, ConceptRuntimeDelta):
                    yield ConceptTurnStreamDelta(event.content)
                if isinstance(event, ConceptInitialRuntimeResult):
                    final_result = event.result
        except SiftRuntimeError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error
        if final_result is None:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": "stream_incomplete", "message": "Model stream ended early."},
            )
        regenerated = _concept_from_initial_result(
            request.question.strip(),
            final_result,
        ).model_copy(update={"id": concept.id, "note_revision": concept.note_revision + 1})
        saved = self._save_concept_with_audit(
            regenerated,
            event_type="retryGeneration",
            actor="ai",
        )
        answer = (saved.initial_answer or saved.one_line_explanation).strip()
        answer_source = saved.answer_source or _fallback_answer_source()
        self.store.replace_turn_pair_from_index(
            saved.id,
            0,
            request.question,
            answer,
            answer_source=answer_source,
        )
        yield ConceptTurnStreamResult(
            ConceptTurnResponse(
                answer=answer,
                answerSource=answer_source,
                updateMode=UpdateMode.none,
                concept=saved,
                proposal=None,
            )
        )

    def _persist_answer_sources(
        self,
        concept_id: UUID,
        answer_source: AnswerSourceDTO,
    ) -> dict[str, UUID]:
        sources = _sources_from_answer_source(concept_id, answer_source)
        if sources and hasattr(self.store, "add_sources"):
            persisted = self.store.add_sources(concept_id, sources)
        else:
            persisted = sources
        return {
            citation.source_id: source.id
            for citation, source in zip(answer_source.citations, persisted, strict=False)
            if citation.source_id is not None
        }

    def _persist_turn_learning_state(
        self,
        concept: ConceptDTO,
        result: ConceptTurnResult,
    ) -> None:
        learning_updates = [
            *result.learning_state_updates,
            *_learning_updates_from_memory_patch(result.memory_patch),
        ]
        if learning_updates and hasattr(self.store, "add_learning_state_updates"):
            self.store.add_learning_state_updates(concept.id, learning_updates)

    def _apply_candidate_updates(
        self,
        concept: ConceptDTO,
        result: ConceptTurnResult,
        source_id_map: dict[str, UUID] | None = None,
    ) -> tuple[ConceptDTO, UpdateProposalDTO | None, list[ClaimDTO]]:
        if not result.candidate_updates:
            return concept, None, []
        auto_operations: list[Any] = []
        claims: list[ClaimDTO] = []
        proposal_operations: list[Any] = []
        proposal_rationales: list[str] = []

        for update in result.candidate_updates:
            decision = _candidate_decision(concept, update)
            if decision == "drop":
                continue
            if decision == "proposal":
                operation = _candidate_to_patch_operation(update, concept)
                if operation is not None:
                    proposal_operations.append(operation)
                    proposal_rationales.append(_candidate_rationale(update))
                continue
            if update.operation == CandidateUpdateOperation.add_claim and update.content:
                claim = _claim_from_candidate(
                    concept.id,
                    update,
                    source_id_map or {},
                )
                if claim is not None:
                    claims.append(claim)
                continue
            operation = _candidate_to_patch_operation(update, concept)
            if operation is not None:
                auto_operations.append(operation)

        if auto_operations:
            concept = self._apply_auto_patch(concept, auto_operations)
        proposal = None
        if proposal_operations:
            proposal = UpdateProposalDTO(
                id=uuid4(),
                baseNoteRevision=concept.note_revision,
                patchOperations=proposal_operations,
                rationale=" ".join(proposal_rationales) or "Suggested durable knowledge update.",
                confidence=result.answer_source.confidence,
                status=ProposalStatus.proposed,
            )
            self.store.save_proposal(proposal, concept_id=concept.id)
        return concept, proposal, claims

    def _apply_auto_patch(
        self,
        concept: ConceptDTO,
        operations: list,
    ) -> ConceptDTO:
        try:
            return self._apply_patch_operations(
                concept,
                concept.note_revision,
                operations,
                event_type="autoMerge",
                actor="ai",
            )
        except PatchApplicationError:
            return concept

    def _apply_patch_operations(
        self,
        concept: ConceptDTO,
        base_revision: int,
        operations: list,
        event_type: str,
        actor: str,
        proposal_id: UUID | None = None,
    ) -> ConceptDTO:
        result = apply_patch_operations(
            NoteSnapshot(revision=concept.note_revision, blocks=tuple(concept.blocks)),
            base_revision=base_revision,
            operations=operations,
        )
        self._validate_relation_operations(concept, result.relation_operations)
        updated = concept.model_copy(
            update={
                "maturity": ConceptMaturity.growing,
                "note_revision": result.revision,
                "blocks": list(result.blocks),
            }
        )
        saved = self._save_concept_with_audit(
            updated,
            event_type=event_type,
            actor=actor,
            proposal_id=proposal_id,
        )
        for operation in result.relation_operations:
            saved = self.store.add_relation(
                source_concept_id=saved.id,
                target_concept_id=operation.target_concept_id,
                relation_type=operation.relation_type,
            )
        return saved

    def _save_concept_with_audit(
        self,
        concept: ConceptDTO,
        event_type: str,
        actor: str,
        proposal_id: UUID | None = None,
    ) -> ConceptDTO:
        saved = self.store.save_concept(concept, owner_id=self.owner_id)
        self.store.record_note_audit(
            saved.id,
            event_type=event_type,
            actor=actor,
            proposal_id=proposal_id,
        )
        return saved

    def _append_initial_turn(
        self, concept: ConceptDTO, raw_capture: str, operation_key: str | None = None
    ) -> None:
        self.store.append_turn_pair(
            concept.id,
            raw_capture,
            (concept.initial_answer or concept.one_line_explanation).strip(),
            answer_source=concept.answer_source,
            operation_key=operation_key,
        )

    def _existing_capture_result(
        self,
        idempotency_key: str,
        payload_hash: str,
    ) -> ConceptDTO | None:
        attempt = self.store.get_capture_attempt(self.owner_id, idempotency_key)
        if attempt is None:
            return None
        _raise_if_idempotency_payload_conflict(attempt.payload_hash, payload_hash)
        if attempt.status == "succeeded" and attempt.concept_id is not None:
            return self.store.get_concept(attempt.concept_id, owner_id=self.owner_id)
        if attempt.status == "failed":
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": attempt.failure_code or "generation_failed",
                    "message": attempt.failure_message or "Capture generation failed.",
                },
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "generation_in_progress", "message": "Capture is still generating."},
        )

    def _existing_turn_result(
        self,
        endpoint: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> ConceptTurnResponse | None:
        record = self.store.get_idempotency_record(
            self.owner_id,
            endpoint,
            idempotency_key,
        )
        if record is None or record.response_json is None:
            return None
        _raise_if_idempotency_payload_conflict(record.payload_hash, payload_hash)
        return ConceptTurnResponse.model_validate_json(record.response_json)

    def _existing_concept_result(
        self,
        endpoint: str,
        idempotency_key: str,
        payload_hash: str,
    ) -> ConceptDTO | None:
        record = self.store.get_idempotency_record(
            self.owner_id,
            endpoint,
            idempotency_key,
        )
        if record is None or record.response_json is None:
            return None
        _raise_if_idempotency_payload_conflict(record.payload_hash, payload_hash)
        return ConceptDTO.model_validate_json(record.response_json)

    def _validate_relation_operations(
        self,
        concept: ConceptDTO,
        operations: tuple[AddRelationPatchOperation, ...],
    ) -> None:
        for operation in operations:
            if operation.target_concept_id == concept.id:
                raise PatchApplicationError(
                    PatchErrorCode.unsupported_operation,
                    "Patch cannot relate a concept to itself.",
                )
            try:
                self.store.get_concept(operation.target_concept_id, owner_id=self.owner_id)
            except HTTPException as error:
                if error.status_code == status.HTTP_404_NOT_FOUND:
                    raise PatchApplicationError(
                        PatchErrorCode.missing_concept,
                        "Patch relation target concept does not exist.",
                    ) from error
                raise

    def _create_update_proposal(
        self,
        concept_id: UUID,
        result: ConceptTurnResult,
    ) -> UpdateProposalDTO:
        if result.proposal is None:
            raise ValueError("Cannot create update proposal without model proposal.")
        proposal = UpdateProposalDTO(
            id=uuid4(),
            baseNoteRevision=result.proposal.base_note_revision,
            patchOperations=result.proposal.patch_operations,
            rationale=result.proposal.rationale,
            confidence=result.answer_source.confidence,
            status=ProposalStatus.proposed,
        )
        # Temporary MVP shortcut: proposal.id is not the concept id, so store a hidden mapping by
        # keeping concept id in an in-memory side table once the repository layer lands.
        self.store.save_proposal(proposal, concept_id=concept_id)
        return proposal


def should_use_web_search(question: str) -> bool:
    _ = question
    return False


def _validate_replacement_turn(turns: list[RecentTurn], turn_index: int) -> None:
    if turn_index >= len(turns) or turns[turn_index].role != "user":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "invalid_turn_replacement", "message": "Turn is not replaceable."},
        )


def _fallback_answer_source() -> AnswerSourceDTO:
    return AnswerSourceDTO(
        sourceType=AnswerSourceType.model_knowledge,
        confidence=0.5,
        uncertaintyNote=None,
    )


def _fallback_initial_concept(title: str) -> ConceptDTO:
    return ConceptDTO(
        id=uuid4(),
        canonicalTitle=title,
        displayTitle=title,
        oneLineExplanation=f"{title} captured as a draft concept.",
        maturity=ConceptMaturity.initial,
        captureStatus=CaptureStatus.ready,
        noteRevision=1,
        blocks=[
            block.model_copy(update={"position": position})
            for position, block in enumerate(MockConceptModelService().initial_blocks(title))
        ],
        answerSource=AnswerSourceDTO(
            sourceType=AnswerSourceType.model_knowledge,
            confidence=0.5,
            uncertaintyNote="Mock backend response; no external sources cited.",
        ),
    )


def _concept_from_initial_result(title: str, result) -> ConceptDTO:
    display_title = result.display_title.strip() or title
    canonical_title = result.canonical_title.strip() or display_title
    return ConceptDTO(
        id=uuid4(),
        canonicalTitle=canonical_title,
        displayTitle=display_title,
        oneLineExplanation=result.one_line_explanation.strip(),
        initialAnswer=result.answer.strip(),
        maturity=ConceptMaturity.initial,
        captureStatus=CaptureStatus.ready,
        noteRevision=1,
        blocks=[
            NoteBlockDTO(
                id=uuid4(),
                blockType=block.block_type,
                content=block.content.strip(),
                source=NoteBlockSource.ai,
                isUserLocked=False,
                position=position,
            )
            for position, block in enumerate(result.blocks)
            if block.content.strip()
        ],
        tags=_names_from_suggestions(result.suggested_tags),
        topics=_names_from_suggestions(result.suggested_topics),
        answerSource=result.answer_source,
    )


def _initial_result_from_concept(concept: ConceptDTO) -> ConceptInitialResult:
    return ConceptInitialResult(
        canonicalTitle=concept.canonical_title,
        displayTitle=concept.display_title,
        oneLineExplanation=concept.one_line_explanation,
        answer=(concept.initial_answer or concept.one_line_explanation).strip(),
        blocks=[
            {
                "blockType": block.block_type,
                "content": block.content,
            }
            for block in concept.blocks
        ],
        suggestedTags=[{"name": tag, "confidence": 0.5} for tag in concept.tags],
        suggestedTopics=[{"name": topic, "confidence": 0.5} for topic in concept.topics],
        answerSource=concept.answer_source
        or AnswerSourceDTO(
            sourceType=AnswerSourceType.model_knowledge,
            confidence=0.5,
            uncertaintyNote=None,
        ),
        modelMeta=ModelMeta(provider="mock", model="sift-explain"),
    )


def _sources_from_answer_source(
    concept_id: UUID,
    answer_source: AnswerSourceDTO,
) -> list[SourceDTO]:
    if answer_source.source_type not in {
        AnswerSourceType.search_discovered,
        AnswerSourceType.source_read,
    }:
        return []
    return [
        SourceDTO(
            id=uuid4(),
            conceptId=concept_id,
            title=citation.title,
            url=citation.url,
            sourceType=SourceType.secondary,
        )
        for citation in answer_source.citations
        if citation.source_id is not None
    ]


def _learning_updates_from_memory_patch(memory_patch: MemoryPatch) -> list[LearningStateUpdateDTO]:
    updates: list[LearningStateUpdateDTO] = []
    updates.extend(
        LearningStateUpdateDTO(
            field=LearningStateField.confirmed_understanding,
            content=item,
            origin=LearningStateOrigin.assistant_inference,
        )
        for item in memory_patch.confirmed_understanding
    )
    updates.extend(
        LearningStateUpdateDTO(
            field=LearningStateField.open_questions,
            content=item,
            origin=LearningStateOrigin.assistant_inference,
        )
        for item in memory_patch.open_questions
    )
    updates.extend(
        LearningStateUpdateDTO(
            field=LearningStateField.user_context,
            content=item,
            origin=LearningStateOrigin.assistant_inference,
        )
        for item in memory_patch.user_preferences
    )
    return updates


def _candidate_decision(concept: ConceptDTO, update: CandidateUpdate) -> str:
    if not update.content and update.operation not in {CandidateUpdateOperation.add_relation}:
        return "drop"
    if (
        update.evidence_status != EvidenceStatus.source_backed
        and update.time_sensitivity == TimeSensitivity.time_sensitive
    ):
        return "drop"
    if update.operation in {
        CandidateUpdateOperation.replace_block,
        CandidateUpdateOperation.replace_claim,
    }:
        return "proposal"
    if update.operation == CandidateUpdateOperation.append_block and update.target_block_id:
        block = _block_by_id(concept, update.target_block_id)
        if block is None:
            return "drop"
        if block.source != NoteBlockSource.ai or block.is_user_locked:
            return "proposal"
    return "auto"


def _candidate_to_patch_operation(
    update: CandidateUpdate,
    concept: ConceptDTO,
) -> AppendPatchOperation | ReplacePatchOperation | AddRelationPatchOperation | None:
    if update.operation == CandidateUpdateOperation.add_relation:
        if update.target_concept_id is None:
            return None
        return AddRelationPatchOperation(
            operation="addRelation",
            targetConceptId=update.target_concept_id,
            relationType=update.relation_type or "related",
        )
    if update.operation in {
        CandidateUpdateOperation.append_block,
        CandidateUpdateOperation.add_open_question,
    }:
        content = update.content or ""
        target_block_id = update.target_block_id or _append_target_block_id(concept, update)
        if target_block_id is None:
            return None
        return AppendPatchOperation(
            operation="append",
            targetBlockId=target_block_id,
            content=content,
        )
    if update.operation == CandidateUpdateOperation.replace_block:
        if update.target_block_id is None or not update.content:
            return None
        block = _block_by_id(concept, update.target_block_id)
        if block is None:
            return None
        return ReplacePatchOperation(
            operation="replace",
            targetBlockId=block.id,
            oldValueHash=content_hash(block.content),
            newContent=update.content,
        )
    return None


def _append_target_block_id(concept: ConceptDTO, update: CandidateUpdate) -> UUID | None:
    if update.operation == CandidateUpdateOperation.add_open_question:
        block_type = NoteBlockType.open_question
    else:
        block_type = update.block_type or NoteBlockType.user_takeaways
    for block in concept.blocks:
        if block.block_type == block_type and block.source == NoteBlockSource.ai:
            return block.id
    if not concept.blocks:
        return None
    return concept.blocks[-1].id


def _claim_from_candidate(
    concept_id: UUID,
    update: CandidateUpdate,
    source_id_map: dict[str, UUID],
) -> ClaimDTO | None:
    source_ids = [
        source_id_map[source_id] for source_id in update.source_ids if source_id in source_id_map
    ]
    if update.evidence_status == EvidenceStatus.source_backed and not source_ids:
        return None
    if update.evidence_status != EvidenceStatus.source_backed:
        source_ids = []
    return ClaimDTO(
        id=uuid4(),
        conceptId=concept_id,
        statement=update.content or "",
        type=update.claim_type or ClaimType.fact,
        evidenceStatus=update.evidence_status,
        timeSensitivity=update.time_sensitivity,
        sourceIds=source_ids,
    )


def _candidate_rationale(update: CandidateUpdate) -> str:
    if update.operation == CandidateUpdateOperation.replace_block:
        return "Suggested update modifies existing card content."
    if update.operation == CandidateUpdateOperation.replace_claim:
        return "Suggested update replaces an existing claim."
    return "Suggested update requires confirmation."


def _block_by_id(concept: ConceptDTO, block_id: UUID) -> NoteBlockDTO | None:
    for block in concept.blocks:
        if block.id == block_id:
            return block
    return None


def _answer_source_from_recent_turn(turn: RecentTurn) -> AnswerSourceDTO | None:
    if turn.answer_source_json is None:
        return None
    try:
        payload = json.loads(turn.answer_source_json)
    except json.JSONDecodeError:
        return None
    return AnswerSourceDTO.model_validate(payload)


def _is_non_durable_followup(question: str) -> bool:
    normalized = question.strip()
    if not normalized:
        return True
    if len(normalized) <= 3 and not any(char.isalpha() for char in normalized):
        return True
    return normalized.casefold() in {
        "hi",
        "hello",
        "test",
        "testing",
        "ping",
        "111",
        "123",
        "测试",
    }


def _idempotency_payload_hash(payload: Any) -> str:
    if hasattr(payload, "model_dump"):
        payload = payload.model_dump(mode="json", by_alias=True)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return sha256(canonical.encode("utf-8")).hexdigest()


def _turn_idempotency_scope(concept_id: UUID) -> str:
    return f"turn:{concept_id}"


def _proposal_merge_idempotency_scope(proposal_id: UUID) -> str:
    return f"proposal-merge:{proposal_id}"


def _raise_if_idempotency_payload_conflict(
    existing_hash: str | None,
    requested_hash: str,
) -> None:
    if existing_hash is None or existing_hash == requested_hash:
        return
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "idempotency_payload_conflict",
            "message": "Idempotency key already belongs to a different operation payload.",
        },
    )


def _names_from_suggestions(suggestions: list) -> list[str]:
    return _normalized_names([suggestion.name for suggestion in suggestions])


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


def _chunk_text(text: str, size: int = 12) -> list[str]:
    return [text[index : index + size] for index in range(0, len(text), size)]
