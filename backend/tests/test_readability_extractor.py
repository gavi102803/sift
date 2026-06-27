import httpx
import pytest

from sift_backend.runtime.research_stack import (
    ReadabilityExtractorLimits,
    SiftReadabilityExtractProvider,
)
from sift_backend.runtime.types import SiftRuntimeError


@pytest.mark.asyncio
async def test_readability_extractor_extracts_basic_html_without_scripts() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            html="""
            <html>
              <head><title>Readable Page</title><script>secret()</script></head>
              <body><article><h1>Hello</h1><p>Useful text.</p></article></body>
            </html>
            """,
            request=request,
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://example.com",
    )
    extractor = SiftReadabilityExtractProvider(
        resolver=lambda host: ["93.184.216.34"],
        client=client,
    )

    documents = await extractor.extract(["https://example.com/page"])

    assert documents[0].url == "https://example.com/page"
    assert documents[0].title == "Readable Page"
    assert "Hello Useful text." in documents[0].content
    assert "secret" not in documents[0].content
    await client.aclose()


@pytest.mark.asyncio
async def test_readability_extractor_blocks_localhost() -> None:
    extractor = SiftReadabilityExtractProvider()

    with pytest.raises(SiftRuntimeError, match="blocked"):
        await extractor.extract(["http://localhost/page"])


@pytest.mark.asyncio
async def test_readability_extractor_blocks_private_dns_resolution() -> None:
    extractor = SiftReadabilityExtractProvider(resolver=lambda host: ["10.0.0.2"])

    with pytest.raises(SiftRuntimeError, match="blocked"):
        await extractor.extract(["https://example.com/page"])


@pytest.mark.asyncio
async def test_readability_extractor_revalidates_redirect_targets() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://localhost/private"},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extractor = SiftReadabilityExtractProvider(
        resolver=lambda host: ["93.184.216.34"] if host == "example.com" else ["127.0.0.1"],
        client=client,
    )

    with pytest.raises(SiftRuntimeError, match="blocked"):
        await extractor.extract(["https://example.com/page"])
    await client.aclose()


@pytest.mark.asyncio
async def test_readability_extractor_blocks_unsafe_content_type() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/octet-stream"},
            content=b"binary",
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extractor = SiftReadabilityExtractProvider(
        resolver=lambda host: ["93.184.216.34"],
        client=client,
    )

    with pytest.raises(SiftRuntimeError, match="textual page content"):
        await extractor.extract(["https://example.com/file"])
    await client.aclose()


@pytest.mark.asyncio
async def test_readability_extractor_blocks_oversized_body() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"x" * 20,
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    extractor = SiftReadabilityExtractProvider(
        limits=ReadabilityExtractorLimits(max_body_bytes=10),
        resolver=lambda host: ["93.184.216.34"],
        client=client,
    )

    with pytest.raises(SiftRuntimeError, match="too large"):
        await extractor.extract(["https://example.com/large"])
    await client.aclose()
