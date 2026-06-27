import json
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException

from sift_backend.ai.context_pack import RecentTurn
from sift_backend.api.concepts import build_concept_service
from sift_backend.auth.principal import CurrentPrincipal
from sift_backend.concepts.service import (
    ConceptService,
    InMemoryConceptStore,
    MockConceptModelService,
    SiftRuntimeConceptModelService,
)
from sift_backend.config import Settings
from sift_backend.runtime.concept_runtime import LightweightHermesRuntime
from sift_backend.runtime.tools import DisabledWebSearchTool
from sift_backend.runtime.types import (
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelRequest,
    RuntimeModelResponse,
    SiftRuntimeError,
)
from sift_backend.schemas.common import (
    AnswerSourceType,
    CandidateUpdateOperation,
    EvidenceStatus,
    LearningStateField,
    LearningStateOrigin,
    NoteBlockSource,
    NoteBlockType,
    UpdateMode,
)
from sift_backend.schemas.concepts import (
    ConceptDTO,
    ConceptTurnRequest,
    CreateConceptRequest,
    NoteBlockDTO,
    UpdateConceptSummaryRequest,
)
from sift_backend.schemas.model_outputs import ConceptTurnResult, ModelMeta, ModelUpdateProposal
from sift_backend.schemas.patches import AddRelationPatchOperation, AppendPatchOperation


class FailingModelService(MockConceptModelService):
    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ):
        raise SiftRuntimeError("invalid_schema", "Bad structured output.")


class InitialConceptModelService(MockConceptModelService):
    async def create_initial_concept(
        self,
        title: str,
        locale: str,
    ) -> ConceptDTO:
        return ConceptDTO(
            id="00000000-0000-0000-0000-000000000123",
            canonicalTitle="Retrieval-Augmented Generation",
            displayTitle="RAG",
            oneLineExplanation="RAG grounds answers in retrieved context.",
            maturity="initial",
            captureStatus="ready",
            noteRevision=1,
            blocks=[
                NoteBlockDTO(
                    id="00000000-0000-0000-0000-000000000124",
                    blockType=NoteBlockType.what_it_is,
                    content="RAG retrieves context before generation.",
                    source=NoteBlockSource.ai,
                    isUserLocked=False,
                )
            ],
            tags=["AI", "Retrieval"],
            topics=["Machine Learning"],
            answerSource={
                "sourceType": AnswerSourceType.model_knowledge,
                "confidence": 0.82,
            },
        )


class RelationProposalModelService(MockConceptModelService):
    def __init__(self, target_concept_id: UUID) -> None:
        self.target_concept_id = target_concept_id

    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ) -> ConceptTurnResult:
        return ConceptTurnResult(
            answer="This should be linked to the related concept.",
            answerSource={
                "sourceType": AnswerSourceType.model_knowledge,
                "confidence": 0.8,
            },
            updateDecision={
                "mode": UpdateMode.needs_confirmation,
                "reason": "A durable relation should be confirmed.",
            },
            proposal=ModelUpdateProposal(
                baseNoteRevision=concept.note_revision,
                patchOperations=[
                    AddRelationPatchOperation(
                        operation="addRelation",
                        targetConceptId=self.target_concept_id,
                        relationType="related",
                    )
                ],
                rationale="Connects related concepts.",
            ),
            modelMeta=ModelMeta(provider="test", model="relation-test"),
        )


class CandidateUpdateModelService(MockConceptModelService):
    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ) -> ConceptTurnResult:
        return ConceptTurnResult(
            answer="MCP is often compared with function calling.",
            answerSource={
                "sourceType": AnswerSourceType.model_knowledge,
                "confidence": 0.8,
            },
            updateDecision={
                "mode": UpdateMode.none,
                "reason": "Candidate policy decides durable changes.",
            },
            candidateUpdates=[
                {
                    "operation": CandidateUpdateOperation.add_open_question,
                    "content": "How is MCP different from function calling?",
                    "evidenceStatus": EvidenceStatus.model_explanation,
                },
                {
                    "operation": CandidateUpdateOperation.add_claim,
                    "content": "MCP is a protocol for connecting AI apps to tools and data.",
                    "claimType": "definition",
                    "evidenceStatus": EvidenceStatus.model_explanation,
                    "timeSensitivity": "stable",
                },
            ],
            learningStateUpdates=[
                {
                    "field": LearningStateField.open_questions,
                    "content": "How is MCP different from function calling?",
                    "origin": LearningStateOrigin.assistant_inference,
                }
            ],
            modelMeta=ModelMeta(provider="test", model="candidate-test"),
        )


