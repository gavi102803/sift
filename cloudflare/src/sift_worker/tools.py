from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sift_worker.agent_core import AgentControlError
from sift_worker.tool_contracts import (
    WEB_EXTRACT_TOOL_CONTRACT,
    WEB_SEARCH_TOOL_CONTRACT,
)
from sift_worker.web_search import WorkerWebSearchClient

ToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]
@dataclass(frozen=True)
class ToolDefinition:
    name: str
    aliases: tuple[str, ...]
    description: str
    input_schema: dict[str, Any]
    risk_level: str
    timeout_seconds: float
    handler: ToolHandler


class ToolRegistry:
    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}
        self._aliases: dict[str, str] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions or definition.name in self._aliases:
            raise ValueError(f"Tool already registered: {definition.name}")
        for alias in definition.aliases:
            if alias in self._definitions or alias in self._aliases:
                raise ValueError(f"Tool alias already registered: {alias}")
        self._definitions[definition.name] = definition
        for alias in definition.aliases:
            self._aliases[alias] = definition.name

    def resolve(self, name: str) -> ToolDefinition:
        canonical = self._aliases.get(name, name)
        definition = self._definitions.get(canonical)
        if definition is None:
            raise AgentControlError(
                "tool_not_registered",
                f"The runtime has no registered tool named {name}.",
            )
        return definition

    async def execute(self, name: str, arguments: dict[str, Any]) -> tuple[str, Any]:
        definition = self.resolve(name)
        _validate_arguments(definition, arguments)
        try:
            result = await asyncio.wait_for(
                definition.handler(arguments),
                timeout=definition.timeout_seconds,
            )
        except TimeoutError as error:
            raise AgentControlError(
                "tool_timeout",
                f"Tool {definition.name} exceeded its execution timeout.",
            ) from error
        return definition.name, result


def web_tool_registry(
    client: WorkerWebSearchClient,
    *,
    search_timeout_seconds: float = 12,
) -> ToolRegistry:
    registry = ToolRegistry()

    async def search(arguments: dict[str, Any]) -> Any:
        query = str(arguments["query"])
        if "maxResults" in arguments:
            return await client.search(
                query,
                max_results=int(arguments["maxResults"]),
            )
        return await client.search(query)

    async def extract(arguments: dict[str, Any]) -> Any:
        return await client.extract(str(arguments["url"]))

    registry.register(
        ToolDefinition(
            name=WEB_SEARCH_TOOL_CONTRACT.name,
            aliases=WEB_SEARCH_TOOL_CONTRACT.aliases,
            description=WEB_SEARCH_TOOL_CONTRACT.description,
            input_schema=WEB_SEARCH_TOOL_CONTRACT.input_schema,
            risk_level=WEB_SEARCH_TOOL_CONTRACT.risk_level,
            timeout_seconds=search_timeout_seconds,
            handler=search,
        )
    )
    registry.register(
        ToolDefinition(
            name=WEB_EXTRACT_TOOL_CONTRACT.name,
            aliases=WEB_EXTRACT_TOOL_CONTRACT.aliases,
            description=WEB_EXTRACT_TOOL_CONTRACT.description,
            input_schema=WEB_EXTRACT_TOOL_CONTRACT.input_schema,
            risk_level=WEB_EXTRACT_TOOL_CONTRACT.risk_level,
            timeout_seconds=10,
            handler=extract,
        )
    )
    return registry


def _validate_arguments(definition: ToolDefinition, arguments: dict[str, Any]) -> None:
    schema = definition.input_schema
    properties = schema.get("properties")
    allowed = set(properties) if isinstance(properties, dict) else set()
    required = schema.get("required")
    for key in required if isinstance(required, list) else []:
        if key not in arguments:
            raise _invalid_arguments(definition.name)
    if schema.get("additionalProperties") is False and set(arguments) - allowed:
        raise _invalid_arguments(definition.name)
    for key, value in arguments.items():
        field = properties.get(key) if isinstance(properties, dict) else None
        expected = field.get("type") if isinstance(field, dict) else None
        if expected == "string" and (not isinstance(value, str) or not value.strip()):
            raise _invalid_arguments(definition.name)
        if (
            expected == "string"
            and isinstance(value, str)
            and len(value) > int(field.get("maxLength", len(value)))
        ):
            raise _invalid_arguments(definition.name)
        if expected == "integer" and (
            not isinstance(value, int) or isinstance(value, bool)
        ):
            raise _invalid_arguments(definition.name)
        if isinstance(field, dict) and isinstance(value, int):
            if value < int(field.get("minimum", value)):
                raise _invalid_arguments(definition.name)
            if value > int(field.get("maximum", value)):
                raise _invalid_arguments(definition.name)


def _invalid_arguments(name: str) -> AgentControlError:
    return AgentControlError(
        "tool_invalid_arguments",
        f"Tool {name} received invalid arguments.",
    )
