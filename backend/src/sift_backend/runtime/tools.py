import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from sift_backend.runtime.types import SiftRuntimeError


@dataclass(frozen=True)
class RuntimeCitation:
    title: str
    url: str
    snippet: str = ""
    position: int | None = None


@dataclass(frozen=True)
class RuntimeExtractedDocument:
    url: str
    title: str = ""
    content: str = ""
    raw_content: str = ""


@dataclass(frozen=True)
class WebProviderProfile:
    name: str
    display_name: str
    description: str
    requires_api_key: bool
    supports_search: bool = True
    supports_extract: bool = False
    status: str = "available"
    is_default: bool = False


class RuntimeWebProvider(Protocol):
    """Hermes-style web provider contract trimmed to Sift's needs."""

    name: str
    display_name: str

    def is_available(self) -> bool:
        ...

    async def search(self, query: str) -> list[RuntimeCitation]:
        ...

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        ...


class RuntimeExtractProvider(Protocol):
    name: str

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        ...


@dataclass(frozen=True)
class RuntimeToolDefinition:
    name: str
    toolset: str
    description: str


RuntimeToolHandler = Callable[[dict[str, Any]], Awaitable[Any]]


class RuntimeToolRegistry:
    """Small async tool registry modeled after Hermes Agent's tool dispatch."""

    def __init__(self) -> None:
        self._definitions: dict[str, RuntimeToolDefinition] = {}
        self._handlers: dict[str, RuntimeToolHandler] = {}

    def register(
        self,
        definition: RuntimeToolDefinition,
        handler: RuntimeToolHandler,
    ) -> None:
        normalized = definition.name.strip().lower()
        if not normalized:
            raise ValueError("tool name must not be empty")
        self._definitions[normalized] = definition
        self._handlers[normalized] = handler

    async def dispatch(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        normalized = tool_name.strip().lower()
        handler = self._handlers.get(normalized)
        if handler is None:
            raise SiftRuntimeError(
                "tool_not_registered",
                f"Runtime tool is not registered: {tool_name}.",
            )
        return await handler(arguments)

    def definitions(self) -> list[RuntimeToolDefinition]:
        return [self._definitions[name] for name in sorted(self._definitions)]


def build_runtime_tool_registry(
    web_provider: RuntimeWebProvider,
    *,
    extract_provider: RuntimeExtractProvider | None = None,
) -> RuntimeToolRegistry:
    registry = RuntimeToolRegistry()
    resolved_extract_provider = extract_provider or web_provider

    async def web_search(arguments: dict[str, Any]) -> list[RuntimeCitation]:
        query = arguments.get("query")
        if not isinstance(query, str) or not query.strip():
            raise SiftRuntimeError("tool_invalid_arguments", "web.search requires a query.")
        return await web_provider.search(query)

    async def web_extract(arguments: dict[str, Any]) -> list[RuntimeExtractedDocument]:
        urls = arguments.get("urls")
        if not isinstance(urls, list) or not all(isinstance(url, str) for url in urls):
            raise SiftRuntimeError("tool_invalid_arguments", "web.extract requires URL strings.")
        return await resolved_extract_provider.extract(urls)

    registry.register(
        RuntimeToolDefinition(
            name="web.search",
            toolset="web",
            description="Search the web and return normalized citations.",
        ),
        web_search,
    )
    registry.register(
        RuntimeToolDefinition(
            name="web.extract",
            toolset="web",
            description="Extract readable content from URLs.",
        ),
        web_extract,
    )
    return registry


ProviderFactory = Callable[[], RuntimeWebProvider]


class WebProviderRegistry:
    """Small web-provider registry adapted from Hermes Agent's provider runtime."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory] = {}

    def register(self, provider_name: str, factory: ProviderFactory) -> None:
        normalized = provider_name.strip().lower()
        if not normalized:
            raise ValueError("provider_name must not be empty")
        self._factories[normalized] = factory

    def create(self, provider_name: str) -> RuntimeWebProvider:
        normalized = provider_name.strip().lower()
        factory = self._factories.get(normalized)
        if factory is None:
            raise SiftRuntimeError(
                "tool_not_configured",
                f"Runtime web provider is not registered: {provider_name}.",
            )
        return factory()

    def available_names(self) -> list[str]:
        return sorted(self._factories)


class DisabledWebProvider:
    name = "disabled"
    display_name = "Disabled"

    def is_available(self) -> bool:
        return True

    async def search(self, query: str) -> list[RuntimeCitation]:
        return []

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        return []


class DDGSWebProvider:
    """DuckDuckGo search provider adapted from Hermes' bundled ddgs plugin."""

    name = "ddgs"
    display_name = "DuckDuckGo"

    def __init__(
        self,
        timeout: float = 20,
        max_results: int = 5,
    ) -> None:
        self.timeout = timeout
        self.max_results = max_results

    def is_available(self) -> bool:
        try:
            import ddgs  # noqa: F401
        except ImportError:
            return False
        return True

    async def search(self, query: str) -> list[RuntimeCitation]:
        if not self.is_available():
            raise SiftRuntimeError(
                "tool_not_configured",
                "DuckDuckGo search requires the ddgs package to be installed.",
            )
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_run_ddgs_search, query, self.max_results),
                timeout=self.timeout,
            )
        except TimeoutError as error:
            raise SiftRuntimeError(
                "tool_timeout",
                "DuckDuckGo search timed out.",
            ) from error
        except Exception as error:
            raise SiftRuntimeError("tool_error", f"DuckDuckGo search failed: {error}") from error

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        return []