class CandidateAndAutoPatchModelService(MockConceptModelService):
    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ) -> ConceptTurnResult:
        return ConceptTurnResult(
            answer="The distinction is now clearer.",
            answerSource={
                "sourceType": AnswerSourceType.model_knowledge,
                "confidence": 0.8,
            },
            updateDecision={
                "mode": UpdateMode.auto_merge,
                "reason": "Append a small clarification.",
            },
            autoPatch=[
                AppendPatchOperation(
                    operation="append",
                    targetBlockId=concept.blocks[0].id,
                    content=" It grounds answers in retrieved context.",
                )
            ],
            candidateUpdates=[
                {
                    "operation": CandidateUpdateOperation.add_claim,
                    "content": "RAG combines retrieval with generation.",
                    "claimType": "definition",
                    "evidenceStatus": EvidenceStatus.model_explanation,
                    "timeSensitivity": "stable",
                }
            ],
            modelMeta=ModelMeta(provider="test", model="candidate-auto-test"),
        )


class ClaimProvenanceModelService(MockConceptModelService):
    async def answer_turn(
        self,
        concept: ConceptDTO,
        request: ConceptTurnRequest,
        recent_turns: list[RecentTurn] | None = None,
        card_memory: str = "",
    ) -> ConceptTurnResult:
        return ConceptTurnResult(
            answer="A2A has a source-backed claim and a model-only claim.",
            answerSource={
                "sourceType": AnswerSourceType.source_read,
                "confidence": 0.8,
                "retrievalUsed": True,
                "citations": [
                    {
                        "sourceId": "src_001",
                        "title": "A2A Protocol",
                        "url": "https://example.com/a2a",
                    },
                    {
                        "sourceId": "src_002",
                        "title": "Other Source",
                        "url": "https://example.com/other",
                    },
                ],
            },
            updateDecision={
                "mode": UpdateMode.none,
                "reason": "Candidate policy handles claims.",
            },
            candidateUpdates=[
                {
                    "operation": CandidateUpdateOperation.add_claim,
                    "content": "A2A is designed for agent-to-agent communication.",
                    "claimType": "definition",
                    "evidenceStatus": EvidenceStatus.source_backed,
                    "timeSensitivity": "stable",
                    "sourceIds": ["src_001"],
                },
                {
                    "operation": CandidateUpdateOperation.add_claim,
                    "content": "This missing-source claim should be dropped.",
                    "claimType": "fact",
                    "evidenceStatus": EvidenceStatus.source_backed,
                    "timeSensitivity": "stable",
                    "sourceIds": [],
                },
                {
                    "operation": CandidateUpdateOperation.add_claim,
                    "content": "A2A is often discussed alongside MCP.",
                    "claimType": "distinction",
                    "evidenceStatus": EvidenceStatus.model_explanation,
                    "timeSensitivity": "stable",
                    "sourceIds": ["src_002"],
                },
            ],
            modelMeta=ModelMeta(provider="test", model="claim-provenance-test"),
        )


class RecordingRuntimeProvider:
    provider_name = "test-runtime"

    def __init__(self, responses: list[RuntimeModelResponse]) -> None:
        self.responses = responses
        self.requests: list[RuntimeModelRequest] = []

    async def complete(
        self,
        request: RuntimeModelRequest,
    ) -> RuntimeModelResponse:
        self.requests.append(request)
        return self.responses.pop(0)

    async def stream(self, request: RuntimeModelRequest):
        response = await self.complete(request)
        yield RuntimeModelDelta(response.content)
        yield RuntimeModelCompleted(response)

    async def list_models(self) -> list[str]:
        return ["test-model"]


def valid_model_content(answer: str) -> str:
    return json.dumps(
        {
            "answer": answer,
            "answerSource": {
                "sourceType": AnswerSourceType.model_knowledge,
                "confidence": 0.8,
            },
            "updateDecision": {
                "mode": UpdateMode.none,
                "reason": "No durable note change needed.",
            },
            "relations": [],
            "suggestedTags": [],
            "suggestedTopics": [],
            "memoryPatch": {
                "confirmedUnderstanding": [],
                "openQuestions": [],
                "userPreferences": [],
            },
            "modelMeta": {"provider": "test", "model": "test-model"},
        }
    )


def test_build_concept_service_uses_mock_when_runtime_key_is_missing() -> None:
    service = build_concept_service(
        Settings(runtime_api_key=""),
        store=InMemoryConceptStore(),
    )

    assert isinstance(service.model_service, MockConceptModelService)


def test_build_concept_service_uses_runtime_when_key_is_present() -> None:
    service = build_concept_service(
        Settings(
            runtime_api_key="test-key",
            runtime_base_url="https://runtime.test/v1",
            runtime_model="sift-explain-test",
            runtime_web_search_enabled=True,
            web_search_api_key="tavily-key",
        ),
        store=InMemoryConceptStore(),
    )

    assert isinstance(service.model_service, SiftRuntimeConceptModelService)
    assert service.model_service.runtime.model == "sift-explain-test"
    assert service.model_service.runtime.web_search_enabled is True


