import json

from sift_backend.config import load_settings


def test_load_settings_reads_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SIFT_RUNTIME_API_KEY", raising=False)
    monkeypatch.delenv("SIFT_RUNTIME_WEB_SEARCH_ENABLED", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SIFT_RUNTIME_API_KEY='file-key'",
                "SIFT_RUNTIME_WEB_SEARCH_ENABLED=false",
                "SIFT_RUNTIME_MODEL=gpt-test",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)

    assert settings.runtime_api_key == "file-key"
    assert settings.runtime_web_search_enabled is False
    assert settings.runtime_model == "gpt-test"


def test_load_settings_prefers_process_environment_over_env_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SIFT_RUNTIME_API_KEY", "process-key")
    env_file = tmp_path / ".env"
    env_file.write_text("SIFT_RUNTIME_API_KEY=file-key", encoding="utf-8")

    settings = load_settings(env_file=env_file)

    assert settings.runtime_api_key == "process-key"


def test_load_settings_accepts_legacy_provider_env_names(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("SIFT_RUNTIME_API_KEY", raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "SIFT_OPENAI_API_KEY=legacy-key",
                "SIFT_MODEL_EXPLAIN=legacy-model",
                "SIFT_ENABLE_WEB_SEARCH=false",
            ]
        ),
        encoding="utf-8",
    )

    settings = load_settings(env_file=env_file)

    assert settings.runtime_api_key == "legacy-key"
    assert settings.runtime_model == "legacy-model"
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
