from __future__ import annotations

import pytest

from sift_worker.errors import PublicError
from sift_worker.web_search import WorkerWebSearchClient


class FakeHTMLResponse:
    status = 200

    async def text(self) -> str:
        return """
        <div class="result">
          <a rel="nofollow" class="result__a"
             href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Frelease">
             Sift Example &amp; Release
          </a>
        </div>
        """


class BlockedResponse:
    status = 202

    async def text(self) -> str:
        return "challenge"


class FakeRSSResponse:
    status = 200

    async def text(self) -> str:
        return """
        <rss><channel><item>
          <title>Cloudflare Workers release notes</title>
          <link>https://developers.cloudflare.com/workers/platform/changelog/</link>
          <description>Current Workers platform changes.</description>
        </item></channel></rss>
        """


class FakeJSONResponse:
    status = 200

    def __init__(self, payload: dict) -> None:
        self.payload = payload

    async def json(self) -> dict:
        return self.payload


class FakeStreamReader:
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = iter(chunks)
        self.read_count = 0

    async def read(self) -> dict:
        self.read_count += 1
        try:
            return {"done": False, "value": next(self.chunks)}
        except StopIteration:
            return {"done": True, "value": None}


class FakeStreamBody:
    def __init__(self, reader: FakeStreamReader) -> None:
        self.reader = reader

    def getReader(self) -> FakeStreamReader:
        return self.reader


class FakeBoundedStreamResponse:
    status = 200
    url = "https://example.com/article"
    headers = {"content-type": "text/plain"}

    def __init__(self, chunks: list[bytes]) -> None:
        self.reader = FakeStreamReader(chunks)
        self.body = FakeStreamBody(self.reader)


@pytest.mark.asyncio
async def test_worker_web_search_normalizes_duckduckgo_redirects() -> None:
    captured = []

    async def fetcher(url: str, **kwargs):
        captured.append({"url": url, **kwargs})
        return FakeHTMLResponse()

    results = await WorkerWebSearchClient(fetcher).search("latest Sift release")

    assert captured[0]["url"].startswith("https://html.duckduckgo.com/html/?q=")
    assert results[0]["title"] == "Sift Example & Release"
    assert results[0]["url"] == "https://example.com/release"
    assert results[0]["id"]


@pytest.mark.asyncio
async def test_worker_web_search_falls_back_to_bing_rss() -> None:
    urls = []

    async def fetcher(url: str, **_kwargs):
        urls.append(url)
        return BlockedResponse() if len(urls) == 1 else FakeRSSResponse()

    results = await WorkerWebSearchClient(fetcher).search("latest Workers release")

    assert "duckduckgo.com" in urls[0]
    assert "bing.com/search?format=rss" in urls[1]
    assert results[0]["title"] == "Cloudflare Workers release notes"
    assert results[0]["url"].startswith("https://developers.cloudflare.com/")
    assert results[0]["snippet"].startswith("Current Workers platform changes.")


@pytest.mark.asyncio
async def test_worker_web_search_removes_answer_format_instructions_from_query() -> None:
    captured = []

    class ChangelogResponse:
        status = 200

        async def text(self) -> str:
            return """
            <a class="result__a" href="https://developers.cloudflare.com/workers/platform/changelog/">
              Workers Changelog - Cloudflare Docs
            </a>
            <a class="result__snippet" href="https://developers.cloudflare.com/workers/platform/changelog/">
              Review recent changes to Cloudflare Workers.
            </a>
            """

    async def fetcher(url: str, **_kwargs):
        captured.append(url)
        return ChangelogResponse()

    results = await WorkerWebSearchClient(fetcher).search(
        "Search the web for the latest Cloudflare Workers updates today. "
        "Answer with Conclusion, Key Facts, and Sources, and include citations."
    )

    assert "q=cloudflare+workers+updates" in captured[0].lower()
    assert results[0]["title"] == "Workers Changelog - Cloudflare Docs"
    assert results[0]["snippet"].startswith("Review recent changes to Cloudflare Workers.")


