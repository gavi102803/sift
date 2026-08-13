# Sift Cloudflare Worker

This directory is Sift's authoritative production backend. The SQLAlchemy
backend remains a local/reference implementation; production behavior must be
implemented and accepted here rather than inferred from legacy backend tests.

Implemented:

- Python Worker entrypoint backed by FastAPI;
- health and iOS bootstrap/provider-catalog endpoints;
- closed-beta invite activation, installation-bound bearer authentication, and
  rotating session refresh;
- D1-backed `POST /v1/concept-runs`;
- idempotent model-run persistence and owner-scoped run/event reads;
- a native Worker `TransformStream` resume path that forwards request-local
  provider deltas directly to iOS, with coalesced D1 events retained for
  disconnect and relaunch recovery;
- request-local BYOK calls for OpenAI-compatible, Anthropic, and Gemini providers;
- atomic Concept, Note Block, Note Revision, Turn, and terminal Model Run commits;
- owner-scoped Concept list/read endpoints;
- owner-scoped manual summary, Note Block, whole-note, and organization edits;
- optimistic Revision conflict checks and atomic Revision restore;
- archive/restore, owner-scoped relations, follow-up replacement, and regeneration;
- revision-safe AI update proposals with idempotent merge and dismiss;
- request-local web retrieval through DDGS, Tavily, Exa, Firecrawl, Brave, or
  xAI, with bounded requests, query/result relevance checks, validated
  citations, and durable sources;
- runtime model catalogs and request-local model listing for OpenAI-compatible,
  Anthropic, and Gemini provider protocols;
- persisted web-search settings and a real managed-search diagnostic;
- continuity summaries and periodic knowledge-review child ModelRuns;
- durable Claims and Learning State produced by validated periodic review;
- D1 migrations for beta identity, model runs, provider metadata, concepts,
  proposals, retrieval, maintenance, Claims, and Learning State.
- one provider-neutral Agent Core for initial capture, follow-up, continuity,
  and knowledge-review workflows, with persisted versioned specs, strict resume
  compatibility checks, and enforced model, tool, step, and model-output budgets;
- D1 execution leases, heartbeat renewal, fenced commits, durable checkpoints,
  stale-run takeover, explicit cancellation, and reset-before-stream-replay;
- a typed Tool Registry for `web.search` and `web.extract`, including argument
  contracts, timeouts, HTTPS/redirect/content/size safety checks, bounded
  allowlisted results, explicit `toolFailed` events, and durable provenance hashes;
- a bounded two-round plan/act/observe loop so the model can search, inspect the
  returned sources, and then choose a page to extract without an unbounded agent;
- bounded user input, card/turn/continuity context, retrieval evidence, and
  streamed model output, plus a forced tool-call capability probe before a
  declared tool-capable provider is saved;
- lease-fenced provider snapshots before the first model call, so a resumed run
  cannot silently switch provider or model, and recoverable maintenance child runs;
- atomic initial input persistence: the ModelRun, pending Concept, and original
  user Turn are visible before provider work and reused by idempotent retries;
- explicit provider capability profiles and protocol-conformance tests for
  OpenAI-compatible, Anthropic, and Gemini tool calling and streaming.

A submitted capture is durable before provider work begins. The Provider key
remains request-local and is never stored in D1. Provider metadata
(`providerId`, `baseURL`, and `model`) is stored per owner. This preserves the
contract in `docs/contracts/managed-byok-beta.md`.

## Local development

Requirements:

- Node.js;
- `uv`;
- Wrangler authentication is required only for remote resources/deployment.

```bash
cd cloudflare
cp .dev.vars.example .dev.vars
uv sync
pnpm install
pnpm exec wrangler d1 migrations apply sift --local
uv run pywrangler dev
```

Verify:

```bash
curl http://127.0.0.1:8787/health
```

Run the production Worker gate:

```bash
scripts/check.sh worker
```

## Create the remote resources

After authenticating Wrangler, the production helper reuses an existing D1
database named `sift` or creates one in the APAC location, writes its UUID to
`wrangler.toml`, applies all remote migrations, and deploys:

```bash
cd cloudflare
pnpm exec wrangler login
pnpm run deploy:production
```

The helper refuses to continue while Wrangler is unauthenticated and refuses
ambiguous duplicate databases. Individual commands remain available for
operator recovery:

```bash
pnpm exec wrangler d1 create sift --location apac
pnpm exec wrangler d1 migrations apply sift --remote
uv run pywrangler deploy
```

Generate an invite hash without putting the invite code in shell history:

```bash
python3 scripts/hash_invite.py
```

Seed the hash returned by the script:

```bash
pnpm exec wrangler d1 execute sift --remote \
  --command "INSERT INTO beta_invites (code_hash) VALUES ('<sha256>')"
```

Or issue a cryptographically random invite in one step. The raw code is printed
once; only its SHA-256 hash is written to D1:

```bash
pnpm run invite:issue
```

Do not deploy while `database_id` still contains the all-zero placeholder.

The current Managed iOS endpoint is:

```text
https://sift-backend.sift-cloudflare-worker-tools.workers.dev
```

Verify the deployed route and its public authentication boundary with:

```bash
pnpm run verify:production
```

The verifier checks `/health` and the unauthenticated `/v1/app-status`
contract. It tries the production URL directly first. If the current network
cannot complete `workers.dev` TLS, it uses the existing Wrangler OAuth session
to run the same read-only checks from Cloudflare Browser Run. Production deploys
run this verifier automatically after upload.

Current production resources:

- Worker: `sift-backend`
- deployment ID: `8edb7036-d015-44dc-9d15-5d400bf58c72` (2026-08-11)
- D1 database: `sift` (`f1444fbf-08f1-4e0e-8cd3-b224e235199a`)
- D1 primary region observed during verification: APAC / SIN

Wrangler confirmed the deployment and route above. On 2026-08-11, Cloudflare
Browser Run independently returned `200` with the production Workers identity
from `/health` and the stable `authentication_required` response from
unauthenticated `/v1/app-status`. The development Mac and Simulator still could
not complete a `workers.dev` TLS handshake through the current VPN route, so
authenticated device flows remain a separate release gate.

Some managed networks intercept or rewrite `workers.dev` DNS/TLS. Cloudflare's
API can still report the route as enabled while that network cannot reach it.
For broader distribution, bind a custom domain in a Cloudflare zone and verify
from the target mobile networks before calling the endpoint generally
available.

## Remaining live release gates

Automated Worker, D1 SQL, and iOS contract tests are mandatory in PR CI. Before
calling a specific deployment dogfood-ready, the remaining environment-dependent
gates are:

1. verify model listing and the Managed capture/follow-up flow on the target
   iPhone using its device-local provider key;
2. compare the same flows with the Release Simulator build;
3. measure production CPU time against the Workers Free plan limit.
