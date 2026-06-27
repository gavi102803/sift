from sift_backend.runtime.capability_policies import (
    MaxTokenField,
    ReasoningSupport,
    StructuredOutputStrategy,
    TemperaturePolicy,
    ToolCallingSupport,
    VisionSupport,
    resolve_capability_policy,
    select_structured_output_strategy,
)


def test_deepseek_json_schema_resolves_to_json_object_strategy() -> None:
    policy = resolve_capability_policy(
        "deepseek",
        "deepseek-v4-flash",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": {"type": "object"}},
        },
    )

    assert select_structured_output_strategy(policy, {"type": "json_schema"}) == (
        StructuredOutputStrategy.JSON_OBJECT
    )
    assert policy.extensions.thinking == {"type": "enabled"}
    assert policy.reasoning == ReasoningSupport.EXTRA_BODY_THINKING
    assert policy.tool_calling == ToolCallingSupport.BASIC


def test_kimi_policy_omits_temperature_and_enables_thinking() -> None:
    policy = resolve_capability_policy("kimi", "kimi-k2-turbo-preview")

    assert policy.temperature == TemperaturePolicy.OMIT
    assert policy.extensions.thinking == {"type": "enabled"}
    assert policy.reasoning == ReasoningSupport.EXTRA_BODY_THINKING


def test_gemini_policy_uses_native_capability_dimensions() -> None:
    policy = resolve_capability_policy("gemini", "gemini-3.5-flash")

    assert policy.max_token_field == MaxTokenField.PROVIDER_NATIVE
    assert policy.reasoning == ReasoningSupport.NATIVE_THINKING_CONFIG
    assert policy.tool_calling == ToolCallingSupport.PROVIDER_NATIVE
    assert policy.vision == VisionSupport.PROVIDER_NATIVE
    assert policy.sift_default_allowed is True


def test_unknown_custom_endpoint_starts_with_prompt_validate_policy() -> None:
    policy = resolve_capability_policy(
        "custom",
        "local-model",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": {"type": "object"}},
        },
    )

    assert select_structured_output_strategy(policy, {"type": "json_schema"}) == (
        StructuredOutputStrategy.PROMPT_AND_VALIDATE
    )
    assert policy.temperature == TemperaturePolicy.OMIT
    assert policy.tool_calling == ToolCallingSupport.NONE
    assert policy.sift_default_allowed is False
