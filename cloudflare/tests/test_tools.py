from __future__ import annotations

import asyncio

import pytest

from sift_worker.agent_core import AgentControlError
from sift_worker.tool_contracts import (
    WEB_EXTRACT_TOOL_CONTRACT,
    WEB_SEARCH_TOOL_CONTRACT,
    canonical_tool_name,
    tool_contract_hash,
)
from sift_worker.tools import ToolDefinition, ToolRegistry, web_tool_registry


@pytest.mark.asyncio
async def test_tool_registry_resolves_alias_and_validates_arguments() -> None:
    calls = []

    async def handler(arguments):
        calls.append(arguments)
        return {"ok": True}

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.echo",
            aliases=("echo",),
            description="Test echo",
            input_schema={
                "type": "object",
                "additionalProperties": False,
                "required": ["value"],
                "properties": {"value": {"type": "string"}},
            },
            risk_level="none",
            timeout_seconds=1,
            handler=handler,
        )
    )

    canonical, result = await registry.execute("echo", {"value": "hello"})
    assert canonical == "test.echo"
    assert result == {"ok": True}
    assert calls == [{"value": "hello"}]

    with pytest.raises(AgentControlError) as invalid:
        await registry.execute("echo", {"value": "", "unexpected": True})
    assert invalid.value.code == "tool_invalid_arguments"
    with pytest.raises(AgentControlError) as missing:
        await registry.execute("missing", {})
    assert missing.value.code == "tool_not_registered"


@pytest.mark.asyncio
async def test_tool_registry_enforces_tool_timeout() -> None:
    async def blocked(_arguments):
        await asyncio.sleep(1)

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="test.blocked",
            aliases=(),
            description="Blocked test tool",
            input_schema={"type": "object", "properties": {}},
            risk_level="none",
            timeout_seconds=0.01,
            handler=blocked,
        )
    )

    with pytest.raises(AgentControlError) as error:
        await registry.execute("test.blocked", {})
    assert error.value.code == "tool_timeout"


@pytest.mark.asyncio
async def test_web_tool_registry_exposes_search_and_extract_contracts() -> None:
    class FakeWebClient:
        async def search(self, query: str, *, max_results: int):
            return [{"query": query, "limit": max_results}]

        async def extract(self, url: str):
            return {"url": url, "snippet": "page"}

    registry = web_tool_registry(FakeWebClient())

    search_name, search = await registry.execute(
        "web_search", {"query": "Sift runtime", "maxResults": 2}
    )
    extract_name, extract = await registry.execute(
        "web_extract", {"url": "https://example.com/runtime"}
    )
    assert search_name == "web.search"
    assert search == [{"query": "Sift runtime", "limit": 2}]
    assert extract_name == "web.extract"
    assert extract["snippet"] == "page"

    with pytest.raises(AgentControlError) as oversized_query:
        await registry.execute("web_search", {"query": "q" * 501})
    assert oversized_query.value.code == "tool_invalid_arguments"


def test_web_tools_share_one_versioned_contract_source() -> None:
    assert canonical_tool_name("web_search") == WEB_SEARCH_TOOL_CONTRACT.name
    assert canonical_tool_name("web_extract") == WEB_EXTRACT_TOOL_CONTRACT.name
    assert WEB_SEARCH_TOOL_CONTRACT.input_schema["properties"]["query"][
        "maxLength"
    ] == 500
    assert WEB_EXTRACT_TOOL_CONTRACT.input_schema["properties"]["url"][
        "maxLength"
    ] == 4_096
    assert tool_contract_hash(
        (WEB_SEARCH_TOOL_CONTRACT.name, WEB_EXTRACT_TOOL_CONTRACT.name)
    ).startswith("sha256:")
