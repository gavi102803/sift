import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Settings:
    env: str = "development"
    log_level: str = "INFO"
    database_url: str = "sqlite:///./.data/sift.db"
    runtime_provider: str = "custom"
    runtime_base_url: str = ""
    runtime_api_key: str = ""
    runtime_model: str = "gpt-5.5"
    runtime_web_search_enabled: bool = True
    web_search_provider: str = "ddgs"
    web_search_api_key: str = ""
    runtime_provider_settings: dict[str, dict[str, str]] = field(default_factory=dict)
    web_provider_settings: dict[str, dict[str, str]] = field(default_factory=dict)


def load_settings(env_file: str | Path | None = None) -> Settings:
    env = _load_env_file(env_file)
    stored = _load_provider_settings_file(env)
    web_search_api_key = _setting_value(
        "SIFT_WEB_SEARCH_API_KEY",
        "web_search_api_key",
        Settings.web_search_api_key,
        env,
        stored,
    )
    web_search_provider = _setting_value(
        "SIFT_WEB_SEARCH_PROVIDER",
        "web_search_provider",
        Settings.web_search_provider,
        env,
        stored,
    )
    runtime_provider = _setting_value(
        "SIFT_RUNTIME_PROVIDER",
        "runtime_provider",
        Settings.runtime_provider,
        env,
        stored,
        legacy_env_names=("SIFT_MODEL_PROVIDER",),
        legacy_stored_names=("model_provider",),
    )
    runtime_base_url = _setting_value(
        "SIFT_RUNTIME_BASE_URL",
        "runtime_base_url",
        Settings.runtime_base_url,
        env,
        stored,
        legacy_env_names=("SIFT_OPENAI_COMPATIBLE_BASE_URL", "SIFT_OPENAI_BASE_URL"),
        legacy_stored_names=("openai_compatible_base_url", "openai_base_url"),
    )
    runtime_api_key = _setting_value(
        "SIFT_RUNTIME_API_KEY",
        "runtime_api_key",
        Settings.runtime_api_key,
        env,
        stored,
        legacy_env_names=("SIFT_OPENAI_COMPATIBLE_API_KEY", "SIFT_OPENAI_API_KEY"),
        legacy_stored_names=("openai_compatible_api_key", "openai_api_key"),
    )
    runtime_model = _setting_value(
        "SIFT_RUNTIME_MODEL",
        "runtime_model",
        Settings.runtime_model,
        env,
        stored,
        legacy_env_names=("SIFT_MODEL_EXPLAIN",),
        legacy_stored_names=("model_explain",),
    )
    runtime_provider_settings = _setting_map("runtime_provider_settings", stored)
    runtime_provider_settings = _merge_provider_config(
        runtime_provider_settings,
        runtime_provider,
        {
            "base_url": runtime_base_url,
            "api_key": runtime_api_key,
            "model": runtime_model,
        },
    )
    web_provider_settings = _setting_map("web_provider_settings", stored)
    web_provider_settings = _merge_provider_config(
        web_provider_settings,
        web_search_provider,
        {"api_key": web_search_api_key},
    )
    runtime_selected = runtime_provider_settings.get(runtime_provider, {})
    web_selected = web_provider_settings.get(web_search_provider, {})
    return Settings(
        env=_env_value("SIFT_ENV", Settings.env, env),
        log_level=_env_value("SIFT_LOG_LEVEL", Settings.log_level, env),
        database_url=_env_value("SIFT_DATABASE_URL", Settings.database_url, env),
        runtime_provider=runtime_provider,
        runtime_base_url=runtime_selected.get("base_url", runtime_base_url),
        runtime_api_key=runtime_selected.get("api_key", runtime_api_key),
        runtime_model=runtime_selected.get("model", runtime_model),
        runtime_web_search_enabled=_setting_bool(
            "SIFT_RUNTIME_WEB_SEARCH_ENABLED",
            "runtime_web_search_enabled",
            Settings.runtime_web_search_enabled,
            env,
            stored,
            legacy_env_names=("SIFT_ENABLE_WEB_SEARCH",),
            legacy_stored_names=("enable_web_search",),
        ),
        web_search_provider=_normalize_web_search_provider(
            web_search_provider,
            web_selected.get("api_key", web_search_api_key),
        ),
        web_search_api_key=web_selected.get("api_key", web_search_api_key),
        runtime_provider_settings=runtime_provider_settings,
        web_provider_settings=web_provider_settings,
    )


def provider_settings_path() -> Path:
    if path := os.environ.get("SIFT_PROVIDER_SETTINGS_PATH"):
        return Path(path)
    return Path(__file__).resolve().parents[3] / ".data" / "model-provider.json"


