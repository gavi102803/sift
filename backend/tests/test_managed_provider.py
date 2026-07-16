import sqlite3

from fastapi.testclient import TestClient

from sift_backend.config import Settings
from sift_backend.main import create_app
from sift_backend.runtime.providers import MockRuntimeModelProvider
from sift_backend.runtime.types import SiftRuntimeError

PROVIDER_KEY = "secret-provider-key-must-not-persist"


def _app(tmp_path):
    database_path = tmp_path / "managed-provider.db"
    app = create_app(
        Settings(
            env="test",
            auth_mode="managed",
            database_url=f"sqlite:///{database_path}",
            runtime_provider="mock",
            beta_invite_codes=("invite-one",),
        )
    )
    app.state.test_database_path = database_path
    return app


def _session(client: TestClient) -> tuple[dict, dict[str, str]]:
    response = client.post(
        "/v1/beta/activate",
        json={"inviteCode": "invite-one", "installationId": "install-a"},
    )
    session = response.json()
    return session, {
        "Authorization": f"Bearer {session['betaAccessToken']}",
        "X-Sift-Installation": "install-a",
    }


def _connection_payload() -> dict[str, str]:
    return {
        "providerId": "openai",
        "baseURL": "https://api.openai.com/v1",
        "model": "gpt-5.5",
    }


def test_provider_connection_persists_only_non_secret_fields(tmp_path) -> None:
    app = _app(tmp_path)
    client = TestClient(app)
    _, headers = _session(client)

    saved = client.put(
        "/v1/provider-connection",
        headers=headers,
        json=_connection_payload(),
    )
    loaded = client.get("/v1/provider-connection", headers=headers)

    assert saved.status_code == 200
    assert loaded.json() == saved.json()
    assert "apiKey" not in saved.text
    assert PROVIDER_KEY not in _database_dump(app.state.test_database_path)


def test_provider_test_requires_ephemeral_key(tmp_path) -> None:
    client = TestClient(_app(tmp_path))
    _, headers = _session(client)

    response = client.post(
        "/v1/providers/test",
        headers=headers,
        json=_connection_payload(),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_provider_key"


def test_provider_test_relays_key_without_persisting_it(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path)
    client = TestClient(app)
    _, headers = _session(client)
    captured: dict[str, str] = {}

    def build(provider_name: str, *, base_url: str, api_key: str, timeout: float):
        captured.update(provider=provider_name, base_url=base_url, api_key=api_key)
        return MockRuntimeModelProvider()

    monkeypatch.setattr("sift_backend.runtime.managed_api.build_runtime_model_provider", build)
    response = client.post(
        "/v1/providers/test",
        headers=headers | {"X-Sift-Provider-Key": PROVIDER_KEY},
        json=_connection_payload(),
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert captured["api_key"] == PROVIDER_KEY
    assert PROVIDER_KEY not in response.text
    assert PROVIDER_KEY not in _database_dump(app.state.test_database_path)


def test_provider_failure_never_echoes_or_logs_secret(tmp_path, monkeypatch, caplog) -> None:
    class FailingProvider(MockRuntimeModelProvider):
        async def complete(self, request):
            raise SiftRuntimeError("provider_error", f"upstream leaked {PROVIDER_KEY}")

    monkeypatch.setattr(
        "sift_backend.runtime.managed_api.build_runtime_model_provider",
        lambda *args, **kwargs: FailingProvider(),
    )
    client = TestClient(_app(tmp_path))
    _, headers = _session(client)

    response = client.post(
        "/v1/providers/test",
        headers=headers | {"X-Sift-Provider-Key": PROVIDER_KEY},
        json=_connection_payload(),
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_provider_key"
    assert PROVIDER_KEY not in response.text
    assert PROVIDER_KEY not in caplog.text


def test_concept_runtime_uses_relayed_key_without_persistence(tmp_path, monkeypatch) -> None:
    app = _app(tmp_path)
    client = TestClient(app)
    _, headers = _session(client)
    client.put("/v1/provider-connection", headers=headers, json=_connection_payload())
    captured: dict[str, str] = {}

    def build(provider_name: str, *, base_url: str, api_key: str, timeout: float = 60):
        captured["api_key"] = api_key
        return MockRuntimeModelProvider()

    monkeypatch.setattr("sift_backend.api.concepts.build_runtime_model_provider", build)
    response = client.post(
        "/v1/concepts",
        headers=headers | {"X-Sift-Provider-Key": PROVIDER_KEY},
        json={"rawCapture": "Ephemeral BYOK", "locale": "en"},
    )

    assert response.status_code == 200
    assert captured["api_key"] == PROVIDER_KEY
    assert PROVIDER_KEY not in response.text
    assert PROVIDER_KEY not in _database_dump(app.state.test_database_path)


def test_managed_mode_blocks_legacy_secret_settings_endpoints(tmp_path) -> None:
    client = TestClient(_app(tmp_path))
    _, headers = _session(client)

    for method, path in (
        (client.get, "/v1/model-provider-settings"),
        (client.get, "/v1/web-provider-settings"),
        (client.get, "/v1/model-provider-settings/models"),
        (client.post, "/v1/model-diagnostic"),
        (client.post, "/v1/web-search-diagnostic"),
    ):
        response = method(path, headers=headers)
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "managed_unsupported"


def test_managed_catalog_and_status_never_expose_global_provider_secret(tmp_path) -> None:
    database_path = tmp_path / "managed-redaction.db"
    app = create_app(
        Settings(
            env="test",
            auth_mode="managed",
            database_url=f"sqlite:///{database_path}",
            runtime_provider="openai",
            runtime_api_key=PROVIDER_KEY,
            runtime_provider_settings={"openai": {"api_key": PROVIDER_KEY}},
            beta_invite_codes=("invite-one",),
        )
    )
    client = TestClient(app)
    _, headers = _session(client)

    responses = [
        client.get("/v1/app-status", headers=headers),
        client.get("/v1/runtime/model-providers", headers=headers),
    ]

    assert all(response.status_code == 200 for response in responses)
    assert all(PROVIDER_KEY not in response.text for response in responses)
    assert responses[0].json()["modelProvider"] == "managed-byok"
    assert responses[0].json()["databaseURL"] == "managed"


def test_managed_runtime_error_uses_safe_contract_envelope(tmp_path, monkeypatch) -> None:
    class FailingProvider(MockRuntimeModelProvider):
        async def complete(self, request):
            raise SiftRuntimeError("provider_error", f"upstream leaked {PROVIDER_KEY}")

    app = _app(tmp_path)
    client = TestClient(app)
    _, headers = _session(client)
    client.put("/v1/provider-connection", headers=headers, json=_connection_payload())
    monkeypatch.setattr(
        "sift_backend.api.concepts.build_runtime_model_provider",
        lambda *args, **kwargs: FailingProvider(),
    )

    response = client.post(
        "/v1/concepts",
        headers=headers | {"X-Sift-Provider-Key": PROVIDER_KEY},
        json={"rawCapture": "Safe error contract", "locale": "en"},
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "provider_unreachable"
    assert response.json()["error"]["requestId"]
    assert PROVIDER_KEY not in response.text


def _database_dump(path) -> str:
    with sqlite3.connect(path) as connection:
        return "\n".join(connection.iterdump())
