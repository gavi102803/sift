# Managed BYOK Closed Beta — Client ↔ Backend Contract

**Status: IMPLEMENTED for internal beta validation. Production hosting and real-device release
evidence remain release gates.**
This document defines the client/backend contract for the hosted beta path.
It is separate from Phase 0 Personal Tailnet Dogfood.

## Product form (locked)

```
User: install Sift → activate beta → connect own AI provider → paste own API key → use.
Sift: one managed, public, HTTPS Runtime backend that we operate.
      Users never see backend URL / VPS / Docker / runtime config.
      Users pay their own provider (BYOK); we do not fund or meter inference.
```

## 1. Backend endpoint

- A single fixed managed beta endpoint, e.g. `https://beta.sift.example`
  until the real domain is assigned.
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
- `betaAccessToken` is an opaque bearer token with a 30-day TTL.
- Client refreshes when fewer than 7 days remain:
  `POST /v1/beta/session/refresh` with `Authorization` and
  `X-Sift-Installation` → `{ betaAccessToken, ownerId, expiresAt }`.
- Refresh succeeds only for a valid, unexpired, unrevoked token.
- Expired tokens are not refreshed; the client returns to activation.
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
  → sent per runtime request in `X-Sift-Provider-Key` over TLS
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
- Provider keys are accepted only on runtime/provider-test endpoints that need
  them; other endpoints reject or ignore the header.
- Backend request logs must record only provider id, model, owner id, request id,
  and redacted credential preview (`***last4`) when a preview is unavoidable.

## 5. Providers / models supported in beta

- The beta uses the current Sift provider preset registry and capability policy.
- Do **not** artificially reduce the provider set in this contract. If a provider
  is present in the Sift runtime catalog and supports BYOK relay + connection
  test, it can be exposed.
- Providers without a working relay/test path are hidden by the provider catalog
  response, not by hard-coded iOS lists.
- The provider catalog endpoint returns provider id, display name, default base
  URL, auth mode, supported models or model-list behavior, and feature flags.

## 6. Provider connection test

- `POST /v1/providers/test { providerId, baseURL?, model }` with the key in
  `X-Sift-Provider-Key`.
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

All errors return:

```json
{
  "error": {
    "code": "provider_unreachable",
    "message": "Safe user-facing summary",
    "requestId": "..."
  }
}
```

`message` must never include provider API keys, Authorization headers, raw
provider response bodies containing secrets, or backend stack traces.

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

## 9. Invite Semantics

- Invite codes are pre-seeded or generated by an admin script for the closed beta.
- Each invite code can create exactly one `ownerId`.
- Re-entering the same code on the same installation may return the same owner
  session if the code has not been administratively revoked.
- Reusing the same code from a different installation returns `invite_consumed`
  unless the invite has been explicitly reset.

## 10. Implementation Gates

Phase 1 cannot ship until:

- every concept/turn/source/run/idempotency read and write is filtered by
  server-derived `ownerId`;
- cross-owner concept and turn ids return `404`;
- provider key redaction is covered by tests for logs, exceptions, and API
  responses;
- provider test confirms the key is not persisted;
- Release/TestFlight hides Backend URL controls;
- activation and refresh endpoints return the exact error codes in this contract.
