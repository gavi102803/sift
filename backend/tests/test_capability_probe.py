import json

import pytest

from sift_backend.runtime.capability_policies import (
    StructuredOutputStrategy,
    resolve_capability_policy,
    select_structured_output_strategy,
)
from sift_backend.runtime.capability_probe import (
    get_cached_structured_output_strategy,
    probe_model_capabilities,
)
from sift_backend.runtime.types import (
    RuntimeModelRequest,
    RuntimeModelResponse,
    SiftRuntimeError,
)


@pytest.mark.asyncio
async def test_capability_probe_caches_json_object_when_json_schema_fails(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIFT_CAPABILITY_PROBE_CACHE_PATH", str(tmp_path / "probes.json"))
    provider = StructuredProbeProvider()

    result = await probe_model_capabilities(
        provider,
        provider_name="deepseek",
        model="deepseek-v4-flash",
    )

    assert result.plain_completion.ok is True
    assert result.structured_output["jsonSchema"].ok is False
    assert result.structured_output["jsonObject"].ok is True
    assert result.selected_structured_output == "jsonObject"
    assert get_cached_structured_output_strategy("deepseek", "deepseek-v4-flash") == "jsonObject"

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


@pytest.mark.asyncio
async def test_custom_policy_uses_cached_probe_strategy(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SIFT_CAPABILITY_PROBE_CACHE_PATH", str(tmp_path / "probes.json"))
    provider = StructuredProbeProvider()

    await probe_model_capabilities(
        provider,
        provider_name="custom",
        model="local-model",
    )

    policy = resolve_capability_policy(
        "custom",
        "local-model",
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "answer", "schema": {"type": "object"}},
        },
    )

    assert select_structured_output_strategy(policy, {"type": "json_schema"}) == (
        StructuredOutputStrategy.JSON_OBJECT
    )


class StructuredProbeProvider:
    provider_name = "deepseek"

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        if request.response_format is None:
            return RuntimeModelResponse(
                content="ok",
                provider=self.provider_name,
                model=request.model,
            )
        if request.structured_output_strategy == "jsonSchema":
            raise SiftRuntimeError(
                "provider_error",
                json.dumps(
                    {
                        "message": "This response_format type is unavailable now",
                        "type": "invalid_request_error",
                        "code": "invalid_request_error",
                    }
                ),
            )
        return RuntimeModelResponse(
            content=json.dumps({"ok": True}),
            provider=self.provider_name,
            model=request.model,
        )

    async def stream(self, request: RuntimeModelRequest):
        raise NotImplementedError

    async def list_models(self) -> list[str]:
        return []
