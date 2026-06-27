from dataclasses import dataclass
from typing import Any

from sift_backend.runtime.capability_policies import resolve_capability_policy
from sift_backend.runtime.capability_probe import (
    CapabilityProbeResult,
    probe_model_capabilities,
)
from sift_backend.runtime.types import (
    RuntimeMessage,
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelProvider,
    RuntimeModelRequest,
)


@dataclass(frozen=True)
class ConformanceCaseResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class ModelDriverConformanceResult:
    provider: str
    model: str
    plain_completion: ConformanceCaseResult
    streaming: ConformanceCaseResult
    structured_output: ConformanceCaseResult
    parameter_policy: ConformanceCaseResult
    model_list: ConformanceCaseResult
    selected_structured_output: str | None

    @property
    def ok(self) -> bool:
        return (
            self.plain_completion.ok
            and self.streaming.ok
            and self.structured_output.ok
            and self.parameter_policy.ok
            and self.model_list.ok
        )


async def run_model_driver_conformance(
    provider: RuntimeModelProvider,
    *,
    provider_name: str,
    model: str,
    supports_model_listing: bool = True,
) -> ModelDriverConformanceResult:
    probe = await probe_model_capabilities(
        provider,
        provider_name=provider_name,
        model=model,
    )
    streaming = await _check_streaming(provider, model)
    policy = _check_parameter_policy(provider_name, model)
    model_list = await _check_model_list(
        provider,
        model,
        supports_model_listing=supports_model_listing,
    )
    return ModelDriverConformanceResult(
        provider=provider_name,
        model=model,
        plain_completion=_from_probe_case(probe),
        streaming=streaming,
        structured_output=_structured_from_probe(probe),
        parameter_policy=policy,
        model_list=model_list,
        selected_structured_output=probe.selected_structured_output,
    )


def model_driver_conformance_artifact(
    result: ModelDriverConformanceResult,
) -> dict[str, Any]:
    return {
        "kind": "sift.modelDriverConformance",
        "provider": result.provider,
        "model": result.model,
        "ok": result.ok,
        "selectedStructuredOutput": result.selected_structured_output,
        "cases": {
            "plainCompletion": _case_artifact(result.plain_completion),
            "streaming": _case_artifact(result.streaming),
            "structuredOutput": _case_artifact(result.structured_output),
            "parameterPolicy": _case_artifact(result.parameter_policy),
            "modelList": _case_artifact(result.model_list),
        },
    }


def _case_artifact(result: ConformanceCaseResult) -> dict[str, Any]:
    return {"ok": result.ok, "message": result.message}


def _from_probe_case(probe: CapabilityProbeResult) -> ConformanceCaseResult:
    return ConformanceCaseResult(
        ok=probe.plain_completion.ok,
        message=probe.plain_completion.message,
    )


def _structured_from_probe(probe: CapabilityProbeResult) -> ConformanceCaseResult:
    if probe.selected_structured_output:
        return ConformanceCaseResult(
            ok=True,
            message=f"structured output selected: {probe.selected_structured_output}",
        )
    messages = [
        f"{strategy}: {result.message}"
        for strategy, result in probe.structured_output.items()
        if not result.ok
    ]
    return ConformanceCaseResult(
        ok=False,
        message="; ".join(messages) or "structured output unavailable",
    )


async def _check_streaming(
    provider: RuntimeModelProvider,
    model: str,
) -> ConformanceCaseResult:
    try:
        saw_delta = False
        saw_completed = False
        async for event in provider.stream(
            RuntimeModelRequest(
                model=model,
                messages=(RuntimeMessage(role="user", content="Reply with exactly: ok"),),
            )
        ):
            if isinstance(event, RuntimeModelDelta) and event.content:
                saw_delta = True
            if isinstance(event, RuntimeModelCompleted):
                saw_completed = True
    except Exception as error:
        return ConformanceCaseResult(ok=False, message=str(error))
    if not saw_delta:
        return ConformanceCaseResult(ok=False, message="stream emitted no text delta")
    if not saw_completed:
        return ConformanceCaseResult(ok=False, message="stream emitted no completed event")
    return ConformanceCaseResult(ok=True, message="streaming responded")


def _check_parameter_policy(provider_name: str, model: str) -> ConformanceCaseResult:
    try:
        policy = resolve_capability_policy(provider_name, model)
    except Exception as error:
        return ConformanceCaseResult(ok=False, message=str(error))
    return ConformanceCaseResult(
        ok=True,
        message=(
            f"temperature={policy.temperature}; "
            f"structured={','.join(strategy.value for strategy in policy.structured_output)}; "
            f"streaming={policy.streaming}; "
            f"tool_calling={policy.tool_calling}; "
            f"default_allowed={policy.sift_default_allowed}"
        ),
    )


async def _check_model_list(
    provider: RuntimeModelProvider,
    model: str,
    *,
    supports_model_listing: bool,
) -> ConformanceCaseResult:
    if not supports_model_listing:
        return ConformanceCaseResult(ok=True, message="model listing disabled by provider profile")
    try:
        models = await provider.list_models()
    except Exception as error:
        return ConformanceCaseResult(ok=False, message=str(error))
    if not models:
        return ConformanceCaseResult(ok=False, message="provider returned no models")
    if model not in models:
        return ConformanceCaseResult(
            ok=False,
            message=f"configured model {model!r} was not returned by model list",
        )
    return ConformanceCaseResult(ok=True, message="model list contains configured model")
