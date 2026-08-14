# Sift AI SDK Shadow Worker

This Worker evaluates the unmodified Vercel AI SDK as a replaceable Sift model execution
kernel. It is deliberately isolated from production routes, D1, iOS, and durable knowledge
writes.

## Ownership boundary

- Sift owns durable runs, idempotency, leases, checkpoints, total budgets, authorization,
  evidence provenance, and knowledge commits.
- The upstream AI SDK owns provider transport, normalized streams, structured output, and the
  shadow evaluator's bounded in-request tool loop.
- `AiSdkAgentEngine` is a thin adapter. It does not implement a provider protocol, SSE parser, or
  independent agent loop.

The staging product integration uses a stricter boundary: Sift's Python Worker retains the
durable multi-round tool loop, while the AI SDK engine executes one bounded model call at a time.
The Python Worker checkpoints each normalized tool call/result before requesting the next AI SDK
call, so Worker interruption recovery does not depend on in-memory SDK state.

## Internal staging engine

`wrangler.engine.toml` deploys `sift-ai-sdk-engine-staging` without a public route. The staging
Python Worker reaches it only through the `AI_SDK_ENGINE` Service Binding. Internal endpoints are
authenticated with `SIFT_ENGINE_TOKEN` and accept the provider key only as a request header:

- `POST /internal/v1/generate`;
- `POST /internal/v1/tool-calls`;
- `POST /internal/v1/stream`.

The engine disables AI SDK retries and telemetry. It returns only normalized content, tool calls,
usage, and stable error codes; provider error bodies and credentials are not relayed to Sift.

AI SDK UI is not a native SwiftUI component library, and AG-UI is an event protocol rather than a
drop-in iOS interface. Sift therefore keeps its native SwiftUI and maps stable Sift events to it.
The SDK's provider-specific stream format must not become an iOS API contract.

The built-in `web_search` and `extract_url` tools operate only on evidence included in the
evaluation request. `extract_url` accepts a source id rather than an arbitrary URL, so the shadow
cannot become an SSRF proxy. Custom provider base URLs are rejected unless their normalized HTTPS
URL appears in `SIFT_SHADOW_ALLOWED_BASE_URLS`.

## API

All endpoints require `Authorization: Bearer <SIFT_SHADOW_TOKEN>`:

- `GET /health`
- `POST /v1/eval/initial` — answer stream followed by a schema-validated, non-durable card
- `POST /v1/eval/follow-up` — answer stream only

Provider credentials are request-only headers and are never persisted or returned:

- `x-sift-provider`: `openai`, `anthropic`, `google`, or `openai-compatible`
- `x-sift-model`
- `x-sift-provider-key`
- `x-sift-provider-base-url` when using an allowlisted custom endpoint

The response is `application/x-ndjson`. It emits `run_started`, `sources`, bounded step/tool
events, answer `delta` events, optional `card`, aggregate `usage`, and one terminal or redacted
error event. `sources` is always emitted before the first answer delta.

## Local verification

```bash
cp .dev.vars.example .dev.vars
pnpm install --frozen-lockfile
pnpm run check
pnpm run dev
```

`pnpm run check` runs strict type checking, mock contract/evaluation tests, a 30-scenario mock CPU
benchmark, a Wrangler dry-run, and the 3 MiB Sift bundle gate. The local CPU benchmark is a fast
regression signal; deployed Worker CPU remains a separate live acceptance gate. A real BYOK
provider check can be run without writing credentials to disk:

```bash
SIFT_SHADOW_URL=https://example.workers.dev \
SIFT_SHADOW_TOKEN=... \
SIFT_PROVIDER=openai \
SIFT_MODEL=... \
SIFT_PROVIDER_API_KEY=... \
pnpm run live:eval
```

Run the live check separately for OpenAI, Anthropic, and Google. The script prints only provider,
usage, and terminal status; it never prints the supplied key.
