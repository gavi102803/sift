from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Protocol
from urllib.parse import urljoin, urlparse

import httpx

from sift_backend.runtime.outbound_safety import (
    AddressResolver,
    extraction_policy,
    resolve_host_addresses,
    validate_outbound_url,
)
from sift_backend.runtime.tools import RuntimeCitation, RuntimeExtractedDocument
from sift_backend.runtime.types import SiftRuntimeError


class RuntimeSearchProvider(Protocol):
    name: str

    async def search(self, query: str) -> list[RuntimeCitation]:
        ...


class RuntimeExtractProvider(Protocol):
    name: str

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        ...


@dataclass(frozen=True)
class ReadabilityExtractorLimits:
    connect_timeout: float = 5
    read_timeout: float = 10
    max_redirects: int = 5
    max_body_bytes: int = 1_000_000


class SiftReadabilityExtractProvider:
    name = "sift-readability"

    def __init__(
        self,
        *,
        limits: ReadabilityExtractorLimits | None = None,
        resolver: AddressResolver | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.limits = limits or ReadabilityExtractorLimits()
        self.resolver = resolver or resolve_host_addresses
        self.client = client

    async def extract(self, urls: list[str]) -> list[RuntimeExtractedDocument]:
        documents: list[RuntimeExtractedDocument] = []
        for url in urls:
            documents.append(await self._extract_one(url))
        return documents

    async def _extract_one(self, url: str) -> RuntimeExtractedDocument:
        current_url = _validate_extract_url(url, self.resolver)
        redirects = 0
        owns_client = self.client is None
        timeout = httpx.Timeout(
            connect=self.limits.connect_timeout,
            read=self.limits.read_timeout,
            write=self.limits.connect_timeout,
            pool=self.limits.connect_timeout,
        )
        client = self.client or httpx.AsyncClient(timeout=timeout, follow_redirects=False)
        try:
            while True:
                response = await client.get(current_url)
                if response.is_redirect:
                    redirects += 1
                    if redirects > self.limits.max_redirects:
                        raise SiftRuntimeError(
                            "extract_redirect_limit",
                            "Readable extraction exceeded the redirect limit.",
                        )
                    location = response.headers.get("location")
                    if not location:
                        raise SiftRuntimeError("extract_redirect_invalid", "Redirect had no URL.")
                    current_url = _validate_extract_url(
                        urljoin(current_url, location),
                        self.resolver,
                    )
                    continue
                response.raise_for_status()
                _validate_content_type(response.headers.get("content-type", ""))
                body = response.content
                if len(body) > self.limits.max_body_bytes:
                    raise SiftRuntimeError(
                        "extract_body_too_large",
                        "Readable extraction response body is too large.",
                    )
                html = body.decode(response.encoding or "utf-8", errors="replace")
                title, text = _extract_readable_text(html)
                return RuntimeExtractedDocument(
                    url=str(response.url),
                    title=title,
                    content=text,
                    raw_content=html,
                )
        except httpx.TimeoutException as error:
            raise SiftRuntimeError("extract_timeout", "Readable extraction timed out.") from error
        except httpx.HTTPStatusError as error:
            raise SiftRuntimeError(
                "extract_http_error",
                f"Readable extraction returned HTTP {error.response.status_code}.",
            ) from error
        except httpx.HTTPError as error:
            raise SiftRuntimeError(
                "extract_network_error",
                "Readable extraction failed.",
            ) from error
        finally:
            if owns_client:
                await client.aclose()


def _validate_extract_url(url: str, resolver: AddressResolver) -> str:
    parsed = urlparse(url.strip())
    return validate_outbound_url(
        parsed.geturl(),
        policy=extraction_policy(),
        resolver=resolver,
    )


def _validate_content_type(content_type: str) -> None:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized not in {"text/html", "text/plain", "application/xhtml+xml"}:
        raise SiftRuntimeError(
            "extract_content_type_blocked",
            "Readable extraction only accepts textual page content.",
        )


def _extract_readable_text(html: str) -> tuple[str, str]:
    parser = _ReadableHTMLParser()
    parser.feed(html)
    return parser.title.strip(), " ".join(parser.text_parts).strip()


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.text_parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "iframe", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "iframe", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if not text or self._skip_depth:
            return
        if self._in_title:
            self.title = f"{self.title} {text}".strip()
            return
        self.text_parts.append(text)
