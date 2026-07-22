from uuid import UUID

from pydantic import Field

from sift_backend.schemas.base import SiftBaseModel
from sift_backend.schemas.common import (
    AnswerSourceType,
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
from sift_backend.schemas.patches import PatchOperation


class NoteBlockDTO(SiftBaseModel):
    id: UUID
    block_type: NoteBlockType = Field(alias="blockType")
    content: str
    source: NoteBlockSource
    is_user_locked: bool = Field(default=False, alias="isUserLocked")
    revision: int = Field(default=1, ge=1)
    supported_claim_ids: list[UUID] = Field(default_factory=list, alias="supportedClaimIds")
    position: int | None = None


class ConceptRelationDTO(SiftBaseModel):
    id: UUID
    source_concept_id: UUID = Field(alias="sourceConceptId")
    target_concept_id: UUID = Field(alias="targetConceptId")
    relation_type: str = Field(alias="relationType")
    status: str = "accepted"
    confidence: float = Field(default=1, ge=0, le=1)
    source: str = "user"


class ConceptDTO(SiftBaseModel):
    id: UUID
    canonical_title: str = Field(alias="canonicalTitle")
    display_title: str = Field(alias="displayTitle")
    one_line_explanation: str = Field(default="", alias="oneLineExplanation")
    initial_answer: str | None = Field(default=None, alias="initialAnswer")
    maturity: ConceptMaturity = ConceptMaturity.initial
    capture_status: CaptureStatus = Field(
        default=CaptureStatus.draft,
        alias="captureStatus",
    )
    note_revision: int = Field(default=0, ge=0, alias="noteRevision")
    blocks: list[NoteBlockDTO] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    answer_source: "AnswerSourceDTO | None" = Field(default=None, alias="answerSource")
    relations: list[ConceptRelationDTO] = Field(default_factory=list)
    sources: list["SourceDTO"] = Field(default_factory=list)
    claims: list["ClaimDTO"] = Field(default_factory=list)
    learning_state: "LearningStateDTO | None" = Field(default=None, alias="learningState")
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")


class BatchConceptRequest(SiftBaseModel):
    concept_ids: list[UUID] = Field(min_length=1, alias="conceptIds")


class CreateConceptRequest(SiftBaseModel):
    raw_capture: str = Field(min_length=1, alias="rawCapture")
    locale: str = "en"


class UpdateConceptSummaryRequest(SiftBaseModel):
    display_title: str = Field(min_length=1, alias="displayTitle")
    one_line_explanation: str = Field(default="", alias="oneLineExplanation")


class UpdateNoteBlockRequest(SiftBaseModel):
    content: str = Field(min_length=1)


class UpdateConceptOrganizationRequest(SiftBaseModel):
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class UpdateConceptNoteBlockRequest(SiftBaseModel):
    id: UUID | None = None
    block_type: NoteBlockType = Field(alias="blockType")
    content: str = Field(min_length=1)


class UpdateConceptNoteRequest(SiftBaseModel):
    display_title: str = Field(min_length=1, alias="displayTitle")
    one_line_explanation: str = Field(default="", alias="oneLineExplanation")
    blocks: list[UpdateConceptNoteBlockRequest] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class CreateConceptRelationRequest(SiftBaseModel):
    target_concept_id: UUID = Field(alias="targetConceptId")
    relation_type: str = Field(default="related", min_length=1, alias="relationType")


class ConceptTurnRequest(SiftBaseModel):
    question: str = Field(min_length=1)
    replacing_turn_index: int | None = Field(
        default=None,
        ge=0,
        alias="replacingTurnIndex",
    )


class ConceptHistoryTurnDTO(SiftBaseModel):
    role: str
    content: str
    answer_source: "AnswerSourceDTO | None" = Field(default=None, alias="answerSource")


class CitationDTO(SiftBaseModel):
    title: str
    url: str
    source_id: str | None = Field(default=None, alias="sourceId")


class SourceDTO(SiftBaseModel):
    id: UUID
    concept_id: UUID = Field(alias="conceptId")
    title: str
    url: str | None = None
    source_type: SourceType = Field(default=SourceType.secondary, alias="sourceType")
    retrieved_at: str | None = Field(default=None, alias="retrievedAt")
    published_at: str | None = Field(default=None, alias="publishedAt")
    content_hash: str | None = Field(default=None, alias="contentHash")


class ClaimDTO(SiftBaseModel):
    id: UUID
    concept_id: UUID = Field(alias="conceptId")
    statement: str
    type: ClaimType
    evidence_status: EvidenceStatus = Field(alias="evidenceStatus")
    time_sensitivity: TimeSensitivity = Field(
        default=TimeSensitivity.stable,
        alias="timeSensitivity",
    )
    source_ids: list[UUID] = Field(default_factory=list, alias="sourceIds")
    verified_at: str | None = Field(default=None, alias="verifiedAt")
    superseded_by_claim_id: UUID | None = Field(default=None, alias="supersededByClaimId")


class LearningStateEntryDTO(SiftBaseModel):
    content: str
    origin: LearningStateOrigin
    created_at: str | None = Field(default=None, alias="createdAt")


class LearningStateDTO(SiftBaseModel):
    concept_id: UUID = Field(alias="conceptId")
    user_context: list[LearningStateEntryDTO] = Field(default_factory=list, alias="userContext")
    confirmed_understanding: list[LearningStateEntryDTO] = Field(
        default_factory=list,
        alias="confirmedUnderstanding",
    )
    open_questions: list[LearningStateEntryDTO] = Field(default_factory=list, alias="openQuestions")
    recurring_confusions: list[LearningStateEntryDTO] = Field(
        default_factory=list,
        alias="recurringConfusions",
    )


class LearningStateUpdateDTO(SiftBaseModel):
    field: LearningStateField
    content: str
    origin: LearningStateOrigin


class AnswerSourceDTO(SiftBaseModel):
    source_type: AnswerSourceType = Field(
        default=AnswerSourceType.model_knowledge,
        alias="sourceType",
    )
    confidence: float = Field(ge=0, le=1)
    uncertainty_note: str | None = Field(default=None, alias="uncertaintyNote")
    retrieval_used: bool = Field(default=False, alias="retrievalUsed")
    freshness_note: str | None = Field(default=None, alias="freshnessNote")
    citations: list[CitationDTO] = Field(default_factory=list)


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
    origin: str = "followUp"
    source_run_id: UUID | None = Field(default=None, alias="sourceRunId")


class NoteRevisionSummaryDTO(SiftBaseModel):
    revision: int
    source: str
    created_at: str = Field(alias="createdAt")
    is_current: bool = Field(default=False, alias="isCurrent")
    restored_from_revision: int | None = Field(default=None, alias="restoredFromRevision")


class NoteRevisionDTO(NoteRevisionSummaryDTO):
    snapshot_schema_version: int = Field(alias="snapshotSchemaVersion")
    display_title: str = Field(alias="displayTitle")
    canonical_title: str = Field(alias="canonicalTitle")
    one_line_explanation: str = Field(alias="oneLineExplanation")
    blocks: list[NoteBlockDTO] = Field(default_factory=list)


class ConceptTurnResponse(SiftBaseModel):
    answer: str
    answer_source: AnswerSourceDTO = Field(alias="answerSource")
    update_mode: UpdateMode = Field(alias="updateMode")
    concept: ConceptDTO
    proposal: UpdateProposalDTO | None = None
