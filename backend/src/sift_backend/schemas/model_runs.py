from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import Field

from sift_backend.schemas.base import SiftBaseModel
from sift_backend.schemas.concepts import ConceptTurnRequest, CreateConceptRequest


class ModelRunKind(StrEnum):
    initial_concept = "initialConcept"
    follow_up = "followUp"
    continuity_summary = "continuitySummary"
    knowledge_review = "knowledgeReview"


class ModelRunStatus(StrEnum):
    queued = "queued"
    waiting_for_credential = "waitingForCredential"
    running = "running"
    succeeded = "succeeded"
    failed = "failed"


class CreateConceptRunRequest(SiftBaseModel):
    capture: CreateConceptRequest
    client_draft_id: str | None = Field(default=None, alias="clientDraftId")


class CreateTurnRunRequest(SiftBaseModel):
    turn: ConceptTurnRequest


class ModelRunDTO(SiftBaseModel):
    id: UUID
    kind: ModelRunKind
    status: ModelRunStatus
    concept_id: UUID | None = Field(default=None, alias="conceptId")
    client_draft_id: str | None = Field(default=None, alias="clientDraftId")
    idempotency_key: str = Field(alias="idempotencyKey")
    provider_snapshot: dict[str, str] = Field(default_factory=dict, alias="providerSnapshot")
    agent_spec: str = Field(alias="agentSpec")
    agent_spec_version: str = Field(alias="agentSpecVersion")
    prompt_version: str = Field(alias="promptVersion")
    budget: dict[str, int] = Field(default_factory=dict)
    current_step: str | None = Field(default=None, alias="currentStep")
    model_call_count: int = Field(default=0, alias="modelCallCount")
    tool_call_count: int = Field(default=0, alias="toolCallCount")
    termination_reason: str | None = Field(default=None, alias="terminationReason")
    dependency_run_id: UUID | None = Field(default=None, alias="dependencyRunId")
    checkpoint: str | None = None
    result: dict[str, Any] | None = None
    result_ref: str | None = Field(default=None, alias="resultRef")
    error_code: str | None = Field(default=None, alias="errorCode")
    error_message: str | None = Field(default=None, alias="errorMessage")
    child_run_ids: list[UUID] = Field(default_factory=list, alias="childRunIds")
    created_at: str = Field(alias="createdAt")
    updated_at: str = Field(alias="updatedAt")


class ModelRunEventDTO(SiftBaseModel):
    sequence: int
    type: str
    data: dict[str, Any] | None = None
    created_at: str = Field(alias="createdAt")