def write_provider_settings(settings: Settings) -> None:
    path = provider_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "runtime_provider": settings.runtime_provider,
                "runtime_base_url": settings.runtime_base_url,
                "runtime_api_key": settings.runtime_api_key,
                "runtime_model": settings.runtime_model,
                "runtime_web_search_enabled": settings.runtime_web_search_enabled,
                "web_search_provider": settings.web_search_provider,
                "web_search_api_key": settings.web_search_api_key,
                "runtime_provider_settings": settings.runtime_provider_settings,
                "web_provider_settings": settings.web_provider_settings,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _env_value(name: str, default: str, env_file_values: dict[str, str]) -> str:
    if name in os.environ:
        return os.environ[name]
    return env_file_values.get(name, default)


def _setting_value(
    env_name: str,
    stored_name: str,
    default: str,
    env_file_values: dict[str, str],
    stored_values: dict[str, str],
    legacy_env_names: tuple[str, ...] = (),
    legacy_stored_names: tuple[str, ...] = (),
) -> str:
    if env_name in os.environ:
        return os.environ[env_name]
    if env_name in env_file_values:
        return env_file_values[env_name]
    for legacy_name in legacy_env_names:
        if legacy_name in os.environ:
            return os.environ[legacy_name]
        if legacy_name in env_file_values:
            return env_file_values[legacy_name]
    if stored_name in stored_values:
        return stored_values[stored_name]
    for legacy_name in legacy_stored_names:
        if legacy_name in stored_values:
            return stored_values[legacy_name]
    return default


def _setting_bool(
    env_name: str,
    stored_name: str,
    default: bool,
    env_file_values: dict[str, str],
    stored_values: dict[str, str],
    legacy_env_names: tuple[str, ...] = (),
    legacy_stored_names: tuple[str, ...] = (),
) -> bool:
    if env_name in os.environ or env_name in env_file_values:
        return _env_bool(env_name, default, env_file_values)
    for legacy_name in legacy_env_names:
        if legacy_name in os.environ or legacy_name in env_file_values:
            return _env_bool(legacy_name, default, env_file_values)
    value = stored_values.get(stored_name)
    if value is None:
        for legacy_name in legacy_stored_names:
            if legacy_name in stored_values:
                value = stored_values[legacy_name]
                break
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_web_search_provider(provider: str, api_key: str) -> str:
    normalized = provider.strip().lower()
    if normalized == "tavily" and not api_key.strip():
        return "ddgs"
    return normalized or Settings.web_search_provider


def _env_bool(name: str, default: bool, env_file_values: dict[str, str]) -> bool:
    value = os.environ[name] if name in os.environ else env_file_values.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _load_env_file(env_file: str | Path | None) -> dict[str, str]:
    path = Path(env_file) if env_file is not None else _default_env_file()
    if path is None or not path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        values[name] = _strip_optional_quotes(value)
    return values


def _default_env_file() -> Path | None:
    for path in (
        Path.cwd() / ".env",
        Path(__file__).resolve().parents[2] / ".env",
        Path(__file__).resolve().parents[3] / ".env",
    ):
        if path.exists():
            return path

    return None


def _setting_map(stored_name: str, stored_values: dict[str, Any]) -> dict[str, dict[str, str]]:
    value = stored_values.get(stored_name)
    if not isinstance(value, dict):
        return {}
    out: dict[str, dict[str, str]] = {}
    for provider, config in value.items():
        if not isinstance(provider, str) or not isinstance(config, dict):
            continue
        clean_config = {
            key: item
            for key, item in config.items()
            if isinstance(key, str) and isinstance(item, str)
        }
        if clean_config:
            out[provider] = clean_config
    return out


def _merge_provider_config(
    configs: dict[str, dict[str, str]],
    provider: str,
    config: dict[str, str],
) -> dict[str, dict[str, str]]:
    normalized = provider.strip().lower()
    if not normalized:
        return configs
    merged = {key: dict(value) for key, value in configs.items()}
    existing = merged.get(normalized, {})
    for key, value in config.items():
        if value:
            existing[key] = value
    if existing:
        merged[normalized] = existing
    return merged


def _load_provider_settings_file(env_file_values: dict[str, str]) -> dict[str, Any]:
    raw_path = _env_value("SIFT_PROVIDER_SETTINGS_PATH", "", env_file_values)
    path = Path(raw_path) if raw_path else provider_settings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    values: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(key, str) and isinstance(value, str):
            values[key] = value
        if isinstance(key, str) and isinstance(value, bool):
            values[key] = "true" if value else "false"
        if isinstance(key, str) and isinstance(value, dict):
            values[key] = value
    return values


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
