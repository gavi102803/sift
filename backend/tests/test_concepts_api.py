import json

from fastapi.testclient import TestClient

from sift_backend.concepts.service import ConceptService
from sift_backend.config import Settings
from sift_backend.main import create_app


def make_client() -> TestClient:
    return TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )


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
    assert body["updateMode"] == "autoMerge"
    assert body["concept"]["noteRevision"] == 2
    assert "Follow-up captured" in body["concept"]["blocks"][0]["content"]


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
    assert completed["response"]["concept"]["noteRevision"] == 2


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


def test_submit_turn_returns_404_for_missing_concept() -> None:
    client = make_client()

    response = client.post(
        "/v1/concepts/00000000-0000-0000-0000-000000000001/turns",
        json={"question": "What is this?"},
    )

    assert response.status_code == 404


def test_submit_turn_can_create_update_proposal() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()

    response = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "Define this more precisely"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["updateMode"] == "needsConfirmation"
    assert body["proposal"]["status"] == "proposed"
    assert body["proposal"]["baseNoteRevision"] == 1
    assert body["concept"]["noteRevision"] == 1


def test_merge_update_proposal_applies_patch() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    turn = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "Define this more precisely"},
    ).json()

    response = client.post(f"/v1/update-proposals/{turn['proposal']['id']}/merge")

    assert response.status_code == 200
    body = response.json()
    assert body["noteRevision"] == 2
    assert body["blocks"][0]["content"] == "RAG is a concept being refined by Sift."


def test_dismiss_update_proposal_returns_no_content() -> None:
    client = make_client()
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    turn = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "Define this more precisely"},
    ).json()

    response = client.post(f"/v1/update-proposals/{turn['proposal']['id']}/dismiss")

    assert response.status_code == 204
