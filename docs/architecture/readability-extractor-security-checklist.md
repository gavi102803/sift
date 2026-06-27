# Readability Extractor Security Checklist

Date: 2026-06-27

Default production web extraction is blocked until this checklist passes.

Default Research Stack:

```text
Search Provider: DDGS
Extract Provider: Sift Built-in Readability Extractor
```

Search snippets are discovery evidence only. A source becomes `sourceVerified` only after safe extraction succeeds.

## URL And Network Safety

- Allow only `http` and `https`.
- Reject `localhost`, loopback, link-local, private ranges, multicast, broadcast, and unspecified IPs.
- Reject metadata service IPs, including `169.254.169.254`.
- Resolve DNS before request and validate every resolved address.
- Revalidate after each redirect.
- Enforce maximum redirect count.
- Reject redirects to blocked schemes, hosts, or IP ranges.
- Use a dedicated HTTP client with no ambient proxy or local credential forwarding unless explicitly configured.

## Request Limits

- Set connect timeout.
- Set read timeout.
- Set total request timeout.
- Limit response body bytes.
- Limit decompressed body bytes.
- Limit number of fetched resources to the target HTML document only.
- Do not execute JavaScript.
- Do not load subresources such as images, scripts, iframes, CSS, fonts, or media.

## Response Validation

- Accept only safe textual content types:
  - `text/html`;
  - `text/plain`;
  - selected XML/feed types only if parser support exists.
- Reject binary, archive, executable, office document, and media content types.
- Sniff only enough bytes to prevent content-type spoofing; do not parse unsafe payloads.
- Normalize final URL and record it separately from requested URL.

## Extraction Output

Extractor output must include:

- requested URL;
- final URL;
- title;
- extracted text;
- extraction provider;
- fetched timestamp;
- content type;
- byte length;
- safety decision.

Extractor failure must include a safe error category and must not promote search snippets to verified source text.

## Test Requirements

- Blocks localhost.
- Blocks private IP.
- Blocks metadata IP.
- Blocks DNS result that resolves to private IP.
- Blocks redirect from public URL to private IP.
- Blocks unsupported schemes.
- Blocks oversized body.
- Blocks timeout.
- Blocks unsafe content type.
- Does not execute page scripts.
- Returns `sourceVerified` only on successful extraction.
- Returns `searchDiscovered` or `extractFailed` when extraction is unavailable.

