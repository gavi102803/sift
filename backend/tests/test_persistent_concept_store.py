from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from sift_backend.concepts.service import ConceptService
from sift_backend.persistence.concept_store import PersistentConceptStore
from sift_backend.persistence.database import initialize_database
from sift_backend.persistence.models import NoteRevisionRecord, UpdateEventRecord
from sift_backend.schemas.common import (
    ClaimType,
    EvidenceStatus,
    LearningStateField,
    LearningStateOrigin,
    SourceType,
    TimeSensitivity,
)
from sift_backend.schemas.concepts import (
    ClaimDTO,
    ConceptTurnRequest,
    CreateConceptRelationRequest,
    CreateConceptRequest,
    LearningStateUpdateDTO,
    SourceDTO,
    UpdateConceptNoteRequest,
    UpdateConceptOrganizationRequest,
)


def test_persistent_store_survives_new_store_instance(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    service = ConceptService(store=PersistentConceptStore(session_factory))

    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    second_store = PersistentConceptStore(session_factory)
    persisted = second_store.get_concept(concept.id)

    assert persisted.display_title == "RAG"
    assert persisted.blocks[0].content == "RAG is ready for a first explanation."
    assert persisted.answer_source is not None
    assert persisted.answer_source.source_type == "modelKnowledge"


def test_persistent_store_round_trips_tags_and_topics(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    service = ConceptService(store=PersistentConceptStore(session_factory))
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    service.update_concept_organization(
        concept.id,
        UpdateConceptOrganizationRequest(
            tags=["AI", "Retrieval", "ai"],
            topics=["Machine Learning", "Knowledge"],
        ),
    )

    second_store = PersistentConceptStore(session_factory)
    persisted = second_store.get_concept(concept.id)

    assert persisted.tags == ["AI", "Retrieval"]
    assert persisted.topics == ["Machine Learning", "Knowledge"]


def test_persistent_store_round_trips_knowledge_layers(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    store = PersistentConceptStore(session_factory)
    service = ConceptService(store=store)
    concept = service.create_concept(CreateConceptRequest(rawCapture="MCP"))
    source_id = uuid4()
    claim_id = uuid4()

    store.add_sources(
        concept.id,
        [
            SourceDTO(
                id=source_id,
                conceptId=concept.id,
                title="MCP specification",
                url="https://example.com/mcp",
                sourceType=SourceType.official,
            )
        ],
    )
    store.add_claims(
        concept.id,
        [
            ClaimDTO(
                id=claim_id,
                conceptId=concept.id,
                statement="MCP connects AI apps to tools and data sources.",
                type=ClaimType.definition,
                evidenceStatus=EvidenceStatus.source_backed,
                timeSensitivity=TimeSensitivity.stable,
                sourceIds=[source_id],
            )
        ],
    )
    store.add_learning_state_updates(
        concept.id,
        [
            LearningStateUpdateDTO(
                field=LearningStateField.open_questions,
                content="How does MCP differ from function calling?",
                origin=LearningStateOrigin.user_explicit,
            )
        ],
    )

    persisted = PersistentConceptStore(session_factory).get_concept(concept.id)

    assert persisted.sources[0].id == source_id
    assert persisted.claims[0].source_ids == [source_id]
    assert persisted.learning_state is not None
    assert persisted.learning_state.open_questions[0].content == (
        "How does MCP differ from function calling?"
    )


def test_persistent_store_records_initial_and_manual_note_audit(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    service = ConceptService(store=PersistentConceptStore(session_factory))

    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))
    service.update_concept_organization(
        concept.id,
        UpdateConceptOrganizationRequest(tags=["AI"], topics=["Machine Learning"]),
    )

    with session_factory() as session:
        revisions = session.query(NoteRevisionRecord).order_by(NoteRevisionRecord.revision).all()
        events = session.query(UpdateEventRecord).order_by(UpdateEventRecord.created_at).all()

    assert [revision.revision for revision in revisions] == [1, 2]
    assert revisions[0].merge_mode == "initialGeneration"
    assert revisions[1].merge_mode == "manualEdit"
    assert '"displayTitle": "RAG"' in revisions[0].snapshot_json
    assert [event.event_type for event in events] == ["initialGeneration", "manualEdit"]
    assert [event.actor for event in events] == ["ai", "user"]


def test_persistent_store_round_trips_concept_relations(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    service = ConceptService(store=PersistentConceptStore(session_factory))
    source = service.create_concept(CreateConceptRequest(rawCapture="RAG"))
    target = service.create_concept(CreateConceptRequest(rawCapture="Embedding"))

    related = service.add_relation(
        source.id,
        CreateConceptRelationRequest(targetConceptId=target.id, relationType="related"),
    )

    assert len(related.relations) == 1
    relation = related.relations[0]
    assert relation.source_concept_id == source.id
    assert relation.target_concept_id == target.id

    second_store = PersistentConceptStore(session_factory)
    target_with_relation = second_store.get_concept(target.id)

    assert target_with_relation.relations[0].id == relation.id

    service.remove_relation(source.id, relation.id)

    assert second_store.get_concept(source.id).relations == []


@pytest.mark.asyncio
async def test_persistent_store_round_trips_turns_without_auto_note_updates(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    service = ConceptService(store=PersistentConceptStore(session_factory))
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    response = await service.submit_turn(
        concept.id,
        ConceptTurnRequest(question="Define this more precisely"),
    )

    assert response.update_mode == "none"
    assert response.proposal is None
    assert response.concept.note_revision == 1

    second_service = ConceptService(store=PersistentConceptStore(session_factory))
    turns = second_service.list_turns(concept.id)
    persisted = second_service.get_concept(concept.id)

    assert [turn.content for turn in turns] == [
        "RAG",
        "RAG captured as a draft concept.",
        "Define this more precisely",
        "Draft answer for: Define this more precisely",
    ]
    assert turns[1].answer_source.source_type == "modelKnowledge"
    assert turns[3].answer_source.source_type == "modelKnowledge"
    assert persisted.note_revision == 1
    assert persisted.blocks[0].content == concept.blocks[0].content


@pytest.mark.asyncio
async def test_persistent_store_replaces_edited_turn_branch(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    service = ConceptService(store=PersistentConceptStore(session_factory))
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))
    await service.submit_turn(concept.id, ConceptTurnRequest(question="Old follow-up"))
    await service.submit_turn(concept.id, ConceptTurnRequest(question="Discard this branch"))

    await service.submit_turn(
        concept.id,
        ConceptTurnRequest(question="Edited follow-up", replacingTurnIndex=2),
    )

    turns = ConceptService(store=PersistentConceptStore(session_factory)).list_turns(concept.id)
    assert [turn.content for turn in turns] == [
        "RAG",
        "RAG captured as a draft concept.",
        "Edited follow-up",
        "Draft answer for: Edited follow-up",
    ]


@pytest.mark.asyncio
async def test_persistent_store_rebuilds_card_when_initial_query_is_edited(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    service = ConceptService(store=PersistentConceptStore(session_factory))
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))

    await service.submit_turn(
        concept.id,
        ConceptTurnRequest(question="Agent runtime", replacingTurnIndex=0),
    )

    reloaded_service = ConceptService(store=PersistentConceptStore(session_factory))
    rebuilt = reloaded_service.get_concept(concept.id)
    turns = reloaded_service.list_turns(concept.id)
    assert rebuilt.display_title == "Agent runtime"
    assert rebuilt.note_revision == concept.note_revision + 1
    assert rebuilt.blocks
    assert all(block.id not in {old.id for old in concept.blocks} for block in rebuilt.blocks)
    assert [turn.content for turn in turns] == [
        "Agent runtime",
        "Agent runtime captured as a draft concept.",
    ]


@pytest.mark.asyncio
async def test_persistent_store_records_full_note_manual_edit_audit(tmp_path) -> None:
    database_path = tmp_path / "sift.db"
    session_factory = _session_factory(f"sqlite:///{database_path}")
    service = ConceptService(store=PersistentConceptStore(session_factory))
    concept = service.create_concept(CreateConceptRequest(rawCapture="RAG"))
    service.update_concept_note(
        concept.id,
        UpdateConceptNoteRequest(
            displayTitle=concept.display_title,
            oneLineExplanation=concept.one_line_explanation,
            blocks=[
                {
                    "id": block.id,
                    "blockType": block.block_type,
                    "content": block.content,
                }
                for block in concept.blocks
            ]
            + [
                {
                    "blockType": "userTakeaways",
                    "content": "Keep useful answers only after review.",
                }
            ],
            tags=concept.tags,
            topics=concept.topics,
        ),
    )

    with session_factory() as session:
        revisions = session.query(NoteRevisionRecord).order_by(NoteRevisionRecord.revision).all()
        events = session.query(UpdateEventRecord).order_by(UpdateEventRecord.created_at).all()

    assert [revision.revision for revision in revisions] == [1, 2]
    assert revisions[-1].merge_mode == "manualEdit"
    assert events[-1].event_type == "manualEdit"
    assert events[-1].actor == "user"
    assert events[-1].proposal_id is None


def _session_factory(database_url: str) -> sessionmaker:
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    initialize_database(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
