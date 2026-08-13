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

- `cloudflare/verification/live_conformance.py`
- `cloudflare/src/sift_worker/runtime.py`
- `cloudflare/tests/test_live_conformance.py`
- `cloudflare/tests/test_runtime.py`

The Cloudflare Worker is the production runtime authority. Current automated coverage includes
plain completion, provider-native incremental streaming, structured-card validation, autonomous
tool selection, native tool-call/tool-result round trips, model-call latency/token observation,
forced tool-capability probing, and model-list verification. The older
`backend/` conformance runner remains a Personal/Local Companion compatibility check and must not
be used as evidence that the production Worker passed.

| Case | Requirement |
| --- | --- |
| Plain completion | Provider returns a short non-streamed response. |
| Streaming | Provider emits incremental text deltas and a completed event. |
| Structured output | Resolved strategy works: `jsonSchema`, `jsonObject`, or `promptAndValidate`. |
| Parameter policy | Disallowed params are omitted; fixed params are fixed; token field is correct. |
| Model list | Provider model listing returns the configured model or a deliberate no-listing policy. |
| Tool result round trip | Tool observations use the provider-native result message and stay bounded and untrusted. |
| Call telemetry | Every attempted model call records lifecycle and latency; token counts are recorded only when reported by the provider. |
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

Production Worker live runner:

```bash
cd cloudflare
SIFT_LIVE_PROVIDER=deepseek \
SIFT_LIVE_MODEL=deepseek-chat \
SIFT_LIVE_API_KEY=... \
PYTHONPATH=.:src python -m verification.live_conformance
```

The live runner only reads explicit `SIFT_LIVE_*` variables, writes a redacted result to
`cloudflare/.data/live-conformance.json`, and never reads or mutates Sift Profile settings. It
exits non-zero when credentials are missing, streaming collapses into one terminal chunk, the
structured card fails, or a tool-capable model does not autonomously request Web Search.

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

The executable Managed production gate is `cloudflare/verification/production_e2e.py`. It uses
the same durable `concept-runs -> resume-stream` path as iOS and fails unless it observes at least
two live deltas, the current AgentSpec and tool-contract hash, a `web.search` event, persisted
citations, one new run, one new card, exactly one user/assistant turn pair, and idempotent replay.
Use a dedicated one-time invite or dedicated beta session; the verifier intentionally leaves the
created card durable as product evidence and never writes credentials into its artifact.
The manually dispatched `live-conformance.yml` workflow runs this gate after provider conformance
using a dedicated `SIFT_E2E_SESSION_TOKEN`; missing session or provider credentials fail the job
instead of skipping it.

```bash
cd cloudflare
SIFT_E2E_BASE_URL=https://sift-backend.example.workers.dev \
SIFT_E2E_INSTALLATION_ID=dedicated-e2e-installation \
SIFT_E2E_INVITE_CODE=... \
SIFT_E2E_PROVIDER=deepseek \
SIFT_E2E_MODEL=deepseek-chat \
SIFT_E2E_PROVIDER_API_KEY=... \
PYTHONPATH=.:src python -m verification.production_e2e
```

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

The production Worker runner uses only `SIFT_LIVE_PROVIDER`, `SIFT_LIVE_BASE_URL`,
`SIFT_LIVE_MODEL`, and `SIFT_LIVE_API_KEY`. `SIFT_TEST_*` variables belong to the legacy
Personal/Local Companion runner and are not production evidence.

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
