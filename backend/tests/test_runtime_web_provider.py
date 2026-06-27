import pytest

from sift_backend.runtime.tools import (
    DDGSWebProvider,
    DisabledWebProvider,
    ExaWebProvider,
    FirecrawlWebProvider,
    RuntimeCitation,
    RuntimeExtractedDocument,
    RuntimeWebProvider,
    TavilyWebProvider,
    build_runtime_tool_registry,
    build_web_provider_registry,
)
from sift_backend.runtime.types import SiftRuntimeError


def test_web_provider_registry_creates_registered_provider() -> None:
    registry = build_web_provider_registry(tavily_api_key="tavily-key")

    provider = registry.create("tavily")

    assert isinstance(provider, TavilyWebProvider)
    assert provider.is_available() is True
    assert registry.available_names() == [
        "brave-free",
        "ddgs",
        "disabled",
        "exa",
        "firecrawl",
        "tavily",
        "xai",
    ]


@pytest.mark.asyncio
async def test_ddgs_provider_searches_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    def search(query: str, max_results: int) -> list[RuntimeCitation]:
        assert query == "agent runtime"
        assert max_results == 5
        return [
            RuntimeCitation(
                title="Agent Runtime",
                url="https://example.com/runtime",
                snippet="Runtime result",
                position=1,
            )
        ]

    monkeypatch.setattr("sift_backend.runtime.tools._run_ddgs_search", search)
    monkeypatch.setattr(DDGSWebProvider, "is_available", lambda self: True)

    provider = DDGSWebProvider()

    assert await provider.search("agent runtime") == [
        RuntimeCitation(
            title="Agent Runtime",
            url="https://example.com/runtime",
            snippet="Runtime result",
            position=1,
        )
    ]


def test_web_provider_registry_rejects_unknown_provider() -> None:
    registry = build_web_provider_registry()

    with pytest.raises(SiftRuntimeError, match="not registered"):
        registry.create("parallel")


@pytest.mark.asyncio
async def test_exa_provider_normalizes_search_and_extract(monkeypatch: pytest.MonkeyPatch) -> None:
    async def request(path: str, payload: dict) -> dict:
        if path == "/search":
            return {
                "results": [
                    {
                        "title": "Runtime",
                        "url": "https://example.com/runtime",
                        "highlights": ["coordinates model and tools"],
                    }
                ]
            }
        assert path == "/contents"
        assert payload["urls"] == ["https://example.com/runtime"]
        return {
            "results": [
                {
                    "title": "Runtime",
                    "url": "https://example.com/runtime",
                    "text": "Extracted content",
                }
            ]
        }

    provider = ExaWebProvider(api_key="exa-key")
    monkeypatch.setattr(provider, "_request", request)

    results = await provider.search("agent runtime")
    documents = await provider.extract(["https://example.com/runtime"])

    assert results[0].snippet == "coordinates model and tools"
    assert documents[0].content == "Extracted content"


@pytest.mark.asyncio
async def test_firecrawl_provider_normalizes_search_and_extract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def request(path: str, payload: dict) -> dict:
        if path == "/v1/search":
            return {
                "data": [
                    {
                        "title": "Runtime",
                        "url": "https://example.com/runtime",
                        "description": "Search result",
                    }
                ]
            }
        assert path == "/v1/scrape"
        return {
            "data": {
                "metadata": {"title": "Runtime"},
                "markdown": "Markdown content",
                "html": "<p>Markdown content</p>",
            }
        }

    provider = FirecrawlWebProvider(api_key="firecrawl-key")
    monkeypatch.setattr(provider, "_request", request)

    results = await provider.search("agent runtime")
    documents = await provider.extract(["https://example.com/runtime"])

    assert results[0].title == "Runtime"
    assert documents[0].content == "Markdown content"


@pytest.mark.asyncio
async def test_disabled_web_provider_returns_empty_results() -> None:
    provider = DisabledWebProvider()

    assert await provider.search("RAG") == []
    assert await provider.extract(["https://example.com"]) == []


