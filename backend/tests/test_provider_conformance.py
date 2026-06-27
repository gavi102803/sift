import json
from collections.abc import AsyncIterator

import pytest

from sift_backend.runtime.conformance import run_model_driver_conformance
from sift_backend.runtime.types import (
    RuntimeModelCompleted,
    RuntimeModelDelta,
    RuntimeModelRequest,
    RuntimeModelResponse,
    RuntimeModelStreamEvent,
)


@pytest.mark.asyncio
async def test_model_driver_conformance_passes_with_complete_stream_and_structured(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIFT_CAPABILITY_PROBE_CACHE_PATH", str(tmp_path / "probes.json"))

    result = await run_model_driver_conformance(
        PassingProvider(),
        provider_name="custom",
        model="local-model",
    )

    assert result.ok is True
    assert result.plain_completion.ok is True
    assert result.streaming.ok is True
    assert result.structured_output.ok is True
    assert result.parameter_policy.ok is True
    assert result.model_list.ok is True
    assert result.selected_structured_output == "jsonSchema"


@pytest.mark.asyncio
async def test_model_driver_conformance_reports_streaming_failure(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIFT_CAPABILITY_PROBE_CACHE_PATH", str(tmp_path / "probes.json"))

    result = await run_model_driver_conformance(
        NoDeltaStreamProvider(),
        provider_name="custom",
        model="local-model",
    )

    assert result.ok is False
    assert result.plain_completion.ok is True
    assert result.structured_output.ok is True
    assert result.streaming.ok is False
    assert result.streaming.message == "stream emitted no text delta"


@pytest.mark.asyncio
async def test_model_driver_conformance_reports_model_list_failure(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIFT_CAPABILITY_PROBE_CACHE_PATH", str(tmp_path / "probes.json"))

    result = await run_model_driver_conformance(
        WrongModelListProvider(),
        provider_name="custom",
        model="local-model",
    )

    assert result.ok is False
    assert result.model_list.ok is False
    assert "was not returned" in result.model_list.message


@pytest.mark.asyncio
async def test_model_driver_conformance_allows_disabled_model_listing(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("SIFT_CAPABILITY_PROBE_CACHE_PATH", str(tmp_path / "probes.json"))

    result = await run_model_driver_conformance(
        EmptyModelListProvider(),
        provider_name="custom",
        model="local-model",
        supports_model_listing=False,
    )

    assert result.ok is True
    assert result.model_list.ok is True
    assert result.model_list.message == "model listing disabled by provider profile"


class PassingProvider:
    provider_name = "custom"

    async def complete(self, request: RuntimeModelRequest) -> RuntimeModelResponse:
        if request.response_format is None:
            return RuntimeModelResponse(
                content="ok",
                provider=self.provider_name,
                model=request.model,
            )
        return RuntimeModelResponse(
            content=json.dumps({"ok": True}),
            provider=self.provider_name,
            model=request.model,
        )

    async def stream(
        self,
        request: RuntimeModelRequest,
    ) -> AsyncIterator[RuntimeModelStreamEvent]:
        yield RuntimeModelDelta("ok")
        yield RuntimeModelCompleted(
            RuntimeModelResponse(
                content="ok",
                provider=self.provider_name,
                model=request.model,
            )
        )

    async def list_models(self) -> list[str]:
        return ["local-model"]


class NoDeltaStreamProvider(PassingProvider):
    async def stream(
        self,
        request: RuntimeModelRequest,
    ) -> AsyncIterator[RuntimeModelStreamEvent]:
        yield RuntimeModelCompleted(
            RuntimeModelResponse(
                content="ok",
                provider=self.provider_name,
                model=request.model,
            )
        )


class WrongModelListProvider(PassingProvider):
    async def list_models(self) -> list[str]:
        return ["other-model"]


class EmptyModelListProvider(PassingProvider):
    async def list_models(self) -> list[str]:
        return []
