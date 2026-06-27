import json

from sift_backend.config import Settings, load_settings, write_provider_settings


def test_load_settings_reads_only_infrastructure_from_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(tmp_path / "missing.json"))
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SIFT_ENV=test",
                "SIFT_USER_ID=user-123",
                "SIFT_LOG_LEVEL=DEBUG",
                "SIFT_DATABASE_URL=sqlite:///./.data/test.db",
                "SIFT_RUNTIME_API_KEY=ignored-key",
                "SIFT_RUNTIME_MODEL=ignored-model",
                "SIFT_OPENAI_API_KEY=ignored-legacy-key",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)

    assert settings.env == "test"
    assert settings.user_id == "user-123"
    assert settings.log_level == "DEBUG"
    assert settings.database_url == "sqlite:///./.data/test.db"
    assert settings.runtime_api_key == ""
    assert settings.runtime_model == "gpt-5.5"


def test_load_settings_reads_runtime_from_provider_settings_file(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "model-provider.json"
    settings_path.write_text(
        json.dumps(
            {
                "runtime_provider": "deepseek",
                "runtime_web_search_enabled": False,
                "runtime_provider_settings": {
                    "deepseek": {
                        "base_url": "https://api.deepseek.com/v1",
                        "api_key": "deepseek-key",
                        "model": "deepseek-chat",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(settings_path))
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SIFT_RUNTIME_API_KEY=ignored-env-key",
                "SIFT_RUNTIME_MODEL=ignored-env-model",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)

    assert settings.runtime_provider == "deepseek"
    assert settings.runtime_base_url == "https://api.deepseek.com/v1"
    assert settings.runtime_api_key == "deepseek-key"
    assert settings.runtime_model == "deepseek-chat"
    assert settings.runtime_web_search_enabled is False


def test_load_settings_migrates_tavily_without_key_to_ddgs(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "model-provider.json"
    settings_path.write_text(
        json.dumps({"web_search_provider": "tavily", "web_search_api_key": ""}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(settings_path))

    settings = load_settings(env_file=tmp_path / ".env")

    assert settings.web_search_provider == "ddgs"


def test_load_settings_keeps_tavily_when_key_is_configured(tmp_path, monkeypatch) -> None:
    settings_path = tmp_path / "model-provider.json"
    settings_path.write_text(
        json.dumps({"web_search_provider": "tavily", "web_search_api_key": "tavily-key"}),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(settings_path))

    settings = load_settings(env_file=tmp_path / ".env")

    assert settings.web_search_provider == "tavily"
    assert settings.web_search_api_key == "tavily-key"


def test_write_provider_settings_stores_credential_refs_not_plaintext_json(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "model-provider.json"
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(settings_path))

    write_provider_settings(
        Settings(
            runtime_provider="deepseek",
            runtime_base_url="https://api.deepseek.com/v1",
            runtime_api_key="deepseek-secret",
            runtime_model="deepseek-chat",
            runtime_provider_settings={
                "deepseek": {
                    "base_url": "https://api.deepseek.com/v1",
                    "api_key": "deepseek-secret",
                    "model": "deepseek-chat",
                }
            },
        )
    )

    raw_settings = json.loads(settings_path.read_text(encoding="utf-8"))

    assert "deepseek-secret" not in settings_path.read_text(encoding="utf-8")
    assert raw_settings["runtime_provider_settings"]["deepseek"]["api_key_ref"] == (
        "user:local-dev:runtime:deepseek:api_key"
    )
    assert "api_key" not in raw_settings["runtime_provider_settings"]["deepseek"]

    reloaded = load_settings(env_file=tmp_path / ".env")

    assert reloaded.runtime_api_key == "deepseek-secret"


def test_write_provider_settings_scopes_credentials_by_user_id(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "model-provider.json"
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(settings_path))

    write_provider_settings(
        Settings(
            user_id="user@example.com",
            runtime_provider="deepseek",
            runtime_provider_settings={
                "deepseek": {
                    "api_key": "deepseek-secret",
                    "model": "deepseek-chat",
                }
            },
        )
    )

    raw_settings = json.loads(settings_path.read_text(encoding="utf-8"))

    assert raw_settings["runtime_provider_settings"]["deepseek"]["api_key_ref"] == (
        "user:user_example.com:runtime:deepseek:api_key"
    )
    assert (
        tmp_path
        / ".credentials"
        / "user:user_example.com:runtime:deepseek:api_key"
    ).read_text(encoding="utf-8") == "deepseek-secret"


def test_load_settings_reads_legacy_credential_ref_for_migration(
    tmp_path,
    monkeypatch,
) -> None:
    settings_path = tmp_path / "model-provider.json"
    credentials_path = tmp_path / ".credentials"
    credentials_path.mkdir()
    (credentials_path / "runtime:deepseek:api_key").write_text(
        "legacy-secret",
        encoding="utf-8",
    )
    settings_path.write_text(
        json.dumps(
            {
                "runtime_provider": "deepseek",
                "runtime_provider_settings": {
                    "deepseek": {
                        "api_key_ref": "runtime:deepseek:api_key",
                        "model": "deepseek-chat",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("SIFT_PROVIDER_SETTINGS_PATH", str(settings_path))

    settings = load_settings(env_file=tmp_path / ".env")

    assert settings.runtime_api_key == "legacy-secret"

    write_provider_settings(settings)
    raw_settings = json.loads(settings_path.read_text(encoding="utf-8"))

    assert raw_settings["runtime_provider_settings"]["deepseek"]["api_key_ref"] == (
        "user:local-dev:runtime:deepseek:api_key"
    )
