# Sift Runtime Trust and Ownership Hardening

Date: 2026-06-27

This phase keeps Sift Hermes-informed, not Hermes-vendored. Sift owns runtime policy,
knowledge mutation policy, persistence, credentials, and product semantics.

## Runtime Trust

- Stable definition and explanation prompts default to `notNeeded` retrieval.
- Source, citation, verify, official, latest, policy, version, pricing, and similar
  prompts route to `recommended` or `required` retrieval.
- Required retrieval blocks generation if search or readable extraction cannot provide
  source text.
- Retrieved content is passed as delimited evidence JSON with `sourceId`, not as free-form
  instructions.
- Model citations must reference runtime-provided `sourceId`; backend rejects citations
  outside the current retrieval context.
- Retrieval evidence is no longer placed in a `system` message. Runtime policy stays in
  `system`; evidence JSON is inserted as a separate data-shaped `user` message before the
  real user query.
- Runtime does not auto-attach every retrieved source to an answer. The model selects
  source IDs, and the runtime fills title/URL from the current evidence universe.
- Runtime now distinguishes `searchDiscovered` from `sourceRead`. Source reading is not
  treated as fact verification.

## Citation and Claim Provenance

- Answer citations are model-selected runtime `sourceId` values; model-supplied title and
  URL are overwritten by runtime evidence metadata.
- If retrieval is absent, citations must be empty and the source type must remain
  `modelKnowledge` or `userProvided`.
- Follow-up candidate claims can use `candidateUpdate.sourceIds` to reference runtime
  source IDs.
- Source-backed claims are persisted only when each source ID maps to a persisted Source
  UUID for the current turn.
- Model-only claims do not inherit answer citations.

## Outbound Safety

- Readability extraction validates scheme, port, DNS results, redirect targets, content
  type, body size, and timeout before treating a URL as readable evidence.
- Extraction never allows localhost, private, link-local, multicast, unspecified, reserved,
  or cloud metadata IP targets.
- Custom model endpoints use the same URL/IP safety utility. Production rejects local/LAN
  targets by default.
- Development can explicitly allow a local custom model endpoint with
  `SIFT_ALLOW_LOCAL_MODEL_ENDPOINT=true`; this escape hatch applies only to provider
  `custom`, never to first-party named providers or web extraction.

## Capability Probe and Cache

- `jsonSchema`, `jsonObject`, and `promptAndValidate` probes now use distinct wire behavior.
- `promptAndValidate` sends no `response_format` and validates parsed JSON locally.
- Capability cache keys include provider, base URL fingerprint, protocol driver version,
  payload mapper version, schema version, probe version, and model.
- Cache records include `createdAt`, `expiresAt`, and `lastFailureKind`.
- Custom endpoint capability is endpoint-specific and does not leak across base URLs.

## Backend Ownership and Idempotency

- Initial capture writes backend-authoritative initial user and assistant turns.
- `CaptureAttempt` persists idempotency state for `POST /v1/concepts`.
- Generic idempotency records protect follow-up turn, streamed turn, and proposal merge
  endpoints from duplicate Concept, Turn, or patch writes.
- `CurrentPrincipal` and `DevelopmentPrincipalProvider` introduce an explicit owner boundary.
- Concepts now carry `owner_id`; service list/get/update paths filter by principal owner.

## Migration and CI

- Alembic revision `20260627_0008` adds `owner_id`, `capture_attempts`, and
  `idempotency_records`.
- Migration smoke tests run Alembic to head against SQLite.
- PR CI runs backend ruff, pytest, migration smoke, and iOS build/tests.
- Manual/scheduled live conformance emits a machine-readable provider artifact without
  printing credentials.

## Known Gaps

- Production authentication is not implemented; only the explicit development principal
  exists.
- Full PostgreSQL migration smoke should be wired once CI has a service database.
- Credential storage still supports local development stores; production KMS/Vault remains
  a release gate.
- Event replay for streamed idempotent turns is not implemented; repeated stream requests
  return the terminal result without re-running the model.
