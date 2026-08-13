from __future__ import annotations

import asyncio
import html
import ipaddress
import json
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urljoin, urlparse
from uuid import uuid4
from xml.etree import ElementTree

from sift_worker.errors import PublicError

_RESULT_PATTERN = re.compile(
    r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SNIPPET_PATTERN = re.compile(
    r'<a[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_MARKDOWN_LINK_PATTERN = re.compile(
    r'<link[^>]+type=["\']text/markdown["\'][^>]+href=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_SCRIPT_STYLE_PATTERN = re.compile(
    r"<(script|style|noscript)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_MAIN_PATTERN = re.compile(
    r"<(?:main|article)\b[^>]*>(.*?)</(?:main|article)>",
    re.IGNORECASE | re.DOTALL,
)
_RECENT_DATE_PATTERN = re.compile(
    r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2},\s+20\d{2}\b"
)
_TAG_PATTERN = re.compile(r"<[^>]+>")
_QUERY_STOP_WORDS = {
    "a",
    "an",
    "and",
    "answer",
    "are",
    "citations",
    "conclusion",
    "current",
    "facts",
    "for",
    "format",
    "give",
    "include",
    "is",
    "key",
    "latest",
    "now",
    "of",
    "or",
    "please",
    "search",
    "sources",
    "summarize",
    "summary",
    "the",
    "today",
    "to",
    "web",
    "what",
    "when",
    "which",
    "with",
}


WEB_PROVIDER_PROFILES = {
    "ddgs": ("DuckDuckGo", "DuckDuckGo search; no API key required.", False, False, True),
    "tavily": ("Tavily", "Search and extraction via Tavily.", True, True, False),
    "exa": ("Exa", "Exa web search and content extraction.", True, True, False),
    "firecrawl": ("Firecrawl", "Firecrawl search and content extraction.", True, True, False),
    "brave-free": ("Brave Search", "Brave Search free tier.", True, False, False),
    "xai": ("xAI Web Search", "xAI Grok-backed web search.", True, False, False),
}

_MAX_EXTRACT_RESPONSE_BYTES = 1_000_000
_MAX_WEB_PROVIDER_RESPONSE_BYTES = 1_000_000
_MAX_EXTRACTED_TEXT_CHARS = 20_000
_EXTRACT_CONTENT_TYPES = {
    "text/html",
    "text/markdown",
    "text/plain",
    "application/xhtml+xml",
}


