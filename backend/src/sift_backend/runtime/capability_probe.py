import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

from sift_backend.runtime.capability_policies import StructuredOutputStrategy
from sift_backend.runtime.types import RuntimeMessage, RuntimeModelProvider, RuntimeModelRequest

PROBE_VERSION = "2026-06-27.1"
PROTOCOL_DRIVER_VERSION = "chat-completions-2026-06-27.1"
PAYLOAD_MAPPER_VERSION = "chat-payload-2026-06-27.1"
SCHEMA_VERSION = "sift-runtime-output-2026-06-27.1"
SUCCESS_TTL = timedelta(days=30)
UNSUPPORTED_TTL = timedelta(days=180)
MALFORMED_TTL = timedelta(hours=6)


@dataclass(frozen=True)
class CapabilityProbeCaseResult:
    ok: bool
    message: str
    failure_kind: str | None = None


@dataclass(frozen=True)
class CapabilityProbeResult:
    provider: str
    model: str
    base_url_fingerprint: str
    probe_version: str
    protocol_driver_version: str
    payload_mapper_version: str
    schema_version: str
    plain_completion: CapabilityProbeCaseResult
    structured_output: dict[str, CapabilityProbeCaseResult]
    selected_structured_output: str | None


async def probe_model_capabilities(
    provider: RuntimeModelProvider,
    *,
    provider_name: str,
    model: str,
    base_url: str | None = None,
) -> CapabilityProbeResult:
    resolved_base_url = base_url if base_url is not None else _provider_base_url(provider)
    plain = await _probe_plain_completion(provider, model)
    structured: dict[str, CapabilityProbeCaseResult] = {}
    for strategy in (
        StructuredOutputStrategy.JSON_SCHEMA,
        StructuredOutputStrategy.JSON_OBJECT,
        StructuredOutputStrategy.PROMPT_AND_VALIDATE,
    ):
        structured[strategy.value] = await _probe_structured_output(provider, model, strategy)
    selected = _select_structured_strategy(structured)
    result = CapabilityProbeResult(
        provider=provider_name,
        model=model,
        base_url_fingerprint=_base_url_fingerprint(resolved_base_url),
        probe_version=PROBE_VERSION,
        protocol_driver_version=PROTOCOL_DRIVER_VERSION,
        payload_mapper_version=PAYLOAD_MAPPER_VERSION,
        schema_version=SCHEMA_VERSION,
        plain_completion=plain,
        structured_output=structured,
        selected_structured_output=selected,
    )
    if _last_failure_kind(result) != "auth_failed":
        write_capability_probe_result(result)
    return result


def get_cached_structured_output_strategy(
    provider_name: str,
    model: str,
    *,
    base_url: str | None = None,
) -> str | None:
    cache = _read_probe_cache()
    fingerprint = _base_url_fingerprint(base_url or "")
    record = cache.get(_cache_key(provider_name, fingerprint, model))
    if not isinstance(record, dict) or not _record_versions_match(record):
        return None
    expires_at = _parse_datetime(record.get("expiresAt"))
    if expires_at is None or expires_at <= _now():
        return None
    selected = record.get("selected_structured_output")
    return selected if isinstance(selected, str) else None


def write_capability_probe_result(result: CapabilityProbeResult) -> None:
    path = capability_probe_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = _read_probe_cache()
    cache[
        _cache_key(result.provider, result.base_url_fingerprint, result.model)
    ] = _result_to_json(result)
    path.write_text(json.dumps(cache, indent=2), encoding="utf-8")


def capability_probe_cache_path() -> Path:
    if path := os.environ.get("SIFT_CAPABILITY_PROBE_CACHE_PATH"):
        return Path(path)
    return Path(__file__).resolve().parents[3] / ".data" / "capability-probes.json"


async def _probe_plain_completion(
    provider: RuntimeModelProvider,
    model: str,
) -> CapabilityProbeCaseResult:
    try:
        response = await provider.complete(
            RuntimeModelRequest(
                model=model,
                messages=(RuntimeMessage(role="user", content="Reply with exactly: ok"),),
            )
        )
    except Exception as error:
        return CapabilityProbeCaseResult(ok=False, message=str(error))
    ok = response.content.strip().lower().startswith("ok")
    return CapabilityProbeCaseResult(
        ok=ok,
        message="plain completion responded" if ok else "plain completion response was unexpected",
    )


async def _probe_structured_output(
    provider: RuntimeModelProvider,
    model: str,
    strategy: StructuredOutputStrategy,
) -> CapabilityProbeCaseResult:
    response_format = _probe_response_format(strategy)
    try:
        response = await provider.complete(
            RuntimeModelRequest(
                model=model,
                messages=(
                    RuntimeMessage(
                        role="user",
                        content='Return JSON {"ok": true}.',
                    ),
                ),
                response_format=response_format,
                structured_output_strategy=strategy.value,
            )
        )
        payload = json.loads(response.content.strip())
        _validate_probe_schema(payload)
    except Exception as error:
        return CapabilityProbeCaseResult(
            ok=False,
            message=str(error),
            failure_kind=_failure_kind(error),
        )
    ok = payload.get("ok") is True
    return CapabilityProbeCaseResult(
        ok=ok,
        message=(
            f"{strategy.value} responded with validated JSON"
            if ok
            else f"{strategy.value} returned schema-invalid JSON"
        ),
        failure_kind=None if ok else "malformed_response",
    )


