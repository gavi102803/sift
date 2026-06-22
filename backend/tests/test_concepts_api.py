from fastapi.testclient import TestClient

from sift_backend.main import create_app


def test_create_concept_returns_ready_card() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"})

    assert response.status_code == 200
    body = response.json()
    assert body["displayTitle"] == "RAG"
    assert body["captureStatus"] == "ready"
    assert body["noteRevision"] == 1
    assert len(body["blocks"]) == 2


def test_create_concept_rejects_empty_capture() -> None:
    client = TestClient(create_app())

    response = client.post("/v1/concepts", json={"raw_capture": "", "locale": "en"})

    assert response.status_code == 422


def test_list_concepts_returns_created_cards() -> None:
    client = TestClient(create_app())
    client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"})
    client.post("/v1/concepts", json={"raw_capture": "Embedding", "locale": "en"})

    response = client.get("/v1/concepts")

    assert response.status_code == 200
    titles = [concept["displayTitle"] for concept in response.json()]
    assert titles == ["RAG", "Embedding"]


def test_get_concept_returns_card_by_id() -> None:
    client = TestClient(create_app())
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()

    response = client.get(f"/v1/concepts/{concept['id']}")

    assert response.status_code == 200
    assert response.json()["id"] == concept["id"]
    assert response.json()["displayTitle"] == "RAG"


def test_get_concept_returns_404_for_missing_card() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/concepts/00000000-0000-0000-0000-000000000001")

    assert response.status_code == 404


def test_submit_turn_returns_answer_and_updated_concept() -> None:
    client = TestClient(create_app())
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


def test_list_concept_turns_returns_persisted_question_and_answer() -> None:
    client = TestClient(create_app())
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
        },
    ]


def test_list_concept_turns_returns_404_for_missing_concept() -> None:
    client = TestClient(create_app())

    response = client.get("/v1/concepts/00000000-0000-0000-0000-000000000001/turns")

    assert response.status_code == 404


def test_submit_turn_returns_404_for_missing_concept() -> None:
    client = TestClient(create_app())

    response = client.post(
        "/v1/concepts/00000000-0000-0000-0000-000000000001/turns",
        json={"question": "What is this?"},
    )

    assert response.status_code == 404


def test_submit_turn_can_create_update_proposal() -> None:
    client = TestClient(create_app())
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
    client = TestClient(create_app())
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
    client = TestClient(create_app())
    concept = client.post("/v1/concepts", json={"raw_capture": "RAG", "locale": "en"}).json()
    turn = client.post(
        f"/v1/concepts/{concept['id']}/turns",
        json={"question": "Define this more precisely"},
    ).json()

    response = client.post(f"/v1/update-proposals/{turn['proposal']['id']}/dismiss")

    assert response.status_code == 204
