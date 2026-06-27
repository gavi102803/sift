# Provider Conformance Test Matrix

Date: 2026-06-27

This matrix defines the minimum verification before a provider can move from Planned Stable to Stable in Sift Profile.

## Planned Stable Providers

Stable target set:

- OpenAI
- Anthropic
- Gemini
- DeepSeek
- OpenRouter
- Kimi
- Nous
- Custom OpenAI-compatible endpoint

## A. Model Driver Conformance

Executable harness:

- `backend/src/sift_backend/runtime/conformance.py`
- `backend/src/sift_backend/runtime/live_conformance.py`
- `backend/tests/test_provider_conformance.py`
- `backend/tests/test_live_conformance.py`

Current automated coverage includes plain completion, streaming, structured-output
strategy probing, parameter-policy resolution, and model-list verification. Product
flows remain covered by Sift E2E smoke tests.

| Case | Requirement |
| --- | --- |
| Plain completion | Provider returns a short non-streamed response. |
| Streaming | Provider emits incremental text deltas and a completed event. |
| Structured output | Resolved strategy works: `jsonSchema`, `jsonObject`, or `promptAndValidate`. |
| Parameter policy | Disallowed params are omitted; fixed params are fixed; token field is correct. |
| Model list | Provider model listing returns the configured model or a deliberate no-listing policy. |
| Initial capture | Capture creates one Concept and one visible user Turn. |
| Follow-up continuity | Follow-up sees the concept memory and prior turns. |
| Candidate update | Candidate updates validate and persist as pending/confirmed according to mutation policy. |
| Proposal | Proposal creation validates `baseNoteRevision` and patch operations. |
| Failure query visibility | If capture generation fails, the original query remains visible. |
| Retry idempotency | Retry does not duplicate Concept or Turn. |

## Matrix

| Provider | Plain | Stream | Structured | Params | Model list | Tool call | Mutation payload | Failure query visible | Retry idempotent |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| OpenAI | Required live | Required live | Required live | Required unit + live | Required live | Required live or mocked tool server | Required | Required | Required |
| Anthropic | Required live | Required live | Required prompt-validate live | Required unit + live | Required live | Required live or mocked tool server | Required | Required | Required |
| Gemini | Required live | Required live | Required native/probe live | Required unit + live | Required live | Required live or mocked tool server | Required | Required | Required |
| DeepSeek | Required live | Required live | Required probes for `json_schema`, `json_object`, prompt fallback | Required unit + live | Required live | Required live or mocked tool server | Required | Required | Required |
| OpenRouter | Required live for chosen default routed model | Required live | Required per routed model family | Required unit + live | Required live | Required live or mocked tool server | Required | Required | Required |
| Kimi | Required live | Required live | Required live | Temperature omission required | Required live | Required live or mocked tool server | Required | Required | Required |
| Nous | Required live | Required live | Required live | Required unit + live | Required live | Required live or mocked tool server | Required | Required | Required |
| Custom | Required against configured endpoint | Required if endpoint claims stream | Probe-derived | Probe-derived | Required if listing is supported | Required if endpoint claims tools | Required when chosen as default | Required | Required |

Model Driver Conformance must not depend on DDGS, page extraction, or public web reliability.

Live runner:

```bash
python -m sift_backend.runtime.live_conformance --provider deepseek
```

The live runner only reads explicit `SIFT_TEST_*` variables, writes probe cache to
`SIFT_CAPABILITY_PROBE_CACHE_PATH` or `/tmp/sift-live-conformance-probes.json`,
and never reads or mutates Sift Profile settings. If every selected provider is
skipped because credentials are missing, the command exits non-zero.

## B. Research Stack Conformance

| Case | Requirement |
| --- | --- |
| DDGS discovery | Search returns normalized title, URL, snippet, and provider metadata. |
| Readability extraction | Extractor returns final URL, title, extracted text, fetched timestamp, and extractor metadata. |
| Source classification | Search-only result is `searchDiscovered`; successful extraction is `sourceVerified`. |
| SSRF safety | Localhost, private IP, metadata IP, unsafe redirects, and unsupported schemes are blocked. |
| Content safety | Body size, timeout, redirects, and content type are enforced. |
| Failure reporting | Extract failure is visible as `extractFailed`, not silently promoted to verified source. |

## C. Sift E2E Smoke Test

Run against one or two Stable providers after Model Driver and Research Stack conformance pass:

- Capture -> source retrieval -> assistant answer -> candidate update.
- Follow-up -> proposal -> retry idempotency.
- Capture failure -> original query visible -> retry uses same Concept/Turn.

## Test Isolation Rules

- Unit tests use temp settings paths.
- Unit tests never read real `.env`.
- Unit tests never write real provider profile files.
- Live tests require explicit environment variables in the test runner.
- Live tests must skip individual providers when credentials are absent, but the
  runner must fail when every selected provider is skipped.
- Test credentials must not be persisted into Sift app settings.
- API assertions must confirm only masked key previews are returned.
- Hidden/development providers must not be returned by the Profile catalog API.

## Live Credential Names

Suggested live test variables:

- `SIFT_TEST_OPENAI_API_KEY`
- `SIFT_TEST_ANTHROPIC_API_KEY`
- `SIFT_TEST_GEMINI_API_KEY`
- `SIFT_TEST_DEEPSEEK_API_KEY`
- `SIFT_TEST_OPENROUTER_API_KEY`
- `SIFT_TEST_KIMI_API_KEY`
- `SIFT_TEST_NOUS_API_KEY`
- `SIFT_TEST_CUSTOM_BASE_URL`
- `SIFT_TEST_CUSTOM_API_KEY`
- `SIFT_TEST_TAVILY_API_KEY`
- `SIFT_TEST_EXA_API_KEY`
- `SIFT_TEST_FIRECRAWL_API_KEY`

## Research Stack Tests

Default:

```text
Search: DDGS
Extract: Sift Built-in Readability Extractor
```

Required behaviors:

- Search success plus extract success yields `sourceVerified`.
- Search success plus extract failure yields `searchDiscovered`.
- Search snippet alone is never treated as verified source text.
- Extractor must reject non-http(s), localhost, private IP, and unsafe redirects.
- Extracted content must record final URL, title, text, fetched timestamp, and extraction provider.

## Idempotency Tests

Capture flow:

1. Client sends raw query with idempotency key.
2. Backend creates or reuses pending Concept.
3. Backend creates or reuses visible user Turn.
4. Runtime generation fails.
5. Retry with same key reuses the same Concept and Turn.
6. Retry success appends one assistant Turn and one mutation result.

Follow-up flow:

1. Client sends follow-up with idempotency key.
2. Backend creates or reuses visible user Turn.
3. Runtime generation fails.
4. Retry with same key reuses the user Turn.
5. Retry success appends one assistant Turn and one proposal/candidate update set.