class WorkerWebSearchClient:
    def __init__(
        self,
        fetcher: Any | None = None,
        *,
        provider_id: str = "ddgs",
        api_key: str = "",
    ) -> None:
        self.provider_id = provider_id.strip().lower()
        self.api_key = api_key.strip()
        self.fetcher = fetcher or _workers_fetch

    async def search(self, query: str, *, max_results: int = 5) -> list[dict[str, str]]:
        search_query = _normalized_search_query(query)
        results = await self._search(search_query, max_results=max_results)
        relevant = _relevant_results(search_query, results)
        if not relevant:
            raise _retrieval_error()
        selected = relevant[:max_results]
        if self.provider_id == "ddgs":
            await self._enrich_ddgs_results(selected[:2])
        return selected

    async def extract(self, url: str) -> dict[str, str]:
        safe_url = _result_url(url)
        if safe_url is None:
            raise PublicError("tool_invalid_arguments", "The URL cannot be fetched.", 422)
        final_url, body, content_type = await self._fetch_extractable(safe_url)
        if content_type in {"text/html", "application/xhtml+xml", ""}:
            markdown_match = _MARKDOWN_LINK_PATTERN.search(body)
            if markdown_match:
                markdown_url = _result_url(
                    urljoin(final_url, html.unescape(markdown_match.group(1)))
                )
                if markdown_url is not None:
                    try:
                        final_url, body, _ = await self._fetch_extractable(markdown_url)
                    except PublicError:
                        pass
        excerpt = _page_excerpt(body, limit=_MAX_EXTRACTED_TEXT_CHARS)
        if not excerpt:
            raise _retrieval_error()
        return {
            "id": str(uuid4()),
            "title": _page_title(body) or urlparse(final_url).hostname or final_url,
            "url": final_url,
            "snippet": excerpt,
            "publishedAt": "",
            "provenance": "extracted",
        }

    async def _fetch_extractable(self, safe_url: str) -> tuple[str, str, str]:
        response = await self.fetcher(
            safe_url,
            method="GET",
            headers={
                "Accept": "text/markdown, text/plain, text/html",
                "User-Agent": "Mozilla/5.0 (compatible; Sift/0.1)",
            },
        )
        if not 200 <= int(response.status) < 300:
            raise _retrieval_error()
        final_url = _result_url(str(getattr(response, "url", safe_url) or safe_url))
        if final_url is None:
            raise PublicError("tool_unsafe_redirect", "The URL redirected unsafely.", 422)
        content_length = _response_header(response, "content-length")
        if _declared_response_size(content_length) > _MAX_EXTRACT_RESPONSE_BYTES:
            raise PublicError("tool_response_too_large", "The page is too large to extract.", 422)
        content_type = _response_header(response, "content-type").partition(";")[0].lower()
        if content_type and content_type not in _EXTRACT_CONTENT_TYPES:
            raise PublicError("tool_unsupported_content", "The page type is not supported.", 422)
        body = await _response_text_limited(response, _MAX_EXTRACT_RESPONSE_BYTES)
        return final_url, body, content_type

    async def _search(self, query: str, *, max_results: int) -> list[dict[str, str]]:
        if self.provider_id not in WEB_PROVIDER_PROFILES:
            raise PublicError("managed_unsupported", "Unsupported web provider.", 422)
        if self.provider_id != "ddgs" and not self.api_key:
            raise PublicError("invalid_provider_key", "Check your web provider API key.", 401)
        if self.provider_id == "tavily":
            return await self._post_results(
                "https://api.tavily.com/search",
                {
                    "api_key": self.api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": max_results,
                    "include_answer": False,
                    "include_raw_content": False,
                },
                result_path=("results",),
            )
        if self.provider_id == "exa":
            return await self._post_results(
                "https://api.exa.ai/search",
                {"query": query, "numResults": max_results, "contents": {"highlights": True}},
                headers={"Authorization": f"Bearer {self.api_key}"},
                result_path=("results",),
            )
        if self.provider_id == "firecrawl":
            return await self._post_results(
                "https://api.firecrawl.dev/v1/search",
                {"query": query, "limit": max_results, "scrapeOptions": {"formats": ["markdown"]}},
                headers={"Authorization": f"Bearer {self.api_key}"},
                result_path=("data",),
            )
        if self.provider_id == "brave-free":
            count = max(1, min(max_results, 20))
            response = await self.fetcher(
                f"https://api.search.brave.com/res/v1/web/search"
                f"?q={quote_plus(query)}&count={count}",
                method="GET",
                headers={"X-Subscription-Token": self.api_key, "Accept": "application/json"},
            )
            data = await _web_response_json(response)
            web = data.get("web") if isinstance(data.get("web"), dict) else {}
            return _normalized_results(web.get("results"), max_results)
        if self.provider_id == "xai":
            response = await self.fetcher(
                "https://api.x.ai/v1/responses",
                method="POST",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                body=json.dumps(
                    {
                        "model": "grok-build-0.1",
                        "input": [
                            {
                                "role": "user",
                                "content": (
                                    f"Search the web for: {query}\\n"
                                    "Return JSON only with a results array containing title, "
                                    f"url, and description. Limit to {max_results} results."
                                ),
                            }
                        ],
                        "tools": [{"type": "web_search"}],
                        "include": ["no_inline_citations"],
                    }
                ),
            )
            data = await _web_response_json(response)
            return _xai_results(data, max_results)
        return await self._ddgs(query, max_results=max(max_results, 10))

    async def _ddgs(self, query: str, *, max_results: int) -> list[dict[str, str]]:
        headers = {
            "Accept": "text/html, application/rss+xml",
            "User-Agent": "Mozilla/5.0 (compatible; Sift/0.1)",
        }
        try:
            response = await self.fetcher(
                f"https://html.duckduckgo.com/html/?q={quote_plus(query)}",
                method="GET",
                headers=headers,
            )
            if 200 <= int(response.status) < 300:
                results = _duckduckgo_results(
                    await _response_text_limited(
                        response,
                        _MAX_WEB_PROVIDER_RESPONSE_BYTES,
                    ),
                    max_results,
                )
                if results:
                    return results
        except Exception:
            pass
        try:
            response = await self.fetcher(
                f"https://www.bing.com/search?format=rss&q={quote_plus(query)}",
                method="GET",
                headers=headers,
            )
            if 200 <= int(response.status) < 300:
                results = _bing_rss_results(
                    await _response_text_limited(
                        response,
                        _MAX_WEB_PROVIDER_RESPONSE_BYTES,
                    ),
                    max_results,
                )
                if results:
                    return results
        except Exception:
            pass
        raise _retrieval_error()

    async def _enrich_ddgs_results(self, results: list[dict[str, str]]) -> None:
        await asyncio.gather(
            *(self._enrich_ddgs_result(result) for result in results),
            return_exceptions=True,
        )

    async def _enrich_ddgs_result(self, result: dict[str, str]) -> None:
        extracted = await self.extract(result["url"])
        excerpt = extracted["snippet"]
        if excerpt:
            result["snippet"] = "\n\n".join(
                part for part in (result.get("snippet", ""), excerpt) if part
            )
            result["url"] = extracted["url"]
            result["provenance"] = "extracted"

    async def _post_results(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        result_path: tuple[str, ...],
    ) -> list[dict[str, str]]:
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        response = await self.fetcher(
            url,
            method="POST",
            headers=request_headers,
            body=json.dumps(payload),
        )
        data: Any = await _web_response_json(response)
        for key in result_path:
            data = data.get(key) if isinstance(data, dict) else None
        return _normalized_results(data, 5)


