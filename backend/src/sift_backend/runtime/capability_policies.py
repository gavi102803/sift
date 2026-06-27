from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class TemperaturePolicy(StrEnum):
    ALLOWED = "allowed"
    OMIT = "omit"
    FIXED = "fixed"


class StructuredOutputStrategy(StrEnum):
    JSON_SCHEMA = "jsonSchema"
    JSON_OBJECT = "jsonObject"
    PROMPT_AND_VALIDATE = "promptAndValidate"
    UNSUPPORTED = "unsupported"


class MaxTokenField(StrEnum):
    MAX_TOKENS = "max_tokens"
    MAX_COMPLETION_TOKENS = "max_completion_tokens"
    MAX_OUTPUT_TOKENS = "max_output_tokens"
    NONE = "none"
    PROVIDER_NATIVE = "provider_native"


class ToolCallingSupport(StrEnum):
    NONE = "none"
    BASIC = "basic"
    STREAMING = "streaming"
    PROVIDER_NATIVE = "provider_native"


class StreamingSupport(StrEnum):
    UNSUPPORTED = "unsupported"
    TEXT = "text"
    TEXT_AND_TOOLS = "textAndTools"


class ReasoningSupport(StrEnum):
    UNSUPPORTED = "unsupported"
    TOP_LEVEL_REASONING_EFFORT = "topLevelReasoningEffort"
    EXTRA_BODY_THINKING = "extraBodyThinking"
    EXTRA_BODY_REASONING = "extraBodyReasoning"
    NATIVE_THINKING_CONFIG = "nativeThinkingConfig"
    ADAPTIVE_ONLY = "adaptiveOnly"


class VisionSupport(StrEnum):
    UNSUPPORTED = "unsupported"
    USER_IMAGES = "userImages"
    TOOL_RESULT_IMAGES = "toolResultImages"
    PROVIDER_NATIVE = "providerNative"


@dataclass(frozen=True)
class InternalRequestExtensions:
    thinking: dict[str, Any] | None = None
    reasoning_effort: str | None = None
    reasoning: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedCapabilityPolicy:
    provider_name: str
    model: str
    temperature: TemperaturePolicy = TemperaturePolicy.ALLOWED
    structured_output: tuple[StructuredOutputStrategy, ...] = (
        StructuredOutputStrategy.JSON_SCHEMA,
        StructuredOutputStrategy.JSON_OBJECT,
        StructuredOutputStrategy.PROMPT_AND_VALIDATE,
    )
    max_token_field: MaxTokenField = MaxTokenField.MAX_TOKENS
    tool_calling: ToolCallingSupport = ToolCallingSupport.BASIC
    streaming: StreamingSupport = StreamingSupport.TEXT_AND_TOOLS
    reasoning: ReasoningSupport = ReasoningSupport.UNSUPPORTED
    vision: VisionSupport = VisionSupport.USER_IMAGES
    sift_default_allowed: bool = True
    fixed_temperature: float | None = None
    extensions: InternalRequestExtensions = field(default_factory=InternalRequestExtensions)