@pytest.mark.asyncio
async def test_create_concept_async_uses_model_generated_card() -> None:
    service = ConceptService(model_service=InitialConceptModelService())

    concept = await service.create_concept_async(CreateConceptRequest(rawCapture="RAG"))

    assert concept.display_title == "RAG"
    assert concept.one_line_explanation == "RAG grounds answers in retrieved context."
    assert concept.blocks[0].content == "RAG retrieves context before generation."
    assert concept.tags == ["AI", "Retrieval"]
    assert concept.topics == ["Machine Learning"]
    assert concept.answer_source is not None
    assert concept.answer_source.confidence == 0.82
    assert service.get_concept(concept.id).display_title == "RAG"


def test_owner_boundary_hides_other_users_concepts() -> None:
    store = InMemoryConceptStore()
    owner_a = ConceptService(
        store=store,
        principal=CurrentPrincipal(user_id="owner-a", auth_method="test"),
    )
    owner_b = ConceptService(
        store=store,
        principal=CurrentPrincipal(user_id="owner-b", auth_method="test"),
    )

    concept = owner_a.create_concept(CreateConceptRequest(rawCapture="RAG"))

    assert [item.id for item in owner_a.list_concepts()] == [concept.id]
    assert owner_b.list_concepts() == []
    with pytest.raises(HTTPException) as error:
        owner_b.get_concept(concept.id)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException) as update_error:
        owner_b.update_concept_summary(
            concept.id,
            UpdateConceptSummaryRequest(
                displayTitle="Stolen",
                oneLineExplanation="Should not update.",
            ),
        )
    assert update_error.value.status_code == 404


@pytest.mark.asyncio
async def test_submit_turn_maps_runtime_error_to_bad_gateway() -> None:
    service = ConceptService(model_service=FailingModelService())
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    with pytest.raises(HTTPException) as error:
        await service.submit_turn(
            concept.id,
            ConceptTurnRequest(question="Explain it again."),
        )

    assert error.value.status_code == 502
    assert error.value.detail["code"] == "invalid_schema"
    assert service.get_concept(concept.id).note_revision == concept.note_revision
    assert [turn.content for turn in service.store.list_turns(concept.id)] == [
        "RAG",
        "RAG captured as a draft concept.",
    ]


@pytest.mark.asyncio
async def test_initial_structured_output_failure_does_not_write_concept() -> None:
    store = InMemoryConceptStore()
    provider = RecordingRuntimeProvider(
        responses=[
            RuntimeModelResponse(
                content="not json",
                provider="test",
                model="test-model",
            )
        ]
    )
    runtime = LightweightHermesRuntime(
        model_provider=provider,
        model="test-model",
        web_search_tool=DisabledWebSearchTool(),
        web_search_enabled=False,
    )
    service = ConceptService(
        store=store,
        model_service=SiftRuntimeConceptModelService(runtime),
    )

    with pytest.raises(HTTPException) as error:
        await service.create_concept_async(CreateConceptRequest(rawCapture="RAG"))

    assert error.value.status_code == 502
    assert error.value.detail["code"] == "invalid_json"
    assert store.list_concepts() == []


@pytest.mark.asyncio
async def test_turn_structured_output_failure_does_not_mutate_knowledge() -> None:
    provider = RecordingRuntimeProvider(
        responses=[
            RuntimeModelResponse(
                content="not json",
                provider="test",
                model="test-model",
            )
        ]
    )
    runtime = LightweightHermesRuntime(
        model_provider=provider,
        model="test-model",
        web_search_tool=DisabledWebSearchTool(),
        web_search_enabled=False,
    )
    service = ConceptService(model_service=SiftRuntimeConceptModelService(runtime))
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    with pytest.raises(HTTPException) as error:
        await service.submit_turn(
            concept.id,
            ConceptTurnRequest(question="Explain the stable definition."),
        )

    assert error.value.status_code == 502
    assert error.value.detail["code"] == "invalid_json"
    persisted = service.get_concept(concept.id)
    assert persisted.note_revision == concept.note_revision
    assert persisted.blocks == concept.blocks
    assert persisted.claims == []
    assert persisted.sources == []
    assert persisted.learning_state is None
    assert [turn.content for turn in service.store.list_turns(concept.id)] == [
        "RAG",
        "RAG captured as a draft concept.",
    ]


