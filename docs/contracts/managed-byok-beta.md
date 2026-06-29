# Managed BYOK Closed Beta — Client ↔ Backend Contract

**Status: DRAFT — for codex ratification. Not implemented yet.** This document
defines the seam so the iOS client and the Runtime backend can be built in
parallel against a frozen contract. Nothing here is code; it is the agreement.

## Product form (locked)

```
User: install Sift → activate beta → connect own AI provider → paste own API key → use.
Sift: one managed, public, HTTPS Runtime backend that we operate.
      Users never see backend URL / VPS / Docker / runtime config.
      Users pay their own provider (BYOK); we do not fund or meter inference.
```

## 1. Backend endpoint

- A single fixed managed beta endpoint, e.g. `https://beta.<domain>` (final value TBD).
- **Release / TestFlight builds compile the endpoint in** (Info.plist `SIFTBackendBaseURL`
  or build setting). It is **not user-editable** and there is **no Backend-URL field** in
  the shipped UI.
- URL override exists **only in Debug / internal developer tooling**.
- TLS required for all traffic. Plain HTTP is rejected by the client.

## 2. Identity & activation

Two distinct identifiers — never conflate them:

| Identifier | Source | Purpose | NOT used for |
|---|---|---|---|
| `betaAccessToken` | issued by backend on activation | **authentication**, maps to `ownerId` | — |
| `installationId` | UUID generated on device, stored in Keychain | diagnostics, device binding, rate limiting | **identity / auth / scope** |

Every authenticated request carries:
```
Authorization: Bearer <betaAccessToken>
X-Sift-Installation: <installationId>
```

### Activation flow
1. User enters an invite code.
2. `POST /v1/beta/activate { inviteCode, installationId }` → `{ betaAccessToken, ownerId, expiresAt }`.
3. Client stores `betaAccessToken` in the **iOS Keychain**.

### Token lifecycle
- Token has `expiresAt`. Refresh strategy: **TBD** (refresh endpoint vs. re-activate) — codex to decide.
- Token is **revocable server-side** (per-token and per-owner kill switch).
- Expired or revoked token → `401` with a specific error code (§7). Client clears the
  token from Keychain and returns to the activation screen.

## 3. Owner scope (isolation boundary)

- `ownerId` is **derived from the token server-side**, never from a client-supplied value.
- **Every** `Concept`, `Turn`, `Source`, `Run`, `Idempotency` record, and SSE stream is
  scoped by `ownerId`.
- Cross-owner access returns `404` (not `403`) to avoid existence disclosure.
- `installationId` must never widen or substitute for owner scope.

## 4. Ephemeral BYOK credential relay (security-critical)

```
provider API key
  → stored ONLY in iOS Keychain
  → sent per runtime request in a header over TLS (e.g. X-Provider-Key)
  → backend holds it in memory ONLY to call the provider
  → discarded when the request completes
```

Hard requirements (codex must guarantee):
- The key value is **never** written to: database, logs, traces, metrics, analytics,
  error/crash reports, or support exports.
- Redact at every boundary (request logging middleware, exception handlers, tracing).
- Non-secret fields (`providerId`, `model`) **are** persisted; the key is **not**.
- This is a **relay, not a credential vault** — we are explicitly not building long-term
  managed-secret storage for the beta.

## 5. Providers / models supported in beta

- A curated subset (recommend starting with: `anthropic`, `openai`, `gemini`,
  `deepseek`, `openrouter`). Final list TBD.
- The provider catalog endpoint returns the supported set; the client picker shows only these.

## 6. Provider connection test

- `POST /v1/providers/test { providerId, model }` with the key in the relay header.
- Semantics: performs a **minimal** provider call to validate that key + model are
  reachable and authorized. Returns `200 { ok: true }` or an error code (§7).
- Must **not** persist the key. Used by the onboarding "Test connection" step.

## 7. Error codes (client maps each to a specific UX state)

| Code | HTTP | Client UX |
|---|---|---|
| `invite_invalid` / `invite_consumed` | 400/409 | activation error, re-enter code |
| `beta_token_expired` / `beta_token_revoked` | 401 | clear token, back to activation |
| `invalid_provider_key` | 401/402 | "Check your API key" on the provider screen |
| `provider_quota_exhausted` | 402/429 | "Your provider quota is used up" |
| `provider_unreachable` | 502 | transient; offer retry |
| `backend_unavailable` | 503 | "Can't reach Sift", retry |
| `owner_scope_not_found` | 404 | treat as missing, not an error toast |

## 8. Client onboarding (no infrastructure exposed)

```
Activate beta access
  → Connect your AI
  → choose a supported provider / model
  → paste API key
  → Test connection
  → start Capture
```
No Backend URL, VPS guidance, Docker, shared provider key, or runtime plumbing appears anywhere.

## Open questions for codex (ratify before Phase 1)

1. Token refresh vs. re-activate; `expiresAt` duration.
2. Final header names (`Authorization`, `X-Sift-Installation`, `X-Provider-Key`).
3. State of `ownerId` scoping in the existing migrations (the owner + idempotency tables
   already exist on trunk per `test_migrations`); confirm all read/write paths filter by it.
4. Provider-key redaction strategy across logging / tracing / error handling.
5. Activation: invite codes pre-seeded vs. generated; one-time vs. reusable.
