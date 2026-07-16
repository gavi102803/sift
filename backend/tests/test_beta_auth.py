from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from sift_backend.config import Settings
from sift_backend.main import create_app
from sift_backend.runtime.providers import MockRuntimeModelProvider
from sift_backend.schemas.common import ProposalStatus
from sift_backend.schemas.concepts import UpdateProposalDTO


def _app(tmp_path, *invite_codes: str):
    return create_app(
        Settings(
            env="test",
            auth_mode="managed",
            database_url=f"sqlite:///{tmp_path / 'beta.db'}",
            runtime_provider="mock",
            beta_invite_codes=tuple(invite_codes),
        )
    )


def _activate(client: TestClient, code: str, installation: str) -> dict:
    response = client.post(
        "/v1/beta/activate",
        json={"inviteCode": code, "installationId": installation},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _headers(session: dict, installation: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {session['betaAccessToken']}",
        "X-Sift-Installation": installation,
    }


def _runtime_headers(session: dict, installation: str) -> dict[str, str]:
    return _headers(session, installation) | {"X-Sift-Provider-Key": "test-provider-key"}


def _connect(client: TestClient, session: dict, installation: str) -> None:
    response = client.put(
        "/v1/provider-connection",
        headers=_headers(session, installation),
        json={"providerId": "openai", "model": "gpt-5.5"},
    )
    assert response.status_code == 200, response.text


def test_managed_mode_requires_activation(tmp_path) -> None:
    client = TestClient(_app(tmp_path, "invite-one"))

    response = client.get("/v1/concepts")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "authentication_required"
    assert response.json()["error"]["requestId"]
    assert response.headers["X-Request-ID"]


def test_activation_reuse_and_installation_binding(tmp_path) -> None:
    client = TestClient(_app(tmp_path, "invite-one"))

    first = _activate(client, "invite-one", "install-a")
    second = _activate(client, "invite-one", "install-a")
    conflict = client.post(
        "/v1/beta/activate",
        json={"inviteCode": "invite-one", "installationId": "install-b"},
    )

    assert first["ownerId"] == second["ownerId"]
    assert first["betaAccessToken"] != second["betaAccessToken"]
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "invite_consumed"


def test_refresh_rotates_token_and_rejects_old_token(tmp_path) -> None:
    client = TestClient(_app(tmp_path, "invite-one"))
    session = _activate(client, "invite-one", "install-a")

    refreshed = client.post(
        "/v1/beta/session/refresh",
        headers=_headers(session, "install-a"),
    )
    old_access = client.get("/v1/concepts", headers=_headers(session, "install-a"))

    assert refreshed.status_code == 200
    replacement = refreshed.json()
    assert replacement["ownerId"] == session["ownerId"]
    assert replacement["betaAccessToken"] != session["betaAccessToken"]
    assert old_access.status_code == 401
    assert old_access.json()["error"]["code"] == "beta_token_revoked"
    assert client.get(
        "/v1/concepts",
        headers=_headers(replacement, "install-a"),
    ).status_code == 200


def test_owner_scope_is_derived_from_token(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sift_backend.api.concepts.build_runtime_model_provider",
        lambda *args, **kwargs: MockRuntimeModelProvider(),
    )
    client = TestClient(_app(tmp_path, "invite-a", "invite-b"))
    owner_a = _activate(client, "invite-a", "install-a")
    owner_b = _activate(client, "invite-b", "install-b")
    _connect(client, owner_a, "install-a")
    _connect(client, owner_b, "install-b")

    created = client.post(
        "/v1/concepts",
        headers=_runtime_headers(owner_a, "install-a"),
        json={"rawCapture": "Owner A concept", "locale": "en"},
    )
    owner_b_list = client.get(
        "/v1/concepts",
        headers=_headers(owner_b, "install-b"),
    )
    cross_owner = client.get(
        f"/v1/concepts/{created.json()['id']}",
        headers=_headers(owner_b, "install-b"),
    )

    assert created.status_code == 200
    assert owner_b_list.json() == []
    assert cross_owner.status_code == 404


def test_cross_owner_cannot_dismiss_proposal(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "sift_backend.api.concepts.build_runtime_model_provider",
        lambda *args, **kwargs: MockRuntimeModelProvider(),
    )
    app = _app(tmp_path, "invite-a", "invite-b")
    client = TestClient(app)
    owner_a = _activate(client, "invite-a", "install-a")
    owner_b = _activate(client, "invite-b", "install-b")
    _connect(client, owner_a, "install-a")
    concept = client.post(
        "/v1/concepts",
        headers=_runtime_headers(owner_a, "install-a"),
        json={"rawCapture": "Owner A concept", "locale": "en"},
    ).json()
    proposal = UpdateProposalDTO(
        id=uuid4(),
        baseNoteRevision=concept["noteRevision"],
        patchOperations=[],
        rationale="Owner A only",
        confidence=0.9,
        status=ProposalStatus.proposed,
    )
    app.state.concept_service.store.save_proposal(proposal, concept_id=concept["id"])

    response = client.post(
        f"/v1/update-proposals/{proposal.id}/dismiss",
        headers=_headers(owner_b, "install-b"),
    )
    merge_response = client.post(
        f"/v1/update-proposals/{proposal.id}/merge",
        headers=_headers(owner_b, "install-b"),
    )

    assert response.status_code == 404
    assert merge_response.status_code == 404
    stored = app.state.concept_service.store.get_proposal(proposal.id)
    assert stored.status == ProposalStatus.proposed


def test_database_stores_only_token_hash(tmp_path) -> None:
    app = _app(tmp_path, "invite-one")
    client = TestClient(app)
    session = _activate(client, "invite-one", "install-a")

    engine = create_engine(app.state.settings.database_url)
    with engine.connect() as connection:
        stored = connection.execute(text("select token_hash from beta_sessions")).scalar_one()

    assert stored != session["betaAccessToken"]
    assert len(stored) == 64


def test_owner_revocation_is_a_kill_switch(tmp_path) -> None:
    app = _app(tmp_path, "invite-one")
    client = TestClient(app)
    session = _activate(client, "invite-one", "install-a")

    app.state.beta_auth_service.revoke_owner(session["ownerId"])
    response = client.get("/v1/concepts", headers=_headers(session, "install-a"))

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "beta_token_revoked"
