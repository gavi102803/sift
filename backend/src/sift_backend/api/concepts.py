from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, status

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
    UpdateProposalDTO,
)

router = APIRouter(prefix="/v1", tags=["concepts"])


class InMemoryConceptStore:
    """Temporary store for API contract development before PostgreSQL lands."""

    def __init__(self) -> None:
        self.concepts: dict[UUID, ConceptDTO] = {}
        self.proposals: dict[UUID, UpdateProposalDTO] = {}

    def create_concept(self, request: CreateConceptRequest) -> ConceptDTO:
        concept_id = uuid4()
        title = request.raw_capture.strip()
        concept = ConceptDTO(
            id=concept_id,
            canonicalTitle=title,
            displayTitle=title,
            oneLineExplanation=f"{title} captured as a draft concept.",
            maturity=ConceptMaturity.initial,
            captureStatus=CaptureStatus.ready,
            noteRevision=1,
            blocks=[
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
            ],
        )
        self.concepts[concept_id] = concept
        return concept

    def get_concept(self, concept_id: UUID) -> ConceptDTO:
        try:
            return self.concepts[concept_id]
        except KeyError as error:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Concept not found.",
            ) from error

    def submit_turn(self, concept_id: UUID, request: ConceptTurnRequest) -> ConceptTurnResponse:
        concept = self.get_concept(concept_id)
        updated = concept.model_copy(
            update={
                "maturity": ConceptMaturity.growing,
                "note_revision": concept.note_revision + 1,
            }
        )
        self.concepts[concept_id] = updated
        return ConceptTurnResponse(
            answer=f"Draft answer for: {request.question}",
            answerSource=AnswerSourceDTO(
                sourceType=AnswerSourceType.model_knowledge,
                confidence=0.5,
                uncertaintyNote="Mock backend response; no external sources cited.",
            ),
            updateMode=UpdateMode.none,
            concept=updated,
            proposal=None,
        )

    def merge_proposal(self, proposal_id: UUID) -> ConceptDTO:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Update proposal not found.",
            )
        return self.get_concept(proposal.id)

    def dismiss_proposal(self, proposal_id: UUID) -> None:
        proposal = self.proposals.get(proposal_id)
        if proposal is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Update proposal not found.",
            )
        self.proposals[proposal_id] = proposal.model_copy(
            update={"status": ProposalStatus.dismissed}
        )


store = InMemoryConceptStore()


@router.post("/concepts", response_model=ConceptDTO, response_model_by_alias=True)
async def create_concept(request: CreateConceptRequest) -> ConceptDTO:
    return store.create_concept(request)


@router.post(
    "/concepts/{concept_id}/turns",
    response_model=ConceptTurnResponse,
    response_model_by_alias=True,
)
async def submit_concept_turn(
    concept_id: UUID,
    request: ConceptTurnRequest,
) -> ConceptTurnResponse:
    return store.submit_turn(concept_id, request)


@router.post(
    "/update-proposals/{proposal_id}/merge",
    response_model=ConceptDTO,
    response_model_by_alias=True,
)
async def merge_update_proposal(proposal_id: UUID) -> ConceptDTO:
    return store.merge_proposal(proposal_id)


@router.post("/update-proposals/{proposal_id}/dismiss", status_code=status.HTTP_204_NO_CONTENT)
async def dismiss_update_proposal(proposal_id: UUID) -> None:
    store.dismiss_proposal(proposal_id)
