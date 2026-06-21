from uuid import UUID, uuid4

from fastapi import HTTPException, status

from sift_backend.ai.model_gateway import ConceptModelGateway, ConceptModelGatewayError
from sift_backend.notes.patch_engine import (
    NoteSnapshot,
    PatchApplicationError,
    apply_patch_operations,
    content_hash,
)
from sift_backend.schemas.common import (
    AnswerSourceType,
    CaptureStatus,
    ConceptMaturity,
    NoteBlockSource,
    NoteBlockType,
    ProposalStatus,
    UpdateMode,
)
from sift_backend.schemas.concepts import (
    AnswerSourceDTO,
    ConceptDTO,
    ConceptTurnRequest,
    ConceptTurnResponse,
    CreateConceptRequest,
    NoteBlockDTO,
    UpdateDecisionDTO,
    UpdateProposalDTO,
)
from sift_backend.schemas.model_outputs import (
    ConceptTurnResult,
    MemoryPatch,
    ModelMeta,
    ModelUpdateProposal,
)
from sift_backend.schemas.patches import AppendPatchOperation, ReplacePatchOperation


class InMemoryConceptStore:
    """Temporary store for API contract development before PostgreSQL lands."""

    def __init__(self) -> None:
        self.concepts: dict[UUID, ConceptDTO] = {}
        self.proposals: dict[UUID, UpdateProposalDTO] = {}
        self.proposal_concept_ids: dict[UUID, UUID] = {}

    def save_concept(self, concept: ConceptDTO) -> ConceptDTO:
        self.concepts[concept.id] = concept
        return concept

    def get_concept(self, concept_id: UUID) -> ConceptDTO:
        try:
            return self.concepts[concept_id]
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Concept not found.",
            ) from error

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


class MockConceptModelService:
    """Deterministic stand-in for LiteLLM-backed generation while service wiring lands."""

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


class LiteLLMConceptModelService:
    """Concept model service backed by Sift's LiteLLM model gateway."""

    def __init__(
        self,
        gateway: ConceptModelGateway,
        model_alias: str,
    ) -> None:
        self.gateway = gateway
        self.model_alias = model_alias
        self._fallback_initial_blocks = MockConceptModelService()

    def initial_blocks(self, title: str) -> list[NoteBlockDTO]:
        return self._fallback_initial_blocks.initial_blocks(title)

    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
    ) -> ConceptTurnResult:
        return await self.gateway.answer_concept_turn(
            concept=concept,
            card_memory="",
            recent_turns=[],
            user_query=request.question,
            model_alias=self.model_alias,
        )


class ConceptService:
    def __init__(
        self,
        store: InMemoryConceptStore | None = None,
        model_service: MockConceptModelService | LiteLLMConceptModelService | None = None,
    ) -> None:
        self.store = store or InMemoryConceptStore()
        self.model_service = model_service or MockConceptModelService()

    def create_concept(self, request: CreateConceptRequest) -> ConceptDTO:
        title = request.raw_capture.strip()
        concept = ConceptDTO(
            id=uuid4(),
            canonicalTitle=title,
            displayTitle=title,
            oneLineExplanation=f"{title} captured as a draft concept.",
            maturity=ConceptMaturity.initial,
            captureStatus=CaptureStatus.ready,
            noteRevision=1,
            blocks=self.model_service.initial_blocks(title),
        )
        return self.store.save_concept(concept)

    async def submit_turn(
        self,
        concept_id: UUID,
        request: ConceptTurnRequest,
    ) -> ConceptTurnResponse:
        concept = self.store.get_concept(concept_id)
        try:
            result = await self.model_service.answer_turn(concept, request)
        except ConceptModelGatewayError as error:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"code": error.code, "message": str(error)},
            ) from error

        if result.update_mode == UpdateMode.auto_merge and result.auto_patch:
            concept = self._apply_auto_patch(concept, result.auto_patch)
            proposal = None
        elif result.update_mode == UpdateMode.needs_confirmation and result.proposal:
            proposal = self._create_update_proposal(concept.id, result)
        else:
            proposal = None

        return ConceptTurnResponse(
            answer=result.answer,
            answerSource=result.answer_source,
            updateMode=result.update_mode,
            concept=concept,
            proposal=proposal,
        )

    def merge_proposal(self, proposal_id: UUID) -> ConceptDTO:
        proposal = self.store.get_proposal(proposal_id)
        if proposal.status != ProposalStatus.proposed:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Update proposal is not mergeable.",
            )

        concept = self.store.get_concept(self.store.get_proposal_concept_id(proposal_id))
        try:
            updated = self._apply_patch_operations(
                concept,
                proposal.base_note_revision,
                proposal.patch_operations,
            )
        except PatchApplicationError as error:
            self.store.save_proposal(proposal.model_copy(update={"status": ProposalStatus.stale}))
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": error.code, "message": str(error)},
            ) from error

        self.store.save_proposal(proposal.model_copy(update={"status": ProposalStatus.accepted}))
        return updated

    def dismiss_proposal(self, proposal_id: UUID) -> None:
        proposal = self.store.get_proposal(proposal_id)
        self.store.save_proposal(proposal.model_copy(update={"status": ProposalStatus.dismissed}))

    def _apply_auto_patch(
        self,
        concept: ConceptDTO,
        operations: list,
    ) -> ConceptDTO:
        try:
            return self._apply_patch_operations(concept, concept.note_revision, operations)
        except PatchApplicationError:
            return concept

    def _apply_patch_operations(
        self,
        concept: ConceptDTO,
        base_revision: int,
        operations: list,
    ) -> ConceptDTO:
        result = apply_patch_operations(
            NoteSnapshot(revision=concept.note_revision, blocks=tuple(concept.blocks)),
            base_revision=base_revision,
            operations=operations,
        )
        updated = concept.model_copy(
            update={
                "maturity": ConceptMaturity.growing,
                "note_revision": result.revision,
                "blocks": list(result.blocks),
            }
        )
        return self.store.save_concept(updated)

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
