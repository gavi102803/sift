import json

from fastapi.testclient import TestClient

from sift_backend.concepts.service import ConceptService, MockConceptModelService
from sift_backend.config import Settings
from sift_backend.main import create_app
from sift_backend.runtime.types import SiftRuntimeError
from sift_backend.schemas.concepts import ConceptDTO


def make_client(concept_service: ConceptService | None = None) -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=concept_service or ConceptService(),
        )
    )


class FailsFirstInitialModelService(MockConceptModelService):
    def __init__(self) -> None:
        self.calls = 0

    async def create_initial_concept(
        self,
        title: str,
        locale: str,
    ) -> ConceptDTO:
        self.calls += 1
        if self.calls == 1:
            raise SiftRuntimeError("generation_failed", "First attempt failed.")
        return await super().create_initial_concept(title=title, locale=locale)


def test_create_concept_returns_ready_card() -> None:
    client = make_client()

    response = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"})

    assert response.status_code == 200
    body = response.json()
    assert body["displayTitle"] == "RAG"
    assert body["captureStatus"] == "ready"
    assert body["noteRevision"] == 1
    assert body["answerSource"]["sourceType"] == "modelKnowledge"
    assert len(body["blocks"]) == 2


def test_create_concept_rejects_empty_capture() -> None:
    client = make_client()

    response = client.post("/v1/concepts", json={"raw_capture": "", "locale": "en"})

    assert response.status_code == 422


def test_list_concepts_returns_created_cards() -> None:
    client = make_client()
    client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"})
    client.post("/v1/concepts", json={"raw_capture": "Embedding", "locale": "en"})

    response = client.get("/v1/concepts")

    assert response.status_code == 200
    titles = [concept["displayTitle"] for concept in response.json()]
    assert titles == ["RAG", "Embedding"]


