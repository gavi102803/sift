import json
from typing import Any

from sift_backend.runtime.capability_policies import (
    ResolvedCapabilityPolicy,
    StructuredOutputStrategy,
    TemperaturePolicy,
    resolve_capability_policy,
    select_structured_output_strategy,
)
from sift_backend.runtime.types import RuntimeModelRequest


def build_chat_completions_payload(
    request: RuntimeModelRequest,
    *,
    provider_name: str,
    base_url: str | None = None,
) -> dict[str, Any]:
    policy = resolve_capability_policy(
        provider_name,
        request.model,
        response_format=request.response_format,
        strategy_override=request.structured_output_strategy,
        base_url=base_url,
    )
    strategy = select_structured_output_strategy(policy, request.response_format)
    messages = [
        {"role": message.role, "content": message.content}
        for message in request.messages
    ]
    if request.response_format and _should_append_schema_instruction(
        request.response_format,
        strategy,
    ):
        messages.append(_prompt_and_validate_instruction(request.response_format))

    payload: dict[str, Any] = {
        "model": request.model,
        "messages": messages,
    }
    if request.temperature is not None and policy.temperature != TemperaturePolicy.OMIT:
        payload["temperature"] = request.temperature
    if request.response_format:
        if strategy == StructuredOutputStrategy.JSON_SCHEMA:
            payload["response_format"] = request.response_format
        elif strategy == StructuredOutputStrategy.JSON_OBJECT:
            payload["response_format"] = {"type": "json_object"}

    _apply_provider_payload_extensions(payload, policy)
    return payload


def _prompt_and_validate_instruction(response_format: dict[str, Any]) -> dict[str, str]:
    schema = response_format.get("json_schema", {}).get("schema")
    schema_payload = schema if isinstance(schema, dict) else response_format
    return {
        "role": "system",
        "content": (
            "Return only valid JSON. Do not wrap the response in markdown fences. "
            "The JSON object must match this exact schema. Include every required key, "
            "use the exact camelCase field names, and do not add extra keys:\n"
            f"{json.dumps(schema_payload, ensure_ascii=False)}"
        ),
    }


def _should_append_schema_instruction(
    response_format: dict[str, Any],
    strategy: StructuredOutputStrategy | None,
) -> bool:
    if strategy == StructuredOutputStrategy.PROMPT_AND_VALIDATE:
        return True
    if strategy != StructuredOutputStrategy.JSON_OBJECT:
        return False
    return isinstance(response_format.get("json_schema", {}).get("schema"), dict)


def _apply_provider_payload_extensions(
    payload: dict[str, Any],
    policy: ResolvedCapabilityPolicy,
) -> None:
    extensions = policy.extensions
    provider = policy.provider_name
    if extensions.thinking:
        payload["thinking"] = extensions.thinking
    if extensions.reasoning_effort:
        payload["reasoning_effort"] = extensions.reasoning_effort
    if extensions.reasoning and provider in {"openrouter", "nous"}:
        payload["reasoning"] = extensions.reasoning
    if extensions.tags and provider == "nous":
        payload["tags"] = extensions.tags