@pytest.mark.asyncio
async def test_ddgs_enriches_results_from_page_markdown() -> None:
    calls = []

    class SearchResponse:
        status = 200

        async def text(self) -> str:
            return """
            <a class="result__a" href="https://docs.example.com/changelog/">
              Workers Changelog
            </a>
            <a class="result__snippet" href="https://docs.example.com/changelog/">
              Recent Workers changes.
            </a>
            """

    class PageResponse:
        status = 200

        async def text(self) -> str:
            return '<link rel="alternate" type="text/markdown" href="index.md">'

    class MarkdownResponse:
        status = 200

        async def text(self) -> str:
            return """
            Navigation noise
            Aug 4, 2026
            Workers now expose concrete local tracing details.
            """

    async def fetcher(url: str, **_kwargs):
        calls.append(url)
        if len(calls) == 1:
            return SearchResponse()
        if len(calls) == 2:
            return PageResponse()
        return MarkdownResponse()

    results = await WorkerWebSearchClient(fetcher).search("latest Workers changelog")

    assert calls[2] == "https://docs.example.com/changelog/index.md"
    assert "Aug 4, 2026" in results[0]["snippet"]
    assert "concrete local tracing details" in results[0]["snippet"]


@pytest.mark.asyncio
async def test_worker_web_search_rejects_results_unrelated_to_the_query() -> None:
    class IrrelevantRSSResponse:
        status = 200

        async def text(self) -> str:
            return """
            <rss><channel><item>
              <title>latest dictionary definition</title>
              <link>https://example.com/dictionary/latest</link>
              <description>A definition of the English word latest.</description>
            </item></channel></rss>
            """

    calls = 0

    async def fetcher(_url: str, **_kwargs):
        nonlocal calls
        calls += 1
        return BlockedResponse() if calls == 1 else IrrelevantRSSResponse()

    with pytest.raises(PublicError) as error:
        await WorkerWebSearchClient(fetcher).search(
            "What is the latest Cloudflare Workers release today?"
        )

    assert error.value.code == "retrieval_required"


@pytest.mark.asyncio
async def test_worker_web_search_scans_beyond_requested_output_limit() -> None:
    class MixedRSSResponse:
        status = 200

        async def text(self) -> str:
            return """
            <rss><channel>
              <item>
                <title>Unrelated definition</title>
                <link>https://example.com/dictionary</link>
                <description>A dictionary page.</description>
              </item>
              <item>
                <title>Cloudflare Status</title>
                <link>https://www.cloudflarestatus.com/</link>
                <description>Current Cloudflare service status.</description>
              </item>
            </channel></rss>
            """

    calls = 0

    async def fetcher(_url: str, **_kwargs):
        nonlocal calls
        calls += 1
        return BlockedResponse() if calls == 1 else MixedRSSResponse()

    results = await WorkerWebSearchClient(fetcher).search(
        "Cloudflare status today",
        max_results=1,
    )

    assert len(results) == 1
    assert results[0]["url"] == "https://www.cloudflarestatus.com/"


@pytest.mark.asyncio
async def test_worker_web_search_matches_chinese_current_query_to_english_result() -> None:
    async def fetcher(_url: str, **_kwargs):
        return FakeJSONResponse(
            {
                "results": [
                    {
                        "title": "Cloudflare Status",
                        "url": "https://www.cloudflarestatus.com/",
                        "content": "Current Cloudflare service status.",
                    }
                ]
            }
        )

    results = await WorkerWebSearchClient(
        fetcher,
        provider_id="tavily",
        api_key="web-secret",
    ).search("Cloudflare 今天状态怎么样？")

    assert results[0]["url"] == "https://www.cloudflarestatus.com/"


