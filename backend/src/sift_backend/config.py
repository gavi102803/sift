import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sift_backend.credential_store import (
    credential_ref,
    credential_store_for_settings_path,
    legacy_credential_ref,
)


@dataclass(frozen=True)
class Settings:
    env: str = "development"
    user_id: str = "local-dev"
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
    settings_path = _resolved_provider_settings_path(env)
    credential_store = credential_store_for_settings_path(settings_path)
    stored = _load_provider_settings_file(env)
    runtime_provider = _stored_str(stored, "runtime_provider", Settings.runtime_provider)
    runtime_base_url = _stored_str(stored, "runtime_base_url", Settings.runtime_base_url)
    runtime_api_key = _stored_str(stored, "runtime_api_key", Settings.runtime_api_key)
    runtime_model = _stored_str(stored, "runtime_model", Settings.runtime_model)
    web_search_provider = _stored_str(
        stored,
        "web_search_provider",
        Settings.web_search_provider,
    )
    web_search_api_key = _stored_str(
        stored,
        "web_search_api_key",
        Settings.web_search_api_key,
    )
    runtime_provider_settings = _setting_map("runtime_provider_settings", stored)
    runtime_provider_settings = _resolve_provider_credentials(
        runtime_provider_settings,
        credential_store,
        kind="runtime",
    )
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
    web_provider_settings = _resolve_provider_credentials(
        web_provider_settings,
        credential_store,
        kind="web",
    )
    web_provider_settings = _merge_provider_config(
        web_provider_settings,
        web_search_provider,
        {"api_key": web_search_api_key},
    )
    runtime_selected = runtime_provider_settings.get(runtime_provider, {})
    web_selected = web_provider_settings.get(web_search_provider, {})
    return Settings(
        env=_env_value("SIFT_ENV", Settings.env, env),
        user_id=_env_value("SIFT_USER_ID", Settings.user_id, env),
        log_level=_env_value("SIFT_LOG_LEVEL", Settings.log_level, env),
        database_url=_env_value("SIFT_DATABASE_URL", Settings.database_url, env),
        runtime_provider=runtime_provider,
        runtime_base_url=runtime_selected.get("base_url", runtime_base_url),
        runtime_api_key=runtime_selected.get("api_key", runtime_api_key),
        runtime_model=runtime_selected.get("model", runtime_model),
        runtime_web_search_enabled=_stored_bool(
            stored,
            "runtime_web_search_enabled",
            Settings.runtime_web_search_enabled,
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
    credential_store = credential_store_for_settings_path(path)
    runtime_provider_settings = _settings_with_credential_refs(
        settings.runtime_provider_settings,
        credential_store,
        kind="runtime",
        user_id=settings.user_id,
    )
    web_provider_settings = _settings_with_credential_refs(
        settings.web_provider_settings,
        credential_store,
        kind="web",
        user_id=settings.user_id,
    )
    path.write_text(
        json.dumps(
            {
                "runtime_provider": settings.runtime_provider,
                "runtime_base_url": settings.runtime_base_url,
                "runtime_model": settings.runtime_model,
                "runtime_web_search_enabled": settings.runtime_web_search_enabled,
                "web_search_provider": settings.web_search_provider,
                "runtime_provider_settings": runtime_provider_settings,
                "web_provider_settings": web_provider_settings,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _env_value(name: str, default: str, env_file_values: dict[str, str]) -> str:
    if name in os.environ:
        return os.environ[name]
    return env_file_values.get(name, default)


def _stored_str(stored_values: dict[str, Any], name: str, default: str) -> str:
    value = stored_values.get(name)
    return value if isinstance(value, str) else default


def _stored_bool(
    stored_values: dict[str, Any],
    stored_name: str,
    default: bool,
) -> bool:
    value = stored_values.get(stored_name)
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
    overwrite_keys: set[str] | None = None,
) -> dict[str, dict[str, str]]:
    normalized = provider.strip().lower()
    if not normalized:
        return configs
    merged = {key: dict(value) for key, value in configs.items()}
    existing = merged.get(normalized, {})
    overwrite_keys = overwrite_keys or set()
    for key, value in config.items():
        if value and (key not in existing or key in overwrite_keys):
            existing[key] = value
    if existing:
        merged[normalized] = existing
    return merged


def _resolve_provider_credentials(
    configs: dict[str, dict[str, str]],
    credential_store,
    *,
    kind: str,
) -> dict[str, dict[str, str]]:
    resolved: dict[str, dict[str, str]] = {}
    for provider, config in configs.items():
        next_config = dict(config)
        if not next_config.get("api_key"):
            api_key = _resolve_configured_api_key(
                provider,
                next_config,
                credential_store,
                kind=kind,
            )
            if api_key:
                next_config["api_key"] = api_key
        resolved[provider] = next_config
    return resolved


def _resolve_configured_api_key(
    provider: str,
    config: dict[str, str],
    credential_store,
    *,
    kind: str,
) -> str:
    if config.get("api_key_ref"):
        api_key = credential_store.get(config["api_key_ref"])
        if api_key:
            return api_key
    return credential_store.get(legacy_credential_ref(kind, provider))


def _settings_with_credential_refs(
    configs: dict[str, dict[str, str]],
    credential_store,
    *,
    kind: str,
    user_id: str,
) -> dict[str, dict[str, str]]:
    serialized: dict[str, dict[str, str]] = {}
    for provider, config in configs.items():
        next_config = {
            key: value
            for key, value in config.items()
            if key not in {"api_key", "api_key_ref"}
        }
        api_key = config.get("api_key", "")
        if api_key:
            ref = config.get("api_key_ref")
            if ref and not ref.startswith("user:"):
                ref = credential_ref(kind, provider, user_id=user_id)
            ref = ref or credential_ref(kind, provider, user_id=user_id)
            credential_store.set(ref, api_key)
            next_config["api_key_ref"] = ref
        elif config.get("api_key_ref"):
            next_config["api_key_ref"] = config["api_key_ref"]
        serialized[provider] = next_config
    return serialized


def _load_provider_settings_file(env_file_values: dict[str, str]) -> dict[str, Any]:
    path = _resolved_provider_settings_path(env_file_values)
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


def _resolved_provider_settings_path(env_file_values: dict[str, str]) -> Path:
    raw_path = _env_value("SIFT_PROVIDER_SETTINGS_PATH", "", env_file_values)
    return Path(raw_path) if raw_path else provider_settings_path()


def _strip_optional_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value
