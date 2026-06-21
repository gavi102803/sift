from uuid import UUID

from pydantic import Field

from sift_backend.schemas.base import SiftBaseModel
from sift_backend.schemas.common import UpdateMode
from sift_backend.schemas.concepts import AnswerSourceDTO, UpdateDecisionDTO
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


class ConceptTurnResult(SiftBaseModel):
    answer: str
    answer_source: AnswerSourceDTO = Field(alias="answerSource")
    update_decision: UpdateDecisionDTO = Field(alias="updateDecision")
    auto_patch: list[PatchOperation] = Field(default_factory=list, alias="autoPatch")
    proposal: ModelUpdateProposal | None = None
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

