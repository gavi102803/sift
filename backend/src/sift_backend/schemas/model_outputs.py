from uuid import UUID

from pydantic import Field

from sift_backend.schemas.base import SiftBaseModel
from sift_backend.schemas.common import (
    CandidateUpdateOperation,
    ClaimType,
    EvidenceStatus,
    NoteBlockType,
    TimeSensitivity,
    UpdateMode,
)
from sift_backend.schemas.concepts import AnswerSourceDTO, LearningStateUpdateDTO, UpdateDecisionDTO
from sift_backend.schemas.patches import PatchOperation


class ConceptRelationSuggestion(SiftBaseModel):
    target_concept_id: UUID | None = Field(default=None, alias="targetConceptId")
    title: str
    relation_type: str = Field(alias="relationType")
    confidence: float = Field(ge=0, le=1)


class TagSuggestion(SiftBaseModel):
    name: str
    confidence: float = Field(ge=0, le=1)


class TopicSuggestion(SiftBaseModel):
    name: str
    confidence: float = Field(ge=0, le=1)


class MemoryPatch(SiftBaseModel):
    confirmed_understanding: list[str] = Field(
        default_factory=list,
        alias="confirmedUnderstanding",
    )
    open_questions: list[str] = Field(default_factory=list, alias="openQuestions")
    user_preferences: list[str] = Field(default_factory=list, alias="userPreferences")


class ContinuitySummaryEntry(SiftBaseModel):
    content: str = Field(min_length=1)
    source_turn_ids: list[int] = Field(min_length=1, alias="sourceTurnIds")


class ContinuitySummaryResult(SiftBaseModel):
    prior_answers: list[ContinuitySummaryEntry] = Field(
        default_factory=list,
        alias="priorAnswers",
    )
    confirmed_understanding: list[ContinuitySummaryEntry] = Field(
        default_factory=list,
        alias="confirmedUnderstanding",
    )
    user_context: list[ContinuitySummaryEntry] = Field(
        default_factory=list,
        alias="userContext",
    )
    recurring_confusions: list[ContinuitySummaryEntry] = Field(
        default_factory=list,
        alias="recurringConfusions",
    )
    open_questions: list[ContinuitySummaryEntry] = Field(
        default_factory=list,
        alias="openQuestions",
    )

    @property
    def entries(self) -> list[ContinuitySummaryEntry]:
        return [
            *self.prior_answers,
            *self.confirmed_understanding,
            *self.user_context,
            *self.recurring_confusions,
            *self.open_questions,
        ]


class ModelMeta(SiftBaseModel):
    provider: str
    model: str
    latency_ms: int | None = Field(default=None, ge=0, alias="latencyMs")
    input_tokens: int | None = Field(default=None, ge=0, alias="inputTokens")
    output_tokens: int | None = Field(default=None, ge=0, alias="outputTokens")


class ModelUpdateProposal(SiftBaseModel):
    base_note_revision: int = Field(ge=0, alias="baseNoteRevision")
    patch_operations: list[PatchOperation] = Field(alias="patchOperations")
    rationale: str


class CandidateUpdate(SiftBaseModel):
    operation: CandidateUpdateOperation
    target_block_id: UUID | None = Field(default=None, alias="targetBlockId")
    target_claim_id: UUID | None = Field(default=None, alias="targetClaimId")
    target_concept_id: UUID | None = Field(default=None, alias="targetConceptId")
    relation_type: str | None = Field(default=None, alias="relationType")
    block_type: NoteBlockType | None = Field(default=None, alias="blockType")
    claim_type: ClaimType | None = Field(default=None, alias="claimType")
    content: str | None = None
    evidence_status: EvidenceStatus = Field(
        default=EvidenceStatus.model_explanation,
        alias="evidenceStatus",
    )
    time_sensitivity: TimeSensitivity = Field(
        default=TimeSensitivity.stable,
        alias="timeSensitivity",
    )
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")


class InitialNoteBlockOutput(SiftBaseModel):
    block_type: NoteBlockType = Field(alias="blockType")
    content: str


class ConceptInitialResult(SiftBaseModel):
    canonical_title: str = Field(alias="canonicalTitle")
    display_title: str = Field(alias="displayTitle")
    one_line_explanation: str = Field(alias="oneLineExplanation")
    answer: str
    blocks: list[InitialNoteBlockOutput]
    suggested_tags: list[TagSuggestion] = Field(
        default_factory=list,
        alias="suggestedTags",
    )
    suggested_topics: list[TopicSuggestion] = Field(
        default_factory=list,
        alias="suggestedTopics",
    )
    answer_source: AnswerSourceDTO = Field(alias="answerSource")
    model_meta: ModelMeta = Field(alias="modelMeta")


class ConceptTurnResult(SiftBaseModel):
    answer: str
    answer_source: AnswerSourceDTO = Field(alias="answerSource")
    update_decision: UpdateDecisionDTO = Field(alias="updateDecision")
    auto_patch: list[PatchOperation] = Field(default_factory=list, alias="autoPatch")
    proposal: ModelUpdateProposal | None = None
    candidate_updates: list[CandidateUpdate] = Field(
        default_factory=list,
        alias="candidateUpdates",
    )
    learning_state_updates: list[LearningStateUpdateDTO] = Field(
        default_factory=list,
        alias="learningStateUpdates",
    )
    relations: list[ConceptRelationSuggestion] = Field(default_factory=list)
    suggested_tags: list[TagSuggestion] = Field(
        default_factory=list,
        alias="suggestedTags",
    )
    suggested_topics: list[TopicSuggestion] = Field(
        default_factory=list,
        alias="suggestedTopics",
    )
    memory_patch: MemoryPatch = Field(
        default_factory=MemoryPatch,
        alias="memoryPatch",
    )
    model_meta: ModelMeta = Field(alias="modelMeta")

    @property
    def update_mode(self) -> UpdateMode:
        return self.update_decision.mode
