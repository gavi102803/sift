# Hermes-Informed Runtime Migration Plan

Date: 2026-06-27

Status: historical Personal/Local Companion migration plan. It is not the Managed production
Harness plan or a production completion record. Managed execution authority now lives in
`cloudflare/src/sift_worker/`; current release gates are defined by
`provider-conformance-test-matrix.md` and the Worker tests. Any "Implemented locally" statement
below refers only to the older `backend/` compatibility implementation unless it names a Worker
path explicitly.

This plan starts after the manifest, driver contract, capability spec, and conformance matrix are accepted. It does not delete the current OpenAI-compatible adapter first. It folds it into a named `ChatCompletionsDriver`.

## Phase 0: Freeze Current Behavior

- Keep current runtime paths working.
- Add Hermes Reuse Decision Record as a release gate for any future "Hermes support" claim.
- Add failing/regression tests for the user-visible bugs already found:
  - query visible immediately after capture;
  - capture failure keeps original query visible;
  - retry does not duplicate Concept or Turn;
  - DeepSeek `json_schema` 400 is recorded as structured-output capability failure, not generic provider failure.
- Enforce test/dev/prod settings-path isolation for all new tests.
- Permit plaintext local provider settings only for local development and controlled tests.

Release gate before real user API-key configuration:

- provider credentials are out of ordinary plaintext JSON;
- connections are user-scoped;
- credentials are secure references or encrypted values;
- API responses return masked previews only;
- tests cannot read or write real profile settings.

## Phase 1: Provider Preset Registry

- Introduce pinned `ProviderPreset` data with:
  - `hermes_commit_sha`;
  - upstream path;
  - `api_mode`;
  - `protocol_driver`;
  - auth type;
  - base URL;
  - model list behavior;
  - exposure tier.
- Keep existing provider settings shape at the API boundary.
- Map current `RuntimeModelProviderProfile` into `ProviderPreset`.

## Phase 2: ChatCompletionsDriver Extraction

- Rename/consolidate current `OpenAICompatibleRuntimeProvider` into `ChatCompletionsDriver`.
- Move provider-specific payload decisions out of the driver.
- Add a request builder that consumes `ResolvedCapabilityPolicy`.
- Migrate DeepSeek, OpenRouter, Kimi, Nous, and Custom to the same driver.

## Phase 3: Capability Resolver

- Implement resolution order:

```text
Protocol Default
-> Provider Override
-> Model Family Policy
-> Connection Probe Result
```

- Replace `_supports_response_format(provider_name)` with structured-output strategy resolution.
- Add connection probe cache.
- Probe DeepSeek `json_schema`, `json_object`, and prompt fallback.
- Keep prompt-only fallback behind cached policy, not runtime blind retry.

## Phase 4: Research Stack Split

- Split `web_provider` into:
  - `search_provider`;
  - `extract_provider`.
- Add Sift Built-in Readability Extractor.
- Default to DDGS Search + Sift Readability Extract.
- Add `searchDiscovered` versus `sourceVerified` answer-source status.

## Phase 5: Credential Store Hardening And Migration

- This phase is not permission to delay credential isolation. Credential isolation is already a Phase 0 release gate before real user API-key configuration.
- Complete production credential-store hardening if earlier phases used a temporary dev-only implementation.
- Add migration for any existing local dev provider settings. Implemented: legacy `runtime:<provider>:api_key` refs remain readable and are rewritten to user-scoped refs on the next save.
- Add user-scoped provider connection management. Implemented: credential refs are written as `user:<user_id>:<kind>:<provider>:api_key`; default local scope is `local-dev`, override with `SIFT_USER_ID`.
- Block tests from reading real `.env` unless explicitly marked live. Implemented for live conformance: the runner only reads explicit `SIFT_TEST_*` variables and writes probe cache outside profile settings.

## Phase 6: Additional Drivers

- Harden `AnthropicMessagesDriver`.
- Add `GeminiDriver`. Implemented locally for native `generateContent`, `streamGenerateContent`, and model listing; live conformance remains required before Stable promotion.
- Add `ResponsesDriver` only after OpenAI/xAI Responses use cases are explicit.
- Leave `BedrockDriver` deferred.

## Phase 7: Conformance Gate

- Run the provider conformance matrix before making a provider Stable.
- Providers without passing live tests remain Advanced or Deferred.
- Router providers must pass against the selected default routed model, not just the router endpoint.

## Non-goals

- Do not vendor the full Hermes runtime.
- Do not import Hermes CLI, gateway, agent loop, memory, OAuth flows, or auxiliary-model semantics into Sift.
- Do not create one full adapter per provider.
- Do not make Sift knowledge mutation depend on provider-specific runtime code.