def test_get_concept_returns_card_by_id() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()

    response = client.get(f"/v1/concepts/{concept['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == concept["id"]
    assert response.json()["displayTitle"] == "RAG"


def test_get_concept_returns_404_for_missing_card() -> None:
    client = make_client()

    response = client.get("/v1/concepts/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 404


def test_update_concept_summary_persists_manual_edit() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()

    response = client.patch(
        f"/v1/concepts/{concept['id']}",
        json={
            "displayTitle": "Retrieval-Augmented Generation",
            "oneLineExplanation": "Grounds answers in retrieved context.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["displayTitle"] == "Retrieval-Augmented Generation"
    assert body["canonicalTitle"] == "Retrieval-Augmented Generation"
    assert body["oneLineExplanation"] == "Grounds answers in retrieved context."
    assert body["noteRevision"] == 2


def test_update_note_block_locks_user_content() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    block = concept["blocks"][0]

    response = client.patch(
        f"/v1/concepts/{concept['id']}/blocks/{block['id']}",
        json={"content": "RAG combines retrieval with generation at answer time."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["noteRevision"] == 2
    assert body["maturity"] == "growing"
    assert body["blocks"][0]["content"] == "RAG combines retrieval with generation at answer time."
    assert body["blocks"][0]["source"] == "user"
    assert body["blocks"][0]["isUserLocked"] is True


def test_update_note_block_returns_404_for_missing_block() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()

    response = client.patch(
        f"/v1/concepts/{concept['id']}/blocks/00000000-0000-0000-0000-000000000001",
        json={"content": "Updated content"},
    )

    assert response.status_code == 404


def test_update_concept_note_replaces_ordered_blocks_and_preserves_unchanged_source() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    first_block, second_block = concept["blocks"]

    response = client.put(
        f"/v1/concepts/{concept['id']}/note",
        json={
            "displayTitle": "Retrieval-Augmented Generation",
            "oneLineExplanation": "Grounds answers in retrieved context.",
            "blocks": [
                {
                    "id": second_block["id"],
                    "blockType": second_block["blockType"],
                    "content": second_block["content"],
                },
                {
                    "blockType": "userTakeaways",
                    "content": "Use RAG when answers need retrieved context.",
                },
            ],
            "tags": ["AI", "ai", "Retrieval"],
            "topics": ["Knowledge"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["displayTitle"] == "Retrieval-Augmented Generation"
    assert body["oneLineExplanation"] == "Grounds answers in retrieved context."
    assert body["noteRevision"] == 2
    assert [block["position"] for block in body["blocks"]] == [0, 1]
    assert [block["id"] for block in body["blocks"]] == [
        second_block["id"],
        body["blocks"][1]["id"],
    ]
    assert body["blocks"][0]["source"] == second_block["source"]
    assert body["blocks"][0]["isUserLocked"] == second_block["isUserLocked"]
    assert body["blocks"][1]["source"] == "user"
    assert body["blocks"][1]["isUserLocked"] is True
    assert first_block["id"] not in [block["id"] for block in body["blocks"]]
    assert body["tags"] == ["AI", "Retrieval"]
    assert body["topics"] == ["Knowledge"]


def test_update_concept_organization_persists_tags_and_topics() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()

    response = client.patch(
        f"/v1/concepts/{concept['id']}/organization",
        json={
            "tags": ["AI", "Retrieval", "ai", ""],
            "topics": ["Machine Learning", "Knowledge"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["tags"] == ["AI", "Retrieval"]
    assert body["topics"] == ["Machine Learning", "Knowledge"]
    assert body["noteRevision"] == 2

    persisted = client.get(f"/v1/concepts/{concept['id']}").json()
    assert persisted["tags"] == ["AI", "Retrieval"]
    assert persisted["topics"] == ["Machine Learning", "Knowledge"]


def test_add_and_remove_concept_relation() -> None:
    client = make_client()
    source = client.post("/v1/concepts", json={"rawCapture": "RAG", "locale": "en"}).json()
    target = client.post("/v1/concepts", json={"rawCapture": "Embedding", "locale": "en"}).json()

    response = client.post(
        f"/v1/concepts/{source['id']}/relations",
        json={"targetConceptId": target["id"], "relationType": "related"},
    )

    assert response.status_code == 200
    body = response.json()
    assert len(body["relations"]) == 1
    relation = body["relations"][0]
    assert relation["sourceConceptId"] == source["id"]
    assert relation["targetConceptId"] == target["id"]
    assert relation["relationType"] == "related"
    assert relation["status"] == "accepted"

    persisted = client.get(f"/v1/concepts/{target['id']}").json()
    assert persisted["relations"][0]["id"] == relation["id"]

    removed = client.delete(f"/v1/concepts/{source['id']}/relations/{relation['id']}")

    assert removed.status_code == 200
    assert removed.json()["relations"] == []


def test_add_concept_relation_rejects_self_relation() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"rawCapture": "RAG", "locale": "en"}).json()

    response = client.post(
        f"/v1/concepts/{concept['id']}/relations",
        json={"targetConceptId": concept["id"], "relationType": "related"},
    )

    assert response.status_code == 422


def test_submit_turn_returns_answer_and_updated_concept() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "Embedding", "locale": "en"}).json()

    response = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "How is it different from a token?"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Draft answer for: How is it different from a token?"
    assert body["answerSource"]["sourceType"] == "modelKnowledge"
    assert body["updateMode"] == "none"
    assert body["proposal"] is None
    assert body["concept"]["noteRevision"] == 1
    assert "Follow-up captured" not in body["concept"]["blocks"][0]["content"]


def test_submit_turn_stream_returns_deltas_and_completed_response() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "Embedding", "locale": "en"}).json()

    with client.stream(
        "POST",
        f"/v1/concepts/{concept['id']}/turns/stream",
        json={"question": "How is it different from a token?"},
    ) as response:
        assert response.status_code == 200
        events = [json.loads(line) for line in response.iter_lines() if line]

    assert events[0] == {"type": "started"}
    assert "".join(event["delta"] for event in events if event["type"] == "delta") == (
        "Draft answer for: How is it different from a token?"
    )
    completed = events[-1]
    assert completed["type"] == "completed"
    assert completed["response"]["answer"] == "Draft answer for: How is it different from a token?"
    assert completed["response"]["concept"]["noteRevision"] == 1


def test_create_concept_stream_returns_deltas_completed_and_reuses_key() -> None:
    client = make_client()
    headers = {"Idempotency-Key": "capture-stream-rag-1"}
    payload = {"raw_capture": "RAG", "locale": "en"}

    def run_stream() -> list[dict]:
        with client.stream(
            "POST",
            "/v1/concepts/stream",
            json=payload,
            headers=headers,
        ) as response:
            assert response.status_code == 200
            return [json.loads(line) for line in response.iter_lines() if line]

    first = run_stream()
    second = run_stream()

    assert first[0] == {"type": "started"}
    assert "".join(event["delta"] for event in first if event["type"] == "delta")
    assert first[-1]["type"] == "completed"
    assert second[-1]["type"] == "completed"
    assert second[-1]["concept"]["id"] == first[-1]["concept"]["id"]
    assert len(client.get("/v1/concepts").json()) == 1


def test_list_concept_turns_returns_persisted_question_and_answer() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "How is it different from fine-tuning?"},
    )

    response = client.get(f"/v1/concepts/{concept['id']}/turns")

    assert response.status_code == 200
    assert response.json() == [
        {"role": "user", "content": "RAG"},
        {
            "role": "assistant",
            "content": "RAG captured as a draft concept.",
            "answerSource": {
                "sourceType": "modelKnowledge",
                "confidence": 0.5,
                "uncertaintyNote": "Mock backend response; no external sources cited.",
                "retrievalUsed": False,
                "citations": [],
            },
        },
        {"role": "user", "content": "How is it different from fine-tuning?"},
        {
            "role": "assistant",
            "content": "Draft answer for: How is it different from fine-tuning?",
            "answerSource": {
                "sourceType": "modelKnowledge",
                "confidence": 0.5,
                "uncertaintyNote": "Mock backend response; no external sources cited.",
                "retrievalUsed": False,
                "citations": [],
            },
        },
    ]


def test_list_concept_turns_returns_404_for_missing_concept() -> None:
    client = make_client()

    response = client.get("/v1/concepts/00000000-0000-0000-0000-000000000001/turns")

    assert response.status_code == 404


def test_create_concept_idempotency_key_does_not_create_duplicate_card() -> None:
    client = make_client()
    headers = {"Idempotency-Key": "capture-rag-1"}

    first = client.post(
        "/v1/concepts",
        json={"raw_capture": "RAG", "locale": "en"},
        headers=headers,
    )
    second = client.post(
        "/v1/concepts",
        json={"raw_capture": "RAG", "locale": "en"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["id"] == first.json()["id"]
    assert len(client.get("/v1/concepts").json()) == 1
    turns = client.get(f"/v1/concepts/{first.json()['id']}/turns").json()
    assert [turn["role"] for turn in turns] == ["user", "assistant"]


def test_create_concept_same_key_different_payload_returns_conflict() -> None:
    client = make_client()
    headers = {"Idempotency-Key": "capture-conflict-1"}

    first = client.post(
        "/v1/concepts",
        json={"raw_capture": "RAG", "locale": "en"},
        headers=headers,
    )
    second = client.post(
        "/v1/concepts",
        json={"raw_capture": "Agent runtime", "locale": "en"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "idempotency_payload_conflict"
    assert len(client.get("/v1/concepts").json()) == 1


def test_create_concept_terminal_failure_new_retry_key_can_create_new_attempt() -> None:
    service = ConceptService(model_service=FailsFirstInitialModelService())
    client = make_client(service)
    payload = {"raw_capture": "A2A protocol", "locale": "en"}

    failed = client.post(
        "/v1/concepts",
        json=payload,
        headers={"Idempotency-Key": "capture-failed-1"},
    )
    retried_same_key = client.post(
        "/v1/concepts",
        json=payload,
        headers={"Idempotency-Key": "capture-failed-1"},
    )
    retried_new_key = client.post(
        "/v1/concepts",
        json=payload,
        headers={"Idempotency-Key": "capture-failed-2"},
    )

    assert failed.status_code == 502
    assert retried_same_key.status_code == 502
    assert retried_new_key.status_code == 200
    assert retried_new_key.json()["displayTitle"] == "A2A protocol"
    assert len(client.get("/v1/concepts").json()) == 1


def test_turn_idempotency_key_does_not_duplicate_turn_or_patch() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    headers = {"Idempotency-Key": "turn-1"}

    first = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "How does it work?"},
        headers=headers,
    )
    second = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "How does it work?"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["concept"]["noteRevision"] == first.json()["concept"]["noteRevision"]
    persisted = client.get(f"/v1/concepts/{concept['id']}").json()
    assert persisted["noteRevision"] == 1
    turns = client.get(f"/v1/concepts/{concept['id']}/turns").json()
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]


def test_turn_idempotency_key_conflicts_on_different_payload() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    headers = {"Idempotency-Key": "turn-conflict-1"}

    first = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "How does it work?"},
        headers=headers,
    )
    second = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "When should I use it?"},
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"]["code"] == "idempotency_payload_conflict"
    turns = client.get(f"/v1/concepts/{concept['id']}/turns").json()
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]


def test_stream_turn_idempotency_key_returns_terminal_result_without_duplicate_turn() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    headers = {"Idempotency-Key": "stream-turn-1"}

    def run_stream() -> list[dict]:
        with client.stream(
            "POST",
            f"/v1/concepts/{concept['id']}/turns/stream",
            json={"question": "How does it work?"},
            headers=headers,
        ) as response:
            assert response.status_code == 200
            return [json.loads(line) for line in response.iter_lines() if line]

    first = run_stream()
    second = run_stream()

    assert first[-1]["type"] == "completed"
    assert second == [
        {"type": "started"},
        {"type": "completed", "response": first[-1]["response"]},
    ]
    turns = client.get(f"/v1/concepts/{concept['id']}/turns").json()
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]