def _duckduckgo_results(body: str, max_results: int) -> list[dict[str, str]]:
    results = []
    seen: set[str] = set()
    matches = list(_RESULT_PATTERN.finditer(body))
    for index, match in enumerate(matches):
        raw_url, raw_title = match.groups()
        url = _result_url(html.unescape(raw_url))
        title = _clean_text(raw_title)
        if url is None or not title or url in seen:
            continue
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        segment = body[match.end():next_start]
        snippet_match = _SNIPPET_PATTERN.search(segment)
        seen.add(url)
        results.append(
            {
                "id": str(uuid4()),
                "title": title,
                "url": url,
                "snippet": _clean_text(snippet_match.group(1)) if snippet_match else "",
            }
        )
        if len(results) >= max_results:
            break
    return results


def _bing_rss_results(body: str, max_results: int) -> list[dict[str, str]]:
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError:
        return []
    results = []
    seen: set[str] = set()
    for item in root.findall("./channel/item"):
        url = _result_url(item.findtext("link", "").strip())
        title = _clean_text(item.findtext("title", ""))
        if url is None or not title or url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "id": str(uuid4()),
                "title": title,
                "url": url,
                "snippet": _clean_text(item.findtext("description", "")),
                "publishedAt": item.findtext("pubDate", "").strip(),
            }
        )
        if len(results) >= max_results:
            break
    return results


