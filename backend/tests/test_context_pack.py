from uuid import uuid4

from sift_backend.ai.context_pack import (
    RecentTurn,
    build_concept_turn_context_pack,
    build_initial_concept_context_pack,
    concept_turn_response_format,
    initial_concept_response_format,
)
from sift_backend.schemas.common import (
    CaptureStatus,
    ConceptMaturity,
    NoteBlockSource,
    NoteBlockType,
)
from sift_backend.schemas.concepts import ConceptDTO, NoteBlockDTO


def make_concept() -> ConceptDTO:
    return ConceptDTO(
        id=uuid4(),
        canonicalTitle="RAG",
        displayTitle="RAG",
        oneLineExplanation="Retrieval-augmented generation.",
        maturity=ConceptMaturity.growing,
        captureStatus=CaptureStatus.ready,
        noteRevision=3,
        blocks=[
            NoteBlockDTO(
                id=uuid4(),
                blockType=NoteBlockType.what_it_is,
                content="RAG retrieves external context before generation.",
                source=NoteBlockSource.merged,
                isUserLocked=False,
            ),
            NoteBlockDTO(
                id=uuid4(),
                blockType=NoteBlockType.user_takeaways,
                content="Use product docs as retrieval sources.",
                source=NoteBlockSource.user,
                isUserLocked=True,
            ),
        ],
    )


def test_context_pack_includes_card_memory_note_blocks_and_query() -> None:
    concept = make_concept()

    pack = build_concept_turn_context_pack(
        concept=concept,
        card_memory="User prefers practical product examples.",
        recent_turns=[
            RecentTurn(role="user", content="What is RAG?"),
            RecentTurn(role="assistant", content="It retrieves context first."),
        ],
        user_query="How is RAG different from fine-tuning?",
    )

    assert pack.messages[0].role == "system"
    assert "Never overwrite user-locked note blocks" in pack.messages[0].content
    assert "User prefers practical product examples" in pack.messages[1].content
    assert "RAG retrieves external context" in pack.messages[1].content
    assert "isUserLocked" in pack.messages[1].content
    assert pack.messages[-1].content == "How is RAG different from fine-tuning?"


def test_prompts_follow_current_query_language_and_keep_citations_out_of_note_blocks() -> None:
    initial = build_initial_concept_context_pack("什么是 ACP？", "zh-Hans")
    turn = build_concept_turn_context_pack(
        concept=make_concept(),
        card_memory="English card memory.",
        recent_turns=[],
        user_query="请用中文解释。",
    )

    for prompt in (initial.messages[0].content, turn.messages[0].content):
        assert "language" in prompt
        assert "proper nouns, code, and source titles" in prompt
        assert "Do not put bracketed numeric citation markers" in prompt


def test_context_pack_keeps_only_recent_ten_turns() -> None:
    concept = make_concept()
    turns = [RecentTurn(role="user", content=f"Question {index}") for index in range(12)]

    pack = build_concept_turn_context_pack(
        concept=concept,
        card_memory="Memory",
        recent_turns=turns,
        user_query="Current question",
    )

    contents = [message.content for message in pack.messages]
    assert "Question 0" not in contents
    assert "Question 1" not in contents
    assert "Question 2" in contents
    assert "Question 11" in contents


def test_response_format_contains_strict_patch_contract() -> None:
    response_format = concept_turn_response_format()

    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    schema = response_format["json_schema"]["schema"]
    assert "autoPatch" in schema["properties"]
    patch_schema = schema["properties"]["autoPatch"]["items"]
    operations = {
        option["properties"]["operation"]["const"]
        for option in patch_schema["anyOf"]
    }
    assert operations == {"append", "replace", "addRelation"}


def test_response_formats_make_strict_required_fields_explicit() -> None:
    turn_schema = concept_turn_response_format()["json_schema"]["schema"]
    assert set(turn_schema["required"]) == set(turn_schema["properties"])
    assert set(turn_schema["properties"]["answerSource"]["required"]) == set(
        turn_schema["properties"]["answerSource"]["properties"]
    )
    assert set(turn_schema["properties"]["memoryPatch"]["required"]) == set(
        turn_schema["properties"]["memoryPatch"]["properties"]
    )
    assert set(turn_schema["properties"]["modelMeta"]["required"]) == set(
        turn_schema["properties"]["modelMeta"]["properties"]
    )

    initial_schema = initial_concept_response_format()["json_schema"]["schema"]
    assert set(initial_schema["required"]) == set(initial_schema["properties"])
    assert set(initial_schema["properties"]["answerSource"]["required"]) == set(
        initial_schema["properties"]["answerSource"]["properties"]
    )
    assert set(initial_schema["properties"]["modelMeta"]["required"]) == set(
        initial_schema["properties"]["modelMeta"]["properties"]
    )