class TavilyWebProvider:
    """Tavily implementation following Hermes' normalized search/extract shape."""

    name = "tavily"
    display_name = "Tavily"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.tavily.com",
        timeout: float = 20,
        max_results: int = 5,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_results = max_results

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str) -> list[RuntimeCitation]:
        if not self.is_available():
            raise SiftRuntimeError("tool_not_configured", "Tavily API key is not configured.")
        payload = {
            "api_key": self.api_key,
            "query": query,
            "search_depth": "basic",
            "max_results": self.max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        data = await self._request("/search", payload)
        return _normalize_tavily_search(data)

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        if not self.is_available():
            raise SiftRuntimeError("tool_not_configured", "Tavily API key is not configured.")
        if not urls:
            return []
        data = await self._request("/extract", {"api_key": self.api_key, "urls": urls})
        return _normalize_tavily_extract(data)

    async def _request(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.post(path, json=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "tool_error",
                    f"Tavily returned HTTP {error.response.status_code}.",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("tool_timeout", "Tavily request timed out.") from error
            except (httpx.HTTPError, ValueError) as error:
                raise SiftRuntimeError("tool_error", "Tavily request failed.") from error
        if not isinstance(data, dict):
            raise SiftRuntimeError("tool_error", "Tavily response was not an object.")
        return data


class ExaWebProvider:
    name = "exa"
    display_name = "Exa"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.exa.ai",
        timeout: float = 20,
        max_results: int = 5,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_results = max_results

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str) -> list[RuntimeCitation]:
        if not self.is_available():
            raise SiftRuntimeError("tool_not_configured", "Exa API key is not configured.")
        data = await self._request(
            "/search",
            {
                "query": query,
                "numResults": self.max_results,
                "contents": {"highlights": True},
            },
        )
        return _normalize_web_results(data.get("results"), snippet_keys=("highlight", "text"))

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        if not self.is_available():
            raise SiftRuntimeError("tool_not_configured", "Exa API key is not configured.")
        if not urls:
            return []
        data = await self._request("/contents", {"urls": urls, "text": True})
        return _normalize_extract_results(data.get("results"))

    async def _request(self, path: str, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.post(path, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "tool_error",
                    f"Exa returned HTTP {error.response.status_code}.",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("tool_timeout", "Exa request timed out.") from error
            except (httpx.HTTPError, ValueError) as error:
                raise SiftRuntimeError("tool_error", "Exa request failed.") from error
        return data if isinstance(data, dict) else {}


class FirecrawlWebProvider:
    name = "firecrawl"
    display_name = "Firecrawl"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.firecrawl.dev",
        timeout: float = 30,
        max_results: int = 5,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_results = max_results

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str) -> list[RuntimeCitation]:
        if not self.is_available():
            raise SiftRuntimeError("tool_not_configured", "Firecrawl API key is not configured.")
        data = await self._request(
            "/v1/search",
            {
                "query": query,
                "limit": self.max_results,
                "scrapeOptions": {"formats": ["markdown"]},
            },
        )
        return _normalize_web_results(data.get("data"))

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        if not self.is_available():
            raise SiftRuntimeError("tool_not_configured", "Firecrawl API key is not configured.")
        documents: list[RuntimeExtractedDocument] = []
        for url in urls:
            data = await self._request("/v1/scrape", {"url": url, "formats": ["markdown"]})
            payload = data.get("data") if isinstance(data.get("data"), dict) else data
            if not isinstance(payload, dict):
                continue
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            title = metadata.get("title") if isinstance(metadata.get("title"), str) else ""
            markdown = payload.get("markdown")
            html = payload.get("html")
            documents.append(
                RuntimeExtractedDocument(
                    url=url,
                    title=title,
                    content=markdown if isinstance(markdown, str) else "",
                    raw_content=html if isinstance(html, str) else "",
                )
            )
        return documents

    async def _request(self, path: str, payload: dict) -> dict:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.post(path, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "tool_error",
                    f"Firecrawl returned HTTP {error.response.status_code}.",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("tool_timeout", "Firecrawl request timed out.") from error
            except (httpx.HTTPError, ValueError) as error:
                raise SiftRuntimeError("tool_error", "Firecrawl request failed.") from error
        return data if isinstance(data, dict) else {}


class BraveSearchWebProvider:
    name = "brave-free"
    display_name = "Brave Search"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.search.brave.com",
        timeout: float = 15,
        max_results: int = 5,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_results = max_results

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str) -> list[RuntimeCitation]:
        if not self.is_available():
            raise SiftRuntimeError(
                "tool_not_configured",
                "Brave Search API key is not configured.",
            )
        headers = {"X-Subscription-Token": self.api_key, "Accept": "application/json"}
        params = {"q": query, "count": min(max(self.max_results, 1), 20)}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.get("/res/v1/web/search", headers=headers, params=params)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "tool_error",
                    f"Brave Search returned HTTP {error.response.status_code}.",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("tool_timeout", "Brave Search timed out.") from error
            except (httpx.HTTPError, ValueError) as error:
                raise SiftRuntimeError("tool_error", "Brave Search request failed.") from error
        web = data.get("web") if isinstance(data, dict) else {}
        raw_results = web.get("results") if isinstance(web, dict) else []
        return _normalize_web_results(raw_results)

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        return []


class XAIWebProvider:
    name = "xai"
    display_name = "xAI Web Search"

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.x.ai/v1",
        timeout: float = 90,
        max_results: int = 5,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_results = max_results

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def search(self, query: str) -> list[RuntimeCitation]:
        if not self.is_available():
            raise SiftRuntimeError("tool_not_configured", "xAI API key is not configured.")
        prompt = (
            f"Search the web for: {query}\n\n"
            f"Return JSON only: {{\"results\":[{{\"title\":\"...\",\"url\":\"...\","
            f"\"description\":\"...\"}}]}}. Limit to {self.max_results} results."
        )
        payload = {
            "model": "grok-build-0.1",
            "input": [{"role": "user", "content": prompt}],
            "tools": [{"type": "web_search"}],
            "include": ["no_inline_citations"],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout) as client:
            try:
                response = await client.post("/responses", headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as error:
                raise SiftRuntimeError(
                    "tool_error",
                    f"xAI Web Search returned HTTP {error.response.status_code}.",
                ) from error
            except httpx.TimeoutException as error:
                raise SiftRuntimeError("tool_timeout", "xAI Web Search timed out.") from error
            except (httpx.HTTPError, ValueError) as error:
                raise SiftRuntimeError("tool_error", "xAI Web Search request failed.") from error
        return _normalize_xai_search(data)

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        return []


def build_web_provider_registry(
    *,
    tavily_api_key: str = "",
    tavily_base_url: str = "https://api.tavily.com",
) -> WebProviderRegistry:
    registry = WebProviderRegistry()
    registry.register("disabled", DisabledWebProvider)
    registry.register("ddgs", DDGSWebProvider)
    registry.register(
        "tavily",
        lambda: TavilyWebProvider(api_key=tavily_api_key, base_url=tavily_base_url),
    )
    registry.register("exa", lambda: ExaWebProvider(api_key=tavily_api_key))
    registry.register("firecrawl", lambda: FirecrawlWebProvider(api_key=tavily_api_key))
    registry.register("brave-free", lambda: BraveSearchWebProvider(api_key=tavily_api_key))
    registry.register("xai", lambda: XAIWebProvider(api_key=tavily_api_key))
    return registry


def web_provider_profiles() -> list[WebProviderProfile]:
    return [
        WebProviderProfile(
            name="ddgs",
            display_name="DuckDuckGo",
            description="DuckDuckGo search via ddgs; no API key required.",
            requires_api_key=False,
            supports_extract=False,
            is_default=True,
        ),
        WebProviderProfile(
            name="tavily",
            display_name="Tavily",
            description="Search and extraction via Tavily.",
            requires_api_key=True,
            supports_extract=True,
        ),
        WebProviderProfile(
            name="exa",
            display_name="Exa",
            description="Exa web search and content extraction.",
            requires_api_key=True,
            supports_extract=True,
        ),
        WebProviderProfile(
            name="firecrawl",
            display_name="Firecrawl",
            description="Firecrawl search and content extraction.",
            requires_api_key=True,
            supports_extract=True,
        ),
        WebProviderProfile(
            name="brave-free",
            display_name="Brave Search",
            description="Brave Search free tier.",
            requires_api_key=True,
        ),
        WebProviderProfile(
            name="xai",
            display_name="xAI Web Search",
            description="xAI Grok-backed web search.",
            requires_api_key=True,
        ),
        WebProviderProfile(
            name="disabled",
            display_name="Disabled",
            description="Disable runtime web retrieval.",
            requires_api_key=False,
            supports_search=False,
            status="available",
        ),
    ]


def _run_ddgs_search(query: str, max_results: int) -> list[RuntimeCitation]:
    from ddgs import DDGS  # type: ignore

    citations: list[RuntimeCitation] = []
    safe_limit = max(1, max_results)
    with DDGS(timeout=10) as client:
        for index, hit in enumerate(client.text(query, max_results=safe_limit), start=1):
            if index > safe_limit:
                break
            if not isinstance(hit, dict):
                continue
            title = hit.get("title")
            url = hit.get("href") or hit.get("url")
            if not isinstance(title, str) or not isinstance(url, str):
                continue
            body = hit.get("body")
            citations.append(
                RuntimeCitation(
                    title=title,
                    url=url,
                    snippet=body if isinstance(body, str) else "",
                    position=index,
                )
            )
    return citations


def _normalize_tavily_search(data: dict) -> list[RuntimeCitation]:
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        return []
    citations: list[RuntimeCitation] = []
    for index, raw_result in enumerate(raw_results, start=1):
        if not isinstance(raw_result, dict):
            continue
        title = raw_result.get("title")
        url = raw_result.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            continue
        content = raw_result.get("content")
        position = raw_result.get("position")
        citations.append(
            RuntimeCitation(
                title=title,
                url=url,
                snippet=content if isinstance(content, str) else "",
                position=position if isinstance(position, int) else index,
            )
        )
    return citations


def _normalize_tavily_extract(data: dict) -> list[RuntimeExtractedDocument]:
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        return []
    documents: list[RuntimeExtractedDocument] = []
    for raw_result in raw_results:
        if not isinstance(raw_result, dict):
            continue
        url = raw_result.get("url")
        if not isinstance(url, str):
            continue
        title = raw_result.get("title")
        content = raw_result.get("content")
        raw_content = raw_result.get("raw_content")
        documents.append(
            RuntimeExtractedDocument(
                url=url,
                title=title if isinstance(title, str) else "",
                content=content if isinstance(content, str) else "",
                raw_content=raw_content if isinstance(raw_content, str) else "",
            )
        )
    return documents


def _normalize_web_results(
    raw_results: Any,
    *,
    snippet_keys: tuple[str, ...] = ("description", "content", "snippet", "text"),
) -> list[RuntimeCitation]:
    if not isinstance(raw_results, list):
        return []
    citations: list[RuntimeCitation] = []
    for index, raw_result in enumerate(raw_results, start=1):
        if not isinstance(raw_result, dict):
            continue
        title = _first_string(raw_result, ("title", "name"))
        url = _first_string(raw_result, ("url", "link"))
        if not title or not url:
            continue
        snippet = _first_string(raw_result, snippet_keys)
        if not snippet and isinstance(raw_result.get("highlights"), list):
            snippet = " ".join(
                item for item in raw_result["highlights"] if isinstance(item, str)
            )
        citations.append(
            RuntimeCitation(
                title=title,
                url=url,
                snippet=snippet,
                position=index,
            )
        )
    return citations


def _normalize_extract_results(raw_results: Any) -> list[RuntimeExtractedDocument]:
    if not isinstance(raw_results, list):
        return []
    documents: list[RuntimeExtractedDocument] = []
    for raw_result in raw_results:
        if not isinstance(raw_result, dict):
            continue
        url = _first_string(raw_result, ("url", "sourceURL"))
        if not url:
            continue
        title = _first_string(raw_result, ("title",))
        content = _first_string(raw_result, ("text", "content", "markdown"))
        raw_content = _first_string(raw_result, ("raw_content", "html"))
        documents.append(
            RuntimeExtractedDocument(
                url=url,
                title=title,
                content=content,
                raw_content=raw_content,
            )
        )
    return documents


def _normalize_xai_search(data: dict) -> list[RuntimeCitation]:
    text = _xai_output_text(data)
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            parsed = {}
        if isinstance(parsed, dict):
            citations = _normalize_web_results(parsed.get("results"))
            if citations:
                return citations
    citations_raw = data.get("citations")
    return _normalize_web_results(citations_raw, snippet_keys=("snippet", "description"))


def _xai_output_text(data: dict) -> str:
    output = data.get("output")
    if not isinstance(output, list):
        return ""
    parts: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                parts.append(block["text"])
    return "\n".join(parts).strip()


def _first_string(data: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


RuntimeWebSearchTool = RuntimeWebProvider
DisabledWebSearchTool = DisabledWebProvider
DDGSWebSearchTool = DDGSWebProvider
TavilyWebSearchTool = TavilyWebProvider