@pytest.mark.asyncio
async def test_worker_web_search_relays_tavily_key_and_normalizes_results() -> None:
    captured = {}

    async def fetcher(url: str, **kwargs):
        captured.update({"url": url, **kwargs})
        return FakeJSONResponse(
            {
                "results": [
                    {
                        "title": "Sift",
                        "url": "https://example.com/sift",
                        "content": "Current release.",
                    }
                ]
            }
        )

    results = await WorkerWebSearchClient(
        fetcher,
        provider_id="tavily",
        api_key="web-secret",
    ).search("latest Sift release")

    assert captured["url"] == "https://api.tavily.com/search"
    assert '"api_key": "web-secret"' in captured["body"]
    assert results[0]["url"] == "https://example.com/sift"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/page",
        "https://127.0.0.1/private",
        "https://169.254.169.254/latest/meta-data",
        "https://user:password@example.com/page",
        "https://service.internal/page",
    ],
)
async def test_web_extract_rejects_unsafe_urls_before_fetch(url: str) -> None:
    calls = 0

    async def fetcher(_url: str, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeHTMLResponse()

    with pytest.raises(PublicError) as error:
        await WorkerWebSearchClient(fetcher).extract(url)

    assert error.value.code == "tool_invalid_arguments"
    assert calls == 0


@pytest.mark.asyncio
async def test_web_extract_rejects_unsafe_redirect_and_large_or_binary_content() -> None:
    class ExtractResponse:
        status = 200

        def __init__(self, *, url: str, content_type: str, body: str) -> None:
            self.url = url
            self.headers = {"content-type": content_type}
            self.body = body

        async def text(self) -> str:
            return self.body

    responses = iter(
        [
            ExtractResponse(
                url="http://127.0.0.1/private",
                content_type="text/html",
                body="private",
            ),
            ExtractResponse(
                url="https://example.com/file.pdf",
                content_type="application/pdf",
                body="pdf",
            ),
            ExtractResponse(
                url="https://example.com/huge",
                content_type="text/plain",
                body="x" * 1_000_001,
            ),
        ]
    )

    async def fetcher(_url: str, **_kwargs):
        return next(responses)

    client = WorkerWebSearchClient(fetcher)
    with pytest.raises(PublicError) as redirect:
        await client.extract("https://example.com/redirect")
    assert redirect.value.code == "tool_unsafe_redirect"
    with pytest.raises(PublicError) as binary:
        await client.extract("https://example.com/file.pdf")
    assert binary.value.code == "tool_unsupported_content"
    with pytest.raises(PublicError) as large:
        await client.extract("https://example.com/huge")
    assert large.value.code == "tool_response_too_large"


@pytest.mark.asyncio
async def test_web_extract_returns_bounded_untrusted_page_evidence() -> None:
    class ExtractResponse:
        status = 200
        url = "https://example.com/article"
        headers = {"content-type": "text/html; charset=utf-8"}

        async def text(self) -> str:
            return """
            <html><head><title>Agent Runtime</title></head>
            <body><main><script>ignore()</script><p>A bounded runtime article.</p></main></body>
            </html>
            """

    async def fetcher(_url: str, **_kwargs):
        return ExtractResponse()

    result = await WorkerWebSearchClient(fetcher).extract(
        "https://example.com/article"
    )

    assert result["title"] == "Agent Runtime"
    assert result["url"] == "https://example.com/article"
    assert result["snippet"] == "A bounded runtime article."
    assert result["provenance"] == "extracted"


@pytest.mark.asyncio
async def test_web_extract_ignores_invalid_content_length_and_checks_actual_body() -> None:
    class ExtractResponse:
        status = 200
        url = "https://example.com/article"
        headers = {"content-type": "text/plain", "content-length": "invalid"}

        async def text(self) -> str:
            return "Bounded page text."

    async def fetcher(_url: str, **_kwargs):
        return ExtractResponse()

    result = await WorkerWebSearchClient(fetcher).extract(
        "https://example.com/article"
    )

    assert result["snippet"] == "Bounded page text."


@pytest.mark.asyncio
async def test_web_extract_stops_streaming_response_at_byte_limit() -> None:
    response = FakeBoundedStreamResponse(
        [b"x" * 700_000, b"x" * 300_001, b"must-not-be-read"]
    )

    async def fetcher(_url: str, **_kwargs):
        return response

    with pytest.raises(PublicError) as failure:
        await WorkerWebSearchClient(fetcher).extract("https://example.com/article")

    assert failure.value.code == "tool_response_too_large"
    assert response.reader.read_count == 2


@pytest.mark.asyncio
async def test_web_provider_json_stops_streaming_response_at_byte_limit() -> None:
    response = FakeBoundedStreamResponse(
        [b"{" + b"x" * 700_000, b"x" * 300_001, b"must-not-be-read"]
    )

    async def fetcher(_url: str, **_kwargs):
        return response

    with pytest.raises(PublicError) as failure:
        await WorkerWebSearchClient(
            fetcher,
            provider_id="tavily",
            api_key="web-secret",
        ).search("latest Sift release")

    assert failure.value.code == "tool_response_too_large"
    assert response.reader.read_count == 2