def _probe_response_format(strategy: StructuredOutputStrategy) -> dict[str, Any] | None:
    if strategy == StructuredOutputStrategy.PROMPT_AND_VALIDATE:
        return None
    if strategy == StructuredOutputStrategy.JSON_OBJECT:
        return {"type": "json_object"}
    return {
        "type": "json_schema",
        "json_schema": {
            "name": "sift_capability_probe",
            "strict": True,
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "required": ["ok"],
                "properties": {"ok": {"type": "boolean"}},
            },
        },
    }


def _validate_probe_schema(payload: Any) -> None:
    if not isinstance(payload, dict):
        raise ValueError("probe response JSON must be an object")
    if set(payload) != {"ok"}:
        raise ValueError("probe response JSON must contain only the required ok field")
    if payload.get("ok") is not True:
        raise ValueError("probe response JSON ok must be true")


def _select_structured_strategy(results: dict[str, CapabilityProbeCaseResult]) -> str | None:
    for strategy in (
        StructuredOutputStrategy.JSON_SCHEMA,
        StructuredOutputStrategy.JSON_OBJECT,
        StructuredOutputStrategy.PROMPT_AND_VALIDATE,
    ):
        result = results.get(strategy.value)
        if result and result.ok:
            return strategy.value
    return None


def _read_probe_cache() -> dict[str, Any]:
    path = capability_probe_cache_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _result_to_json(result: CapabilityProbeResult) -> dict[str, Any]:
    ttl = _cache_ttl(result)
    created_at = _now()
    return {
        "provider": result.provider,
        "model": result.model,
        "baseURLFingerprint": result.base_url_fingerprint,
        "probe_version": result.probe_version,
        "protocolDriverVersion": result.protocol_driver_version,
        "payloadMapperVersion": result.payload_mapper_version,
        "schemaVersion": result.schema_version,
        "createdAt": created_at.isoformat(),
        "expiresAt": (created_at + ttl).isoformat(),
        "lastFailureKind": _last_failure_kind(result),
        "plain_completion": _case_to_json(result.plain_completion),
        "structured_output": {
            key: _case_to_json(value)
            for key, value in result.structured_output.items()
        },
        "selected_structured_output": result.selected_structured_output,
    }


def _case_to_json(result: CapabilityProbeCaseResult) -> dict[str, Any]:
    return {
        "ok": result.ok,
        "message": result.message[:500],
        "failureKind": result.failure_kind,
    }


def _cache_key(provider_name: str, base_url_fingerprint: str, model: str) -> str:
    return (
        f"{provider_name.strip().lower()}::{base_url_fingerprint}::"
        f"{PROTOCOL_DRIVER_VERSION}::{PAYLOAD_MAPPER_VERSION}::{SCHEMA_VERSION}::"
        f"{PROBE_VERSION}::{model.strip()}"
    )


def _base_url_fingerprint(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/").lower()
    if not normalized:
        return "none"
    return sha256(normalized.encode("utf-8")).hexdigest()[:16]


def _provider_base_url(provider: RuntimeModelProvider) -> str:
    base_url = getattr(provider, "base_url", "")
    return base_url if isinstance(base_url, str) else ""


def _record_versions_match(record: dict[str, Any]) -> bool:
    return (
        record.get("probe_version") == PROBE_VERSION
        and record.get("protocolDriverVersion") == PROTOCOL_DRIVER_VERSION
        and record.get("payloadMapperVersion") == PAYLOAD_MAPPER_VERSION
        and record.get("schemaVersion") == SCHEMA_VERSION
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed


def _cache_ttl(result: CapabilityProbeResult) -> timedelta:
    failure_kind = _last_failure_kind(result)
    if failure_kind in {"unsupported_parameter", "unsupported_response_format"}:
        return UNSUPPORTED_TTL
    if failure_kind in {"malformed_response", "invalid_json"}:
        return MALFORMED_TTL
    return SUCCESS_TTL


def _last_failure_kind(result: CapabilityProbeResult) -> str | None:
    failures = [
        case.failure_kind
        for case in [result.plain_completion, *result.structured_output.values()]
        if not case.ok and case.failure_kind
    ]
    return failures[0] if failures else None


def _failure_kind(error: Exception) -> str:
    if isinstance(error, json.JSONDecodeError):
        return "invalid_json"
    if isinstance(error, ValueError) and "probe response JSON" in str(error):
        return "malformed_response"
    code = getattr(error, "code", None)
    message = str(error).casefold()
    if code == "provider_timeout" or "timeout" in message:
        return "transient"
    if "401" in message or "403" in message or "auth" in message:
        return "auth_failed"
    if "response_format" in message and "json_schema" in message:
        return "unsupported_response_format"
    if "unsupported" in message or "unavailable" in message:
        return "unsupported_parameter"
    if "5" in message and "http" in message:
        return "transient"
    return "provider_error"


def _now() -> datetime:
    return datetime.now(UTC)