def _normalized_results(raw_results: Any, max_results: int) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw_results if isinstance(raw_results, list) else []:
        if not isinstance(item, dict):
            continue
        raw_url = item.get("url")
        raw_title = item.get("title")
        url = _result_url(raw_url) if isinstance(raw_url, str) else None
        title = _clean_text(raw_title) if isinstance(raw_title, str) else ""
        if url is None or not title or url in seen:
            continue
        seen.add(url)
        snippet = (
            item.get("description")
            or item.get("snippet")
            or item.get("content")
            or item.get("text")
        )
        if not isinstance(snippet, str):
            highlights = item.get("highlights")
            snippet = " ".join(value for value in highlights or [] if isinstance(value, str))
        results.append(
            {
                "id": str(uuid4()),
                "title": title,
                "url": url,
                "snippet": _clean_text(snippet or ""),
                "publishedAt": _published_at(item),
            }
        )
        if len(results) >= max_results:
            break
    if not results:
        raise _retrieval_error()
    return results


def _xai_results(data: dict[str, Any], max_results: int) -> list[dict[str, str]]:
    output_text = data.get("output_text")
    if not isinstance(output_text, str):
        output = data.get("output")
        texts = []
        for item in output if isinstance(output, list) else []:
            for content in item.get("content", []) if isinstance(item, dict) else []:
                if isinstance(content, dict) and isinstance(content.get("text"), str):
                    texts.append(content["text"])
        output_text = "".join(texts)
    try:
        parsed = json.loads(output_text or "{}")
    except ValueError as error:
        raise _retrieval_error() from error
    raw_results = parsed.get("results") if isinstance(parsed, dict) else None
    return _normalized_results(raw_results, max_results)


def _relevant_results(
    query: str,
    results: list[dict[str, str]],
) -> list[dict[str, str]]:
    terms = _query_terms(query)
    if not terms:
        return results
    required_matches = min(2, len(terms))
    return [
        result
        for result in results
        if sum(
            term in " ".join(
                (
                    result.get("title", ""),
                    result.get("snippet", ""),
                    result.get("url", ""),
                )
            ).casefold()
            for term in terms
        )
        >= required_matches
    ]


def _query_terms(query: str) -> list[str]:
    normalized = query.casefold()
    for term, replacement in (
        ("状态", " status "),
        ("版本", " version "),
        ("价格", " price "),
        ("发布", " release "),
    ):
        normalized = normalized.replace(term, replacement)
    for term in ("当前", "最新", "今天", "现在", "搜索", "查一下"):
        normalized = normalized.replace(term, " ")
    for phrase in ("怎么样", "是什么", "如何", "多少", "何时", "有没有"):
        normalized = normalized.replace(phrase, " ")
    candidates = re.findall(r"[a-z0-9][a-z0-9.+#-]*|[\u4e00-\u9fff]{2,}", normalized)
    return [
        stripped
        for term in dict.fromkeys(candidates)
        if (stripped := term.strip(".+-"))
        and stripped not in _QUERY_STOP_WORDS
        and len(stripped) >= 2
    ]


def _normalized_search_query(query: str) -> str:
    terms = _query_terms(query)
    return " ".join(terms) if terms else query.strip()


def _published_at(item: dict[str, Any]) -> str:
    value = item.get("publishedAt") or item.get("published_at") or item.get("publishedDate")
    return value.strip() if isinstance(value, str) else ""


async def _web_response_json(response: Any) -> dict[str, Any]:
    status = int(response.status)
    if status in {401, 403}:
        raise PublicError("invalid_provider_key", "Check your web provider API key.", 401)
    if status in {402, 429}:
        raise PublicError("provider_quota_exhausted", "Your web provider quota is used up.", status)
    if status < 200 or status >= 300:
        raise _retrieval_error()
    raw = await _streamed_response_bytes(
        response,
        _MAX_WEB_PROVIDER_RESPONSE_BYTES,
    )
    if raw is None:
        data = await response.json()
    else:
        try:
            data = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as error:
            raise _retrieval_error() from error
    converted = data.to_py() if hasattr(data, "to_py") else data
    if not isinstance(converted, dict):
        raise _retrieval_error()
    return converted


