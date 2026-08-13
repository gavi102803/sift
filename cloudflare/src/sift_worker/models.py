from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_AGENT_INPUT_CHARS = 20_000
MAX_LOCALE_CHARS = 64


class SiftWorkerModel(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class HealthResponse(SiftWorkerModel):
    status: str
    env: str
    runtime: str


class AppStatusResponse(SiftWorkerModel):
    env: str
    model_provider: str = Field(alias="modelProvider")
    explain_model: str = Field(alias="explainModel")
    web_search_enabled: bool = Field(alias="webSearchEnabled")
    database_url: str = Field(alias="databaseURL")
    provider_base_url: str | None = Field(default=None, alias="providerBaseURL")
    api_key_configured: bool = Field(default=False, alias="apiKeyConfigured")
    api_key_preview: str | None = Field(default=None, alias="apiKeyPreview")


class RuntimeProviderOptionResponse(SiftWorkerModel):
    id: str
    name: str
    description: str
    adapter: str
    protocol_driver: str = Field(alias="protocolDriver")
    exposure_tier: str = Field(default="standard", alias="exposureTier")
    default_base_url: str = Field(alias="defaultBaseURL")
    default_model: str = Field(alias="defaultModel")
    requires_api_key: bool = Field(default=True, alias="requiresApiKey")
    supports_model_listing: bool = Field(default=False, alias="supportsModelListing")
    status: str = "available"
    is_advanced: bool = Field(default=False, alias="isAdvanced")


class RuntimeProviderCatalogResponse(SiftWorkerModel):
    providers: list[RuntimeProviderOptionResponse]


class WebProviderOptionResponse(SiftWorkerModel):
    id: str
    name: str
    description: str
    requires_api_key: bool = Field(alias="requiresApiKey")
    supports_search: bool = Field(alias="supportsSearch")
    supports_extract: bool = Field(alias="supportsExtract")
    status: str
    is_default: bool = Field(alias="isDefault")


class WebProviderCatalogResponse(SiftWorkerModel):
    providers: list[WebProviderOptionResponse]


class WebProviderSettingsResponse(SiftWorkerModel):
    provider_type: str = Field(alias="providerType")
    api_key_configured: bool = Field(default=False, alias="apiKeyConfigured")
    api_key_preview: str | None = Field(default=None, alias="apiKeyPreview")
    web_search_enabled: bool = Field(alias="webSearchEnabled")


class UpdateWebProviderSettingsRequest(SiftWorkerModel):
    provider_type: str = Field(alias="providerType")
    api_key: str | None = Field(default=None, alias="apiKey")
    web_search_enabled: bool = Field(alias="webSearchEnabled")


class ModelDiagnosticResponse(SiftWorkerModel):
    ok: bool
    provider: str
    model: str
    message: str
    web_search_used: bool | None = Field(default=None, alias="webSearchUsed")
    citation_count: int | None = Field(default=None, alias="citationCount")


class ActivateBetaRequest(SiftWorkerModel):
    invite_code: str = Field(alias="inviteCode")
    installation_id: str = Field(alias="installationId")


class BetaSessionResponse(SiftWorkerModel):
    beta_access_token: str = Field(alias="betaAccessToken")
    owner_id: str = Field(alias="ownerId")
    expires_at: str = Field(alias="expiresAt")


class CreateConceptRequest(SiftWorkerModel):
    raw_capture: str = Field(
        min_length=1,
        max_length=MAX_AGENT_INPUT_CHARS,
        alias="rawCapture",
    )
    locale: str = Field(default="en", min_length=1, max_length=MAX_LOCALE_CHARS)

    @field_validator("raw_capture")
    @classmethod
    def reject_blank_capture(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("rawCapture must not be blank")
        return value


class CreateConceptRunRequest(SiftWorkerModel):
    capture: CreateConceptRequest
    client_draft_id: str | None = Field(default=None, alias="clientDraftId")


class ConceptTurnRequest(SiftWorkerModel):
    question: str = Field(min_length=1, max_length=MAX_AGENT_INPUT_CHARS)
    replacing_turn_index: int | None = Field(
        default=None,
        ge=0,
        alias="replacingTurnIndex",
    )

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class CreateTurnRunRequest(SiftWorkerModel):
    turn: ConceptTurnRequest


class BatchConceptRequest(SiftWorkerModel):
    concept_ids: list[str] = Field(min_length=1, alias="conceptIds")


class CreateConceptRelationRequest(SiftWorkerModel):
    target_concept_id: str = Field(alias="targetConceptId")
    relation_type: str = Field(default="related", min_length=1, alias="relationType")


class UpdateConceptSummaryRequest(SiftWorkerModel):
    display_title: str = Field(min_length=1, alias="displayTitle")
    one_line_explanation: str = Field(default="", alias="oneLineExplanation")


class UpdateNoteBlockRequest(SiftWorkerModel):
    content: str = Field(min_length=1)


class UpdateConceptOrganizationRequest(SiftWorkerModel):
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class UpdateConceptNoteBlockRequest(SiftWorkerModel):
    id: str | None = None
    block_type: Literal[
        "whatItIs",
        "whyItMatters",
        "example",
        "commonMisunderstandings",
        "relatedConceptsDisplay",
        "userTakeaways",
    ] = Field(alias="blockType")
    content: str = Field(min_length=1)


class UpdateConceptNoteRequest(SiftWorkerModel):
    display_title: str = Field(min_length=1, alias="displayTitle")
    one_line_explanation: str = Field(default="", alias="oneLineExplanation")
    blocks: list[UpdateConceptNoteBlockRequest] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)


class ProviderConnectionRequest(SiftWorkerModel):
    provider_id: str = Field(alias="providerId")
    base_url: str | None = Field(default=None, alias="baseURL")
    model: str


class ProviderConnectionResponse(SiftWorkerModel):
    provider_id: str = Field(alias="providerId")
    base_url: str = Field(alias="baseURL")
    model: str


class ProviderTestResponse(SiftWorkerModel):
    ok: bool


class ProviderModelResponse(SiftWorkerModel):
    id: str
    owned_by: str = Field(alias="ownedBy")


class ProviderModelListResponse(SiftWorkerModel):
    models: list[ProviderModelResponse]


class InitialNoteBlockOutput(SiftWorkerModel):
    block_type: Literal[
        "whatItIs",
        "whyItMatters",
        "example",
        "commonMisunderstandings",
        "relatedConceptsDisplay",
        "userTakeaways",
    ] = Field(alias="blockType")
    content: str = Field(min_length=1)


class SuggestionOutput(SiftWorkerModel):
    name: str = Field(min_length=1)
    confidence: float = Field(ge=0, le=1)


class CitationOutput(SiftWorkerModel):
    source_id: str | None = Field(default=None, alias="sourceId")
    title: str
    url: str


class AnswerSourceOutput(SiftWorkerModel):
    source_type: Literal[
        "modelKnowledge",
        "userProvided",
        "searchDiscovered",
        "sourceRead",
        "sourceVerified",
        "webVerified",
    ] = Field(alias="sourceType")
    confidence: float = Field(ge=0, le=1)
    uncertainty_note: str | None = Field(default=None, alias="uncertaintyNote")
    retrieval_used: bool = Field(default=False, alias="retrievalUsed")
    freshness_note: str | None = Field(default=None, alias="freshnessNote")
    citations: list[CitationOutput] = Field(default_factory=list)


class ModelMetaOutput(SiftWorkerModel):
    provider: str
    model: str
    latency_ms: int | None = Field(default=None, ge=0, alias="latencyMs")
    input_tokens: int | None = Field(default=None, ge=0, alias="inputTokens")
    output_tokens: int | None = Field(default=None, ge=0, alias="outputTokens")


class AppendPatchOutput(SiftWorkerModel):
    operation: Literal["append"]
    target_block_id: str = Field(alias="targetBlockId")
    content: str = Field(min_length=1)


class ReplacePatchOutput(SiftWorkerModel):
    operation: Literal["replace"]
    target_block_id: str = Field(alias="targetBlockId")
    old_value_hash: str = Field(min_length=1, alias="oldValueHash")
    new_content: str = Field(min_length=1, alias="newContent")


class AddRelationPatchOutput(SiftWorkerModel):
    operation: Literal["addRelation"]
    target_concept_id: str = Field(alias="targetConceptId")
    relation_type: str = Field(min_length=1, alias="relationType")


PatchOperationOutput = Annotated[
    AppendPatchOutput | ReplacePatchOutput | AddRelationPatchOutput,
    Field(discriminator="operation"),
]


class ModelUpdateProposalOutput(SiftWorkerModel):
    patch_operations: list[PatchOperationOutput] = Field(
        min_length=1,
        alias="patchOperations",
    )
    rationale: str = Field(min_length=1)


class InitialConceptResult(SiftWorkerModel):
    canonical_title: str = Field(min_length=1, alias="canonicalTitle")
    display_title: str = Field(min_length=1, alias="displayTitle")
    one_line_explanation: str = Field(min_length=1, alias="oneLineExplanation")
    answer: str = Field(min_length=1)
    blocks: list[InitialNoteBlockOutput] = Field(min_length=2, max_length=6)
    suggested_tags: list[SuggestionOutput] = Field(default_factory=list, alias="suggestedTags")
    suggested_topics: list[SuggestionOutput] = Field(
        default_factory=list,
        alias="suggestedTopics",
    )
    answer_source: AnswerSourceOutput = Field(alias="answerSource")
    model_meta: ModelMetaOutput = Field(alias="modelMeta")


class FollowUpResult(SiftWorkerModel):
    answer: str = Field(min_length=1)
    answer_source: AnswerSourceOutput = Field(alias="answerSource")
    proposal: ModelUpdateProposalOutput | None = None
    model_meta: ModelMetaOutput = Field(alias="modelMeta")


class ContinuitySummaryResult(SiftWorkerModel):
    summary: str = Field(min_length=1)


class ClaimCandidateOutput(SiftWorkerModel):
    statement: str = Field(min_length=1)
    type: Literal["definition", "distinction", "fact"]
    evidence_status: Literal[
        "modelExplanation",
        "sourceBacked",
        "userNote",
    ] = Field(alias="evidenceStatus")
    time_sensitivity: Literal["stable", "timeSensitive"] = Field(
        default="stable",
        alias="timeSensitivity",
    )
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")


class LearningStateUpdateOutput(SiftWorkerModel):
    field: Literal[
        "userContext",
        "confirmedUnderstanding",
        "openQuestions",
        "recurringConfusions",
    ]
    content: str = Field(min_length=1)
    origin: Literal["userExplicit", "userConfirmed", "assistantInference"]


class KnowledgeReviewResult(SiftWorkerModel):
    proposal: ModelUpdateProposalOutput | None = None
    claims: list[ClaimCandidateOutput] = Field(default_factory=list)
    learning_state_updates: list[LearningStateUpdateOutput] = Field(
        default_factory=list,
        alias="learningStateUpdates",
    )


class NoteBlockResponse(SiftWorkerModel):
    id: str
    block_type: str = Field(alias="blockType")
    content: str
    source: str
    is_user_locked: bool = Field(default=False, alias="isUserLocked")
    revision: int = 1
    supported_claim_ids: list[str] = Field(default_factory=list, alias="supportedClaimIds")
    position: int | None = None


class ConceptResponse(SiftWorkerModel):
    id: str
    canonical_title: str = Field(alias="canonicalTitle")
    display_title: str = Field(alias="displayTitle")
    one_line_explanation: str = Field(default="", alias="oneLineExplanation")
    initial_answer: str | None = Field(default=None, alias="initialAnswer")
    maturity: str = "initial"
    capture_status: str = Field(default="draft", alias="captureStatus")
    note_revision: int = Field(default=0, alias="noteRevision")
    blocks: list[NoteBlockResponse] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    answer_source: AnswerSourceOutput | None = Field(default=None, alias="answerSource")
    relations: list[dict[str, Any]] = Field(default_factory=list)
    sources: list[dict[str, Any]] = Field(default_factory=list)
    claims: list[dict[str, Any]] = Field(default_factory=list)
    learning_state: dict[str, Any] | None = Field(default=None, alias="learningState")
    created_at: str | None = Field(default=None, alias="createdAt")
    updated_at: str | None = Field(default=None, alias="updatedAt")


class ConceptHistoryTurnResponse(SiftWorkerModel):
    role: str
    content: str
    answer_source: AnswerSourceOutput | None = Field(default=None, alias="answerSource")


class ConceptTurnResponse(SiftWorkerModel):
    answer: str
    answer_source: AnswerSourceOutput = Field(alias="answerSource")
    update_mode: str = Field(default="none", alias="updateMode")
    concept: ConceptResponse
    proposal: dict[str, Any] | None = None


class UpdateProposalResponse(SiftWorkerModel):
    id: str
    base_note_revision: int = Field(alias="baseNoteRevision")
    patch_operations: list[PatchOperationOutput] = Field(alias="patchOperations")
    rationale: str
    confidence: float = Field(ge=0, le=1)
    status: str
    origin: str
    source_run_id: str | None = Field(default=None, alias="sourceRunId")


class NoteRevisionSummaryResponse(SiftWorkerModel):
    revision: int
    source: str
    created_at: str = Field(alias="createdAt")
    is_current: bool = Field(default=False, alias="isCurrent")
    restored_from_revision: int | None = Field(default=None, alias="restoredFromRevision")


class NoteRevisionResponse(NoteRevisionSummaryResponse):
    snapshot_schema_version: int = Field(default=1, alias="snapshotSchemaVersion")
    display_title: str = Field(alias="displayTitle")
    canonical_title: str = Field(alias="canonicalTitle")
    one_line_explanation: str = Field(alias="oneLineExplanation")
    blocks: list[NoteBlockResponse] = Field(default_factory=list)


class ModelRunResponse(SiftWorkerModel):
    id: str
    kind: str
    status: str
    concept_id: str | None = Field(default=None, alias="conceptId")
    client_draft_id: str | None = Field(default=None, alias="clientDraftId")
    idempotency_key: str = Field(alias="idempotencyKey")
    provider_snapshot: dict[str, str] = Field(default_factory=dict, alias="providerSnapshot")
    agent_spec: str = Field(alias="agentSpec")
    agent_spec_version: str = Field(alias="agentSpecVersion")
    prompt_version: str = Field(alias="promptVersion")
    tool_contract_hash: str = Field(default="", alias="toolContractHash")
    budget: dict[str, int] = Field(default_factory=dict)
    current_step: str | None = Field(default=None, alias="currentStep")
    model_call_count: int = Field(default=0, alias="modelCallCount")
    tool_call_count: int = Field(default=0, alias="toolCallCount")
    model_latency_ms: int = Field(default=0, alias="modelLatencyMs")
    input_token_count: int = Field(default=0, alias="inputTokenCount")
    output_token_count: int = Field(default=0, alias="outputTokenCount")
    termination_reason: str | None = Field(default=None, alias="terminationReason")
    dependency_run_id: str | None = Field(default=None, alias="dependencyRunId")
    checkpoint: str | None = None
    result: dict[str, Any] | None = None
    result_ref: str | None = Field(default=None, alias="resultRef")
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")
    child_run_ids: list[str] = Field(default_factory=list, alias="childRunIds")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class ModelRunEventResponse(SiftWorkerModel):
    sequence: int
    type: str
    data: dict[str, Any] | None = None
    created_at: str = Field(alias="createdAt")


@dataclass(frozen=True)
class CurrentPrincipal:
    owner_id: str
    installation_id: str


@dataclass(frozen=True)
class IssuedSession:
    token: str
    owner_id: str
    expires_at: str
