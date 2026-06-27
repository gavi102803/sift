import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sift_backend.runtime.capability_policies import StructuredOutputStrategy
from sift_backend.runtime.types import RuntimeMessage, RuntimeModelProvider, RuntimeModelRequest

PROBE_VERSION = "2026-06-27.1"


@dataclass(frozen=True)
class CapabilityProbeCaseResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class CapabilityProbeResult:
    provider: str
    model: str
    probe_version: str
    plain_completion: CapabilityProbeCaseResult
    structured_output: dict[str, CapabilityProbeCaseResult]
    selected_structured_output: str | None


async def probe_model_capabilities(
    provider: RuntimeModelProvider,
    *,
    provider_name: str,
    model: str,
) -> CapabilityProbeResult:
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
        probe_version=PROBE_VERSION,
        plain_completion=plain,
        structured_output=structured,
        selected_structured_output=selected,
    )
    write_capability_probe_result(result)
    return result


def get_cached_structured_output_strategy(provider_name: str, model: str) -> str | None:
    cache = _read_probe_cache()
    record = cache.get(_cache_key(provider_name, model))
    if not isinstance(record, dict) or record.get("probe_version") != PROBE_VERSION:
        return None
    selected = record.get("selected_structured_output")
    return selected if isinstance(selected, str) else None


def write_capability_probe_result(result: CapabilityProbeResult) -> None:
    path = capability_probe_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = _read_probe_cache()
    cache[_cache_key(result.provider, result.model)] = _result_to_json(result)
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
                response_format=_probe_response_format(strategy),
                structured_output_strategy=strategy.value,
            )
        )
        payload = json.loads(response.content.strip())
    except Exception as error:
        return CapabilityProbeCaseResult(ok=False, message=str(error))
    ok = isinstance(payload, dict) and payload.get("ok") is True
    return CapabilityProbeCaseResult(
        ok=ok,
        message=f"{strategy.value} responded" if ok else f"{strategy.value} returned invalid JSON",
    )


def _probe_response_format(strategy: StructuredOutputStrategy) -> dict[str, Any]:
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
    return {
        "provider": result.provider,
        "model": result.model,
        "probe_version": result.probe_version,
        "plain_completion": _case_to_json(result.plain_completion),
        "structured_output": {
            key: _case_to_json(value)
            for key, value in result.structured_output.items()
        },
        "selected_structured_output": result.selected_structured_output,
    }


def _case_to_json(result: CapabilityProbeCaseResult) -> dict[str, Any]:
    return {"ok": result.ok, "message": result.message[:500]}


def _cache_key(provider_name: str, model: str) -> str:
    return f"{provider_name.strip().lower()}::{model.strip()}"
