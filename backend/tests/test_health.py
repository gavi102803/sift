from fastapi.testclient import TestClient

from sift_backend.concepts.service import ConceptService
from sift_backend.config import Settings
from sift_backend.main import _filter_runtime_models, create_app


def test_health_returns_ok() -> None:
    client = TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "env": "development"}


def test_app_status_reports_mock_backend_when_no_model_key_is_configured() -> None:
    client = TestClient(
        create_app(
            settings=Settings(database_url="sqlite:///./.data/test.db"),
            concept_service=ConceptService(),
        )
    )

    response = client.get("/v1/app-status")

    assert response.status_code == 200
    assert response.json() == {
        "env": "development",
        "modelProvider": "mock",
        "explainModel": "gpt-5.5",
        "webSearchEnabled": True,
        "databaseURL": "sqlite:///./.data/test.db",
        "providerBaseURL": "https://api.openai.com/v1",
        "apiKeyConfigured": False,
        "apiKeyPreview": None,
    }


def test_app_status_reports_configured_runtime() -> None:
    client = TestClient(
        create_app(
            settings=Settings(
                runtime_api_key="runtime-key",
                runtime_model="gpt-test",
                database_url="postgresql://user:password@localhost:5432/sift",
            ),
            concept_service=ConceptService(),
        )
    )

    response = client.get("/v1/app-status")

    assert response.status_code == 200
    assert response.json()["modelProvider"] == "custom"
    assert response.json()["explainModel"] == "gpt-test"
    assert response.json()["databaseURL"] == "postgresql://***@localhost:5432/sift"
    assert response.json()["apiKeyConfigured"] is True
    assert response.json()["apiKeyPreview"] == "***-key"


def test_model_diagnostic_reports_mock_mode_without_provider_key() -> None:
    client = TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )

    response = client.post("/v1/model-diagnostic")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "provider": "mock",
        "model": "mock-runtime",
        "message": "No runtime key configured; mock runtime is active.",
    }


def test_web_search_diagnostic_uses_default_ddgs_provider() -> None:
    client = TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )

    response = client.post("/v1/web-search-diagnostic")

    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "provider": "mock",
        "model": "gpt-5.5",
        "message": "Runtime web search tool configured: ddgs.",
        "webSearchUsed": False,
        "citationCount": 0,
    }


def test_model_provider_settings_update_masks_key_and_rebuilds_status(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(tmp_path / "model-provider.json"))
    client = TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )

    response = client.put(
        "/v1/model-provider-settings",
        json={
            "providerType": "sift_runtime",
            "baseURL": "https://runtime.example/v1",
            "apiKey": "runtime-test-key",
            "explainModel": "runtime-model",
            "webSearchEnabled": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "providerType": "custom",
        "baseURL": "https://runtime.example/v1",
        "apiKeyConfigured": True,
        "apiKeyPreview": "***-key",
        "explainModel": "runtime-model",
        "webSearchEnabled": True,
        "supportsWebSearch": True,
    }

    status_response = client.get("/v1/app-status")

    assert status_response.status_code == 200
    assert status_response.json()["modelProvider"] == "custom"
    assert status_response.json()["apiKeyPreview"] == "***-key"
    assert status_response.json()["webSearchEnabled"] is True


def test_runtime_provider_catalog_lists_hermes_model_and_web_providers() -> None:
    client = TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )

    model_response = client.get("/v1/runtime/model-providers")
    web_response = client.get("/v1/runtime/web-providers")

    assert model_response.status_code == 200
    model_providers = {provider["id"]: provider for provider in model_response.json()["providers"]}
    assert model_providers["deepseek"]["status"] == "available"
    assert model_providers["deepseek"]["apiMode"] == "chat_completions"
    assert model_providers["deepseek"]["protocolDriver"] == "ChatCompletionsDriver"
    assert (
        model_providers["deepseek"]["hermesPluginPath"]
        == "plugins/model-providers/deepseek/__init__.py"
    )
    assert model_providers["deepseek"]["exposureTier"] == "plannedStable"
    assert model_providers["anthropic"]["status"] == "available"
    assert model_providers["anthropic"]["adapter"] == "anthropic_messages"
    assert model_providers["anthropic"]["protocolDriver"] == "AnthropicMessagesDriver"
    assert model_providers["gemini"]["status"] == "available"
    assert model_providers["gemini"]["exposureTier"] == "plannedStable"
    assert model_providers["gemini"]["adapter"] == "gemini"
    assert model_providers["gemini"]["protocolDriver"] == "GeminiDriver"
    assert model_providers["custom"]["isAdvanced"] is True
    assert model_providers["alibaba"]["exposureTier"] == "advanced"
    assert model_providers["alibaba"]["isAdvanced"] is True
    assert {provider["status"] for provider in model_response.json()["providers"]}.isdisjoint(
        {"comingSoon"}
    )
    assert "mock" not in model_providers
    assert "bedrock" not in model_providers
    assert "qwen-oauth" not in model_providers
    assert "xai" not in model_providers

    assert web_response.status_code == 200
    web_providers = {provider["id"]: provider for provider in web_response.json()["providers"]}
    assert web_providers["ddgs"]["requiresApiKey"] is False
    assert web_providers["ddgs"]["isDefault"] is True
    assert web_providers["tavily"]["supportsExtract"] is True
    assert web_providers["exa"]["status"] == "available"
    assert web_providers["firecrawl"]["status"] == "available"
    assert web_providers["brave-free"]["status"] == "available"
    assert "parallel" not in web_providers
    assert "searxng" not in web_providers