def resolve_capability_policy(
    provider_name: str,
    model: str,
    *,
    response_format: dict[str, Any] | None = None,
    strategy_override: str | None = None,
) -> ResolvedCapabilityPolicy:
    provider = provider_name.strip().lower()
    normalized_model = model.strip()
    policy = ResolvedCapabilityPolicy(provider_name=provider, model=normalized_model)

    if provider in {"kimi", "kimi-coding"}:
        policy = _replace(
            policy,
            temperature=TemperaturePolicy.OMIT,
            max_token_field=MaxTokenField.MAX_TOKENS,
            reasoning=ReasoningSupport.EXTRA_BODY_THINKING,
            extensions=_kimi_extensions(),
        )
    elif provider == "deepseek":
        policy = _replace(
            policy,
            structured_output=(
                StructuredOutputStrategy.JSON_OBJECT,
                StructuredOutputStrategy.PROMPT_AND_VALIDATE,
            ),
            reasoning=(
                ReasoningSupport.EXTRA_BODY_THINKING
                if _deepseek_model_supports_thinking(normalized_model)
                else ReasoningSupport.UNSUPPORTED
            ),
            extensions=_deepseek_extensions(normalized_model),
        )
    elif provider == "nous":
        policy = _replace(
            policy,
            reasoning=ReasoningSupport.EXTRA_BODY_REASONING,
            extensions=InternalRequestExtensions(tags=["sift"]),
        )
    elif provider == "anthropic":
        policy = _replace(
            policy,
            structured_output=(StructuredOutputStrategy.PROMPT_AND_VALIDATE,),
            max_token_field=MaxTokenField.MAX_TOKENS,
            tool_calling=ToolCallingSupport.PROVIDER_NATIVE,
            reasoning=ReasoningSupport.ADAPTIVE_ONLY,
            vision=VisionSupport.TOOL_RESULT_IMAGES,
        )
    elif provider == "gemini":
        policy = _replace(
            policy,
            max_token_field=MaxTokenField.PROVIDER_NATIVE,
            tool_calling=ToolCallingSupport.PROVIDER_NATIVE,
            reasoning=ReasoningSupport.NATIVE_THINKING_CONFIG,
            vision=VisionSupport.PROVIDER_NATIVE,
        )
    elif provider == "custom":
        policy = _replace(
            policy,
            temperature=TemperaturePolicy.OMIT,
            structured_output=(
                StructuredOutputStrategy.PROMPT_AND_VALIDATE,
            ),
            tool_calling=ToolCallingSupport.NONE,
            reasoning=ReasoningSupport.UNSUPPORTED,
            vision=VisionSupport.UNSUPPORTED,
            sift_default_allowed=False,
        )

    if strategy_override:
        policy = _replace(
            policy,
            structured_output=(_structured_strategy_from_value(strategy_override),),
        )
    elif response_format is not None:
        cached_strategy = _cached_strategy(provider, normalized_model)
        if cached_strategy is not None:
            policy = _replace(policy, structured_output=(cached_strategy,))

    if response_format is not None:
        requested = _requested_structured_strategy(response_format)
        if strategy_override:
            pass
        elif requested not in policy.structured_output:
            # Runtime should use the cached/probed strategy directly. Until the
            # probe cache lands, choose the best configured non-blind fallback.
            fallback = _first_supported_structured_strategy(policy)
            policy = _replace(policy, structured_output=(fallback,))
        else:
            policy = _replace(policy, structured_output=(requested,))

    return policy


def select_structured_output_strategy(
    policy: ResolvedCapabilityPolicy,
    response_format: dict[str, Any] | None,
) -> StructuredOutputStrategy | None:
    if response_format is None:
        return None
    return _first_supported_structured_strategy(policy)


def _requested_structured_strategy(response_format: dict[str, Any]) -> StructuredOutputStrategy:
    response_type = response_format.get("type")
    if response_type == "json_schema":
        return StructuredOutputStrategy.JSON_SCHEMA
    if response_type == "json_object":
        return StructuredOutputStrategy.JSON_OBJECT
    return StructuredOutputStrategy.PROMPT_AND_VALIDATE


def _structured_strategy_from_value(value: str) -> StructuredOutputStrategy:
    normalized = value.strip()
    for strategy in StructuredOutputStrategy:
        if strategy.value == normalized:
            return strategy
    return StructuredOutputStrategy.PROMPT_AND_VALIDATE


def _cached_strategy(provider_name: str, model: str) -> StructuredOutputStrategy | None:
    try:
        from sift_backend.runtime.capability_probe import get_cached_structured_output_strategy
    except ImportError:
        return None
    cached = get_cached_structured_output_strategy(provider_name, model)
    return _structured_strategy_from_value(cached) if cached else None


def _first_supported_structured_strategy(
    policy: ResolvedCapabilityPolicy,
) -> StructuredOutputStrategy:
    for strategy in policy.structured_output:
        if strategy != StructuredOutputStrategy.UNSUPPORTED:
            return strategy
    return StructuredOutputStrategy.UNSUPPORTED


def _deepseek_extensions(model: str) -> InternalRequestExtensions:
    if not _deepseek_model_supports_thinking(model):
        return InternalRequestExtensions()
    return InternalRequestExtensions(thinking={"type": "enabled"})


def _deepseek_model_supports_thinking(model: str) -> bool:
    normalized = model.strip().lower()
    if not normalized:
        return False
    if normalized.startswith("deepseek-v") and not normalized.startswith("deepseek-v3"):
        return True
    return normalized == "deepseek-reasoner"


def _kimi_extensions() -> InternalRequestExtensions:
    return InternalRequestExtensions(thinking={"type": "enabled"})


def _replace(policy: ResolvedCapabilityPolicy, **changes: Any) -> ResolvedCapabilityPolicy:
    values = {
        "provider_name": policy.provider_name,
        "model": policy.model,
        "temperature": policy.temperature,
        "structured_output": policy.structured_output,
        "max_token_field": policy.max_token_field,
        "tool_calling": policy.tool_calling,
        "streaming": policy.streaming,
        "reasoning": policy.reasoning,
        "vision": policy.vision,
        "sift_default_allowed": policy.sift_default_allowed,
        "fixed_temperature": policy.fixed_temperature,
        "extensions": policy.extensions,
    }
    values.update(changes)
    return ResolvedCapabilityPolicy(**values)