@pytest.mark.asyncio
async def test_tavily_provider_normalizes_search_results(monkeypatch: pytest.MonkeyPatch) -> None:
    async def request(path: str, payload: dict) -> dict:
        assert path == "/search"
        assert payload["api_key"] == "tavily-key"
        assert payload["query"] == "agent runtime"
        return {
            "results": [
                {
                    "title": "Agent Runtime",
                    "url": "https://example.com/runtime",
                    "content": "A runtime coordinates model and tools.",
                },
                {"title": "Missing URL"},
            ]
        }

    provider = TavilyWebProvider(api_key="tavily-key")
    monkeypatch.setattr(provider, "_request", request)

    results = await provider.search("agent runtime")

    assert len(results) == 1
    assert results[0].title == "Agent Runtime"
    assert results[0].url == "https://example.com/runtime"
    assert results[0].snippet == "A runtime coordinates model and tools."
    assert results[0].position == 1


@pytest.mark.asyncio
async def test_tavily_provider_normalizes_extract_results(monkeypatch: pytest.MonkeyPatch) -> None:
    async def request(path: str, payload: dict) -> dict:
        assert path == "/extract"
        assert payload["api_key"] == "tavily-key"
        assert payload["urls"] == ["https://example.com/runtime"]
        return {
            "results": [
                {
                    "url": "https://example.com/runtime",
                    "title": "Agent Runtime",
                    "content": "Clean content",
                    "raw_content": "<p>Clean content</p>",
                }
            ]
        }

    provider = TavilyWebProvider(api_key="tavily-key")
    monkeypatch.setattr(provider, "_request", request)

    documents = await provider.extract(["https://example.com/runtime"])

    assert len(documents) == 1
    assert documents[0].title == "Agent Runtime"
    assert documents[0].content == "Clean content"
    assert documents[0].raw_content == "<p>Clean content</p>"


@pytest.mark.asyncio
async def test_tavily_provider_requires_api_key() -> None:
    provider = TavilyWebProvider(api_key="")

    with pytest.raises(SiftRuntimeError, match="not configured"):
        await provider.search("RAG")


@pytest.mark.asyncio
async def test_runtime_tool_registry_dispatches_web_tools() -> None:
    provider = RecordingWebProvider()
    registry = build_runtime_tool_registry(provider)

    search_results = await registry.dispatch("web.search", {"query": "agent runtime"})
    extracted = await registry.dispatch(
        "web.extract",
        {"urls": ["https://example.com/runtime"]},
    )

    assert registry.definitions()[0].name == "web.extract"
    assert registry.definitions()[1].name == "web.search"
    assert search_results == [
        RuntimeCitation(
            title="Agent Runtime",
            url="https://example.com/runtime",
            snippet="Runtime result",
        )
    ]
    assert extracted == [
        RuntimeExtractedDocument(
            url="https://example.com/runtime",
            title="Agent Runtime",
            content="Extracted runtime content",
        )
    ]
    assert provider.queries == ["agent runtime"]
    assert provider.extracted_urls == [["https://example.com/runtime"]]


@pytest.mark.asyncio
async def test_runtime_tool_registry_can_split_search_and_extract_providers() -> None:
    search_provider = RecordingWebProvider()
    extract_provider = RecordingWebProvider()
    registry = build_runtime_tool_registry(search_provider, extract_provider=extract_provider)

    await registry.dispatch("web.search", {"query": "agent runtime"})
    await registry.dispatch("web.extract", {"urls": ["https://example.com/runtime"]})

    assert search_provider.queries == ["agent runtime"]
    assert search_provider.extracted_urls == []
    assert extract_provider.queries == []
    assert extract_provider.extracted_urls == [["https://example.com/runtime"]]


@pytest.mark.asyncio
async def test_runtime_tool_registry_rejects_unregistered_tools() -> None:
    registry = build_runtime_tool_registry(DisabledWebProvider())

    with pytest.raises(SiftRuntimeError, match="not registered"):
        await registry.dispatch("memory.write", {})


class RecordingWebProvider(RuntimeWebProvider):
    name = "recording"
    display_name = "Recording"

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.extracted_urls: list[list[str]] = []

    def is_available(self) -> bool:
        return True

    async def search(self, query: str) -> list[RuntimeCitation]:
        self.queries.append(query)
        return [
            RuntimeCitation(
                title="Agent Runtime",
                url="https://example.com/runtime",
                snippet="Runtime result",
            )
        ]

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        self.extracted_urls.append(urls)
        return [
            RuntimeExtractedDocument(
                url=urls[0],
                title="Agent Runtime",
                content="Extracted runtime content",
            )
        ]