def test_runtime_model_filter_hides_non_chat_and_test_models() -> None:
    models = _filter_runtime_models(
        [
            "text-embedding-3-large",
            "gpt-5.5testmodel",
            "gpt-4.1-mini",
            "gpt-5.5",
            "gpt-5.5-2026-04-23",
            "gpt-5-codex",
            "gpt-5-search-api",
            "tts-1",
            "omni-moderation-latest",
        ],
        provider_name="openai",
        preferred_model="gpt-5.5",
    )

    assert models == ["gpt-5.5", "gpt-4.1-mini"]


def test_web_provider_settings_update_masks_key_and_rebuilds_status(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(tmp_path / "model-provider.json"))
    client = TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )

    response = client.put(
        "/v1/web-provider-settings",
        json={
            "providerType": "tavily",
            "apiKey": "tavily-test-key",
            "webSearchEnabled": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "providerType": "tavily",
        "apiKeyConfigured": True,
        "apiKeyPreview": "***-key",
        "webSearchEnabled": True,
    }

    status_response = client.post("/v1/web-search-diagnostic")

    assert status_response.status_code == 200
    assert status_response.json()["message"] == "Runtime web search tool configured: tavily."


def test_model_provider_settings_rejects_discarded_upstream_provider() -> None:
    client = TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )

    response = client.put(
        "/v1/model-provider-settings",
        json={
            "providerType": "bedrock",
            "baseURL": "https://bedrock-runtime.us-east-1.amazonaws.com",
            "apiKey": "test-key",
            "explainModel": "anthropic.claude-sonnet-4-5",
            "webSearchEnabled": True,
        },
    )

    assert response.status_code == 422
    assert "not registered" in response.json()["detail"]


def test_provider_settings_are_stored_per_provider(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(tmp_path / "model-provider.json"))
    client = TestClient(
        create_app(
            settings=Settings(runtime_api_key=""),
            concept_service=ConceptService(),
        )
    )

    deepseek_response = client.put(
        "/v1/model-provider-settings",
        json={
            "providerType": "deepseek",
            "baseURL": "https://api.deepseek.com/v1",
            "apiKey": "deepseek-key",
            "explainModel": "deepseek-chat",
            "webSearchEnabled": True,
        },
    )
    openai_response = client.put(
        "/v1/model-provider-settings",
        json={
            "providerType": "openai",
            "baseURL": "https://api.openai.com/v1",
            "apiKey": "openai-key",
            "explainModel": "gpt-5.5",
            "webSearchEnabled": True,
        },
    )

    assert deepseek_response.status_code == 200
    assert openai_response.status_code == 200

    catalog = client.get("/v1/runtime/model-providers").json()["providers"]
    by_id = {provider["id"]: provider for provider in catalog}

    assert by_id["deepseek"]["apiKeyPreview"] == "***-key"
    assert by_id["deepseek"]["configuredModel"] == "deepseek-chat"
    assert by_id["openai"]["apiKeyPreview"] == "***-key"
    assert by_id["openai"]["configuredModel"] == "gpt-5.5"
