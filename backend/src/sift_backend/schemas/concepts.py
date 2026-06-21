from uuid import UUID

from pydantic import Field

from sift_backend.schemas.base import SiftBaseModel
from sift_backend.schemas.common import (
    AnswerSourceType,
    CaptureStatus,
    ConceptMaturity,
    NoteBlockSource,
    NoteBlockType,
    ProposalStatus,
    UpdateMode,
)
from sift_backend.schemas.patches import PatchOperation


class NoteBlockDTO(SiftBaseModel):
    id: UUID
    block_type: NoteBlockType = Field(alias="blockType")
    content: str
    source: NoteBlockSource
    is_user_locked: bool = Field(default=False, alias="isUserLocked")


class ConceptDTO(SiftBaseModel):
    id: UUID
    canonical_title: str = Field(alias="canonicalTitle")
    display_title: str = Field(alias="displayTitle")
    one_line_explanation: str = Field(default="", alias="oneLineExplanation")
    maturity: ConceptMaturity = ConceptMaturity.initial
    capture_status: CaptureStatus = Field(
        default=CaptureStatus.draft,
        alias="captureStatus",
    )
    note_revision: int = Field(default=0, ge=0, alias="noteRevision")
    blocks: list[NoteBlockDTO] = Field(default_factory=list)


class CreateConceptRequest(SiftBaseModel):
    raw_capture: str = Field(min_length=1, alias="rawCapture")
    locale: str = "en"


class ConceptTurnRequest(SiftBaseModel):
    question: str = Field(min_length=1)


class AnswerSourceDTO(SiftBaseModel):
    source_type: AnswerSourceType = Field(
        default=AnswerSourceType.model_knowledge,
        alias="sourceType",
    )
    confidence: float = Field(ge=0, le=1)
    uncertainty_note: str | None = Field(default=None, alias="uncertaintyNote")


class UpdateDecisionDTO(SiftBaseModel):
    mode: UpdateMode
    reason: str


class UpdateProposalDTO(SiftBaseModel):
    id: UUID
    base_note_revision: int = Field(ge=0, alias="baseNoteRevision")
    patch_operations: list[PatchOperation] = Field(alias="patchOperations")
    rationale: str
    confidence: float = Field(ge=0, le=1)
    status: ProposalStatus = ProposalStatus.proposed


class ConceptTurnResponse(SiftBaseModel):
    answer: str
    answer_source: AnswerSourceDTO = Field(alias="answerSource")
    update_mode: UpdateMode = Field(alias="updateMode")
    concept: ConceptDTO
    proposal: UpdateProposalDTO | None = None