async def _response_text_limited(response: Any, max_bytes: int) -> str:
    raw = await _streamed_response_bytes(response, max_bytes)
    if raw is not None:
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise _retrieval_error() from error
    text = str(await response.text())
    if len(text.encode("utf-8")) > max_bytes:
        raise _response_too_large()
    return text


async def _streamed_response_bytes(response: Any, max_bytes: int) -> bytes | None:
    body = getattr(response, "body", None)
    if body is None or not hasattr(body, "getReader"):
        return None
    reader = body.getReader()
    result = bytearray()
    while True:
        chunk = await reader.read()
        done = chunk.get("done") if isinstance(chunk, dict) else getattr(chunk, "done", False)
        value = chunk.get("value") if isinstance(chunk, dict) else getattr(chunk, "value", None)
        if value is not None:
            converted = value.to_py() if hasattr(value, "to_py") else value
            try:
                encoded = converted.encode() if isinstance(converted, str) else bytes(converted)
            except (TypeError, ValueError) as error:
                raise _retrieval_error() from error
            if len(result) + len(encoded) > max_bytes:
                await _cancel_reader(reader)
                raise _response_too_large()
            result.extend(encoded)
        if done:
            return bytes(result)


async def _cancel_reader(reader: Any) -> None:
    cancel = getattr(reader, "cancel", None)
    if not callable(cancel):
        return
    try:
        result = cancel()
        if hasattr(result, "__await__"):
            await result
    except Exception:
        pass


def _response_too_large() -> PublicError:
    return PublicError(
        "tool_response_too_large",
        "The web response is too large to process.",
        422,
    )


async def _workers_fetch(*args: Any, **kwargs: Any) -> Any:
    from js import AbortSignal
    from workers import fetch

    kwargs.setdefault("signal", AbortSignal.timeout(8_000))
    return await fetch(*args, **kwargs)


def _result_url(value: str) -> str | None:
    candidate = f"https:{value}" if value.startswith("//") else value
    parsed = urlparse(candidate)
    if parsed.hostname and parsed.hostname.endswith("duckduckgo.com"):
        redirected = parse_qs(parsed.query).get("uddg", [])
        if redirected:
            candidate = redirected[0]
            parsed = urlparse(candidate)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return None
    hostname = parsed.hostname.casefold()
    if hostname == "localhost" or hostname.endswith((".local", ".internal")):
        return None
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        return candidate
    if (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_unspecified
    ):
        return None
    return candidate


def _clean_text(value: str) -> str:
    return " ".join(html.unescape(_TAG_PATTERN.sub(" ", value)).split())


def _page_excerpt(body: str, *, limit: int = 4_000) -> str:
    markdown_date = _RECENT_DATE_PATTERN.search(body)
    if markdown_date:
        return body[markdown_date.start():markdown_date.start() + limit].strip()
    main_match = _MAIN_PATTERN.search(body)
    html_body = main_match.group(1) if main_match else body
    cleaned = _clean_text(_SCRIPT_STYLE_PATTERN.sub(" ", html_body))
    return cleaned[:limit].strip()


def _page_title(body: str) -> str:
    match = re.search(r"<title\b[^>]*>(.*?)</title>", body, re.IGNORECASE | re.DOTALL)
    return _clean_text(match.group(1)) if match else ""


def _response_header(response: Any, name: str) -> str:
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return ""
    value = headers.get(name)
    return str(value).strip() if value is not None else ""


def _declared_response_size(value: str) -> int:
    if not value:
        return 0
    try:
        size = int(value)
    except ValueError:
        return 0
    return max(size, 0)


def _retrieval_error() -> PublicError:
    return PublicError(
        "retrieval_required",
        "Web retrieval is temporarily unavailable for this question.",
        502,
    )