@pytest.mark.asyncio
async def test_submit_turn_applies_candidate_updates_to_knowledge_layers() -> None:
    service = ConceptService(model_service=CandidateUpdateModelService())
    concept = service.create_concept(CreateConceptRequest(rawCapture="MCP"))

    response = await service.submit_turn(
        concept.id,
        ConceptTurnRequest(question="Compare it with function calling."),
    )
    updated = service.get_concept(concept.id)

    assert response.proposal is None
    assert response.update_mode == UpdateMode.none
    assert "How is MCP different from function calling?" in updated.blocks[-1].content
    assert updated.claims[0].statement == (
        "MCP is a protocol for connecting AI apps to tools and data."
    )
    assert updated.learning_state is not None
    assert updated.learning_state.open_questions[0].origin == "assistantInference"


@pytest.mark.asyncio
async def test_submit_turn_keeps_candidate_claim_when_auto_patch_also_saves() -> None:
    service = ConceptService(model_service=CandidateAndAutoPatchModelService())
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    await service.submit_turn(
        concept.id,
        ConceptTurnRequest(question="Clarify the definition."),
    )
    updated = service.get_concept(concept.id)

    assert "retrieved context" in updated.blocks[0].content
    assert updated.claims[0].statement == "RAG combines retrieval with generation."


@pytest.mark.asyncio
async def test_submit_turn_maps_candidate_claim_source_ids_to_persisted_sources() -> None:
    service = ConceptService(model_service=ClaimProvenanceModelService())
    concept = service.create_concept(CreateConceptRequest(rawCapture="A2A"))

    await service.submit_turn(
        concept.id,
        ConceptTurnRequest(question="Verify source for A2A."),
    )
    updated = service.get_concept(concept.id)

    assert [source.url for source in updated.sources] == [
        "https://example.com/a2a",
        "https://example.com/other",
    ]
    assert [claim.statement for claim in updated.claims] == [
        "A2A is designed for agent-to-agent communication.",
        "A2A is often discussed alongside MCP.",
    ]
    assert updated.claims[0].source_ids == [updated.sources[0].id]
    assert updated.claims[1].source_ids == []


@pytest.mark.asyncio
async def test_submit_turn_reuses_recent_turns_for_same_concept_card() -> None:
    provider = RecordingRuntimeProvider(
        responses=[
            RuntimeModelResponse(
                content=valid_model_content("First answer."),
                provider="test",
                model="test-model",
                input_tokens=None,
                output_tokens=None,
            ),
            RuntimeModelResponse(
                content=valid_model_content("Second answer."),
                provider="test",
                model="test-model",
                input_tokens=None,
                output_tokens=None,
            ),
        ]
    )
    runtime = LightweightHermesRuntime(
        model_provider=provider,
        model="sift-explain-test",
        web_search_tool=DisabledWebSearchTool(),
        web_search_enabled=False,
    )
    service = ConceptService(
        model_service=SiftRuntimeConceptModelService(runtime)
    )
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    await service.submit_turn(concept.id, ConceptTurnRequest(question="What is RAG?"))
    await service.submit_turn(concept.id, ConceptTurnRequest(question="Give me an example."))

    second_request_contents = [message.content for message in provider.requests[1].messages]
    assert "What is RAG?" in second_request_contents
    assert "First answer." in second_request_contents
    assert second_request_contents[-1] == "Give me an example."


@pytest.mark.asyncio
async def test_merge_relation_proposal_persists_concept_relation() -> None:
    target_id = uuid4()
    model_service = RelationProposalModelService(target_id)
    service = ConceptService(model_service=model_service)
    source = service.create_concept(CreateConceptRequest(rawCapture="RAG"))
    target = service.create_concept(CreateConceptRequest(rawCapture="Embedding"))
    model_service.target_concept_id = target.id

    response = await service.submit_turn(
        source.id,
        ConceptTurnRequest(question="Is this related to embeddings?"),
    )

    assert response.proposal is not None
    merged = service.merge_proposal(response.proposal.id)

    assert merged.note_revision == 2
    assert len(merged.relations) == 1
    relation = merged.relations[0]
    assert relation.source_concept_id == source.id
    assert relation.target_concept_id == target.id
    assert relation.relation_type == "related"

    target_with_relation = service.get_concept(target.id)
    assert target_with_relation.relations[0].id == relation.id


@pytest.mark.asyncio
async def test_merge_relation_proposal_rejects_missing_target_concept() -> None:
    missing_target_id = uuid4()
    service = ConceptService(model_service=RelationProposalModelService(missing_target_id))
    source = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    response = await service.submit_turn(
        source.id,
        ConceptTurnRequest(question="Is this related to another concept?"),
    )

    assert response.proposal is not None
    with pytest.raises(HTTPException) as error:
        service.merge_proposal(response.proposal.id)

    assert error.value.status_code == 409
    assert error.value.detail["code"] == "missingConcept"
    assert service.store.get_proposal(response.proposal.id).status == "stale"
    assert service.get_concept(source.id).relations == []
