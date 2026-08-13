# AI SDK Shadow Evaluation

Status: **HOLD for production migration; continue isolated live evaluation.**

Evaluated on 2026-08-13 with the exact package versions in `package.json`. The upstream packages
are consumed unmodified.

## Evidence completed

- Strict TypeScript checking passes.
- 52 contract tests pass, including 30 mock initial/follow-up scenarios.
- The bounded agent test completes search → extract → answer → schema-validated card.
- Tests cover tool allowlisting, duplicate-call caching, tool/model budgets, cancellation, total
  timeout, citation-universe rejection, schema rejection, and redacted provider failure after the
  first delta with `maxRetries: 0`.
- Local 30-scenario mock benchmark: p50 CPU 0.726 ms and p95 CPU 5.415 ms. This is a regression
  signal, not a deployed Worker CPU measurement.
- Wrangler dry-run: 2,197,651-byte bundle (2.10 MiB), 350.40 KiB gzip, no bindings.
- Cloudflare deployment: `sift-ai-sdk-shadow`, startup 49 ms, no production route or D1 binding.
- The deployed Worker has one secret binding, `SIFT_SHADOW_TOKEN`; its value is stored in macOS
  Keychain under service `com.sift.ai-sdk-shadow`, account `shadow-token`.
- Local workerd HTTP smoke returns 401 without the token and 200 with it.

## Remaining live gates

- Direct authenticated health verification against the deployed `workers.dev` endpoint is pending.
  This machine's direct TLS connection failed before HTTP, and Wrangler remote preview later failed
  on the same preview/tail WebSocket TLS path after successful API upload. This is not evidence of a
  Worker exception, but it prevents claiming deployed request-path verification.
- Run one real BYOK tool-call flow each for OpenAI, Anthropic, and Google with `pnpm run live:eval`.
- Record deployed Worker CPU and request latency for those flows; the local mock benchmark does not
  satisfy the live CPU gate.
- Compare answer quality, calls, tokens, latency, and failure rate against the current Python
  runtime on the same evaluation set.
- Production checkpoint/reconnect and iOS event parity remain intentionally outside this shadow;
  they must be tested when an adapter is integrated behind the existing Sift control plane.

## Current decision

The architecture is viable: the SDK handles provider transport, streaming, structured output, and
the tool loop while Sift continues to define budgets, tools, evidence, errors, cancellation, and
durable ownership. The shadow adapter is materially smaller than the current provider runtime, but
it does not yet prove full behavioral parity or live multi-provider reliability. Do not replace or
rewrite the production Worker until every remaining live gate passes.