def test_turn_and_stream_share_logical_idempotency_scope() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    headers = {"Idempotency-Key": "turn-shared-scope-1"}
    payload = {"question": "How does it work?"}

    first = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json=payload,
        headers=headers,
    )
    with client.stream(
        "POST",
        f"/v1/concepts/{concept['id']}/turns/stream",
        json=payload,
        headers=headers,
    ) as response:
        second = [json.loads(line) for line in response.iter_lines() if line]

    assert first.status_code == 200
    assert response.status_code == 200
    assert second == [
        {"type": "started"},
        {"type": "completed", "response": first.json()},
    ]
    turns = client.get(f"/v1/concepts/{concept['id']}/turns").json()
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user", "assistant"]


def test_define_turn_does_not_create_update_proposal() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    response = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "define it more precisely"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["updateMode"] == "none"
    assert body["proposal"] is None
    assert client.get(f"/v1/concepts/{concept['id']}").json()["noteRevision"] == 1


def test_submit_turn_returns_404_for_missing_concept() -> None:
    client = make_client()

    response = client.post(
        "/v1/concepts/00000000-0000-0000-0000-000000000001/turns",
        json={"question": "What is this?"},
    )

    assert response.status_code == 404


def test_submit_turn_ignores_model_patch_candidates_for_manual_note_saving() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()

    response = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "Define this more precisely"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["updateMode"] == "none"
    assert body["proposal"] is None
    assert body["concept"]["noteRevision"] == 1


def test_update_note_endpoint_adds_answer_as_user_takeaway() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    answer = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "Define this more precisely"},
    ).json()["answer"]

    response = client.put(
        f"/v1/concepts/{concept['id']}/note",
        json={
            "displayTitle": concept["displayTitle"],
            "oneLineExplanation": concept["oneLineExplanation"],
            "blocks": [
                {
                    "id": block["id"],
                    "blockType": block["blockType"],
                    "content": block["content"],
                }
                for block in concept["blocks"]
            ]
            + [{"blockType": "userTakeaways", "content": answer}],
            "tags": concept["tags"],
            "topics": concept["topics"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["noteRevision"] == 2
    assert body["blocks"][-1]["blockType"] == "userTakeaways"
    assert body["blocks"][-1]["content"] == answer
    assert body["blocks"][-1]["source"] == "user"


def test_dismiss_update_proposal_returns_404_for_missing_proposal() -> None:
    client = make_client()

    response = client.post("/v1/update-proposals/00000000-0000-0000-0000-000000000001/dismiss")

    assert response.status_code == 404
