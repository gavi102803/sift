from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

MAX_WEB_SEARCH_QUERY_CHARS = 500
MAX_WEB_EXTRACT_URL_CHARS = 4_096


@dataclass(frozen=True)
class ToolContract:
    """Provider-neutral, immutable contract for one model-callable tool."""

    name: str
    provider_name: str
    aliases: tuple[str, ...]
    description: str
    input_schema: dict[str, Any]
    risk_level: str

    def snapshot(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "providerName": self.provider_name,
            "aliases": list(self.aliases),
            "description": self.description,
            "inputSchema": self.input_schema,
            "riskLevel": self.risk_level,
        }


WEB_SEARCH_TOOL_CONTRACT = ToolContract(
    name="web.search",
    provider_name="web_search",
    aliases=("web_search",),
    description=(
        "Search the public web for current, official, or source-backed information "
        "related to the user's request."
    ),
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["query"],
        "properties": {
            "query": {
                "type": "string",
                "description": "A concise web search query.",
                "maxLength": MAX_WEB_SEARCH_QUERY_CHARS,
            },
            "maxResults": {"type": "integer", "minimum": 1, "maximum": 5},
        },
    },
    risk_level="network-read",
)

WEB_EXTRACT_TOOL_CONTRACT = ToolContract(
    name="web.extract",
    provider_name="web_extract",
    aliases=("web_extract",),
    description="Extract readable text from a specific public HTTPS page.",
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["url"],
        "properties": {
            "url": {
                "type": "string",
                "description": "The public HTTPS page URL to extract.",
                "maxLength": MAX_WEB_EXTRACT_URL_CHARS,
            }
        },
    },
    risk_level="network-read",
)

WEB_TOOL_CONTRACTS = (
    WEB_SEARCH_TOOL_CONTRACT,
    WEB_EXTRACT_TOOL_CONTRACT,
)

_CONTRACTS_BY_NAME = {contract.name: contract for contract in WEB_TOOL_CONTRACTS}
_CANONICAL_NAMES = {
    alias.strip().lower(): contract.name
    for contract in WEB_TOOL_CONTRACTS
    for alias in (contract.name, contract.provider_name, *contract.aliases)
}


def canonical_tool_name(name: str) -> str:
    normalized = name.strip().lower()
    return _CANONICAL_NAMES.get(normalized, normalized)


def tool_contract(name: str) -> ToolContract:
    canonical = canonical_tool_name(name)
    try:
        return _CONTRACTS_BY_NAME[canonical]
    except KeyError as error:
        raise ValueError(f"Unknown tool contract: {name}") from error


def tool_contract_hash(allowed_tools: tuple[str, ...] | frozenset[str]) -> str:
    contracts = [tool_contract(name).snapshot() for name in sorted(allowed_tools)]
    encoded = json.dumps(
        contracts,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"
