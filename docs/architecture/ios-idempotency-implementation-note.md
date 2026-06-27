# iOS Idempotency — Implementation Note (design only)

Status: **design for review — no code yet.**
Scope: iOS client only. The backend already reads `Idempotency-Key` and
maintains `CaptureAttempt` / idempotency records keyed by `(owner, endpoint,
key)`. iOS currently never sends the header, so network retries can still
double-create a Concept or double-submit a turn.

## 1. Semantics (the contract)

```
Capture / Follow-up / Stream retry / Proposal merge
  → one idempotency key per USER ACTION (not per network call)
  → the key is reused on every retry of that action
  → sent as request header: Idempotency-Key: <uuid>
```

A "user action" = one tap of Capture send / Follow-up send / Confirm update.
The key must survive app relaunch, so it is **persisted with the operation's
local state**, not held in view/page memory. No "alive only while this screen
exists" pseudo-idempotency.

Non-goals: no client-side dedup logic (the backend owns dedup); no change to
when/what the backend persists; no new endpoints.

## 2. Durability finding

There is **no** field on any iOS SwiftData model today that can hold an
operation key (`grep` for idempotency/attempt/operationKey → none). Therefore a
**minimal model change is required** — durable idempotency is not achievable
without it. Proposed minimal addition: three optional `String?` properties (one
per operation type), each defaulting to `nil`:

| Operation | Key lives on | New field |
|---|---|---|
| Capture / generation (`createConcept`) | the draft `Concept` | `Concept.captureIdempotencyKey: String?` |
| Follow-up / stream (`submitTurn`/`streamTurn`) | the pending/failed `ConversationMessage` | `ConversationMessage.idempotencyKey: String?` |
| Proposal merge (`mergeProposal`) | the `ConceptUpdateProposal` | `ConceptUpdateProposal.mergeIdempotencyKey: String?` |

Optional properties with a `nil` default are a **SwiftData lightweight
migration** (no manual migration step, no data loss). These models live under
`ios/Sift/Persistence/Models/**`, which codex owns — see §6 coordination.

## 3. Per-operation flow

### Capture / generation
- `ConceptLocalStore.createDraft(...)` generates `captureIdempotencyKey = UUID().uuidString` and stores it on the draft `Concept`.
- `CaptureFlowService.generateConcept` / `retryGeneration` read `draft.captureIdempotencyKey` and pass it to `apiClient.createConcept(_:idempotencyKey:)`.
- Retrying a `generationFailed` draft reuses the **same** stored key (the field is set once at draft creation, never regenerated on retry).

### Follow-up + stream retry (same key)
- When the user sends a follow-up, generate a key for that action.
- On failure, `recordFailedFollowUpDraft` stores the key on the failed
  `ConversationMessage` (alongside the existing `failed` marker).
- "Retry it" (the restored composer draft) reuses the stored key; a fresh send
  generates a new key.
- Header goes on `submitTurn` / `streamTurn`.

### Stream no-delta-replay (must handle)
The backend guarantees only a **terminal** result on a duplicate stream — it
does **not** replay intermediate deltas. The current consumer already tolerates
this: `submitFollowUp` ultimately uses `finalResponse` from the `completed`
event and calls `replaceAssistantAnswer(response.answer, …)`, so a zero-delta
stream still fills the assistant turn from `response.answer`. **No behavioural
change needed** — only confirm the empty optimistic assistant bubble is always
replaced by `response.answer` (it is) and that a terminal-only stream is not
treated as an error.

### Proposal merge
- When the user taps **Confirm update**, generate/read
  `proposal.mergeIdempotencyKey` and pass to `apiClient.mergeProposal(id:idempotencyKey:)`.
- A retry of the same confirmation reuses the stored key.

## 4. Header plumbing (explicitly NOT in generic `post()`)

Do **not** inject a UUID inside the shared `HTTPSiftAPIClient.post()` /
`streamPost()` — that would attach a *new* key to unrelated/internal requests
and break dedup. Instead:

- Add an explicit `idempotencyKey: String?` parameter to the four protocol
  methods only: `createConcept`, `submitTurn`, `streamTurn`, `mergeProposal`.
- Thread it into `post()`/`streamPost()` as an optional `headers:` argument, set
  `Idempotency-Key` only when non-nil. All other callers pass `nil`.

## 5. Affected files

iOS-owned (I can implement):
- `ios/Sift/ConceptDetail/ConceptDetailView.swift` — pass keys for follow-up (`submitTurn`/`streamTurn`) and `mergeProposal`.
- `ios/Sift/ConceptDetail/ConceptDetailPreviews.swift` — update `PreviewSiftAPIClient` signatures.

Coordinate with codex (their domain — DTO/contract + persistence models):
- `ios/Sift/API/SiftAPIClient.swift` — add `idempotencyKey:` to 4 protocol methods + `HTTPSiftAPIClient` header plumbing.
- `ios/Sift/API/MockSiftAPIClient.swift` — signature updates.
- `ios/Sift/Persistence/Models/ConceptModels.swift` / `ConversationModels.swift` / `ProposalModels.swift` — +1 optional field each.
- `ios/Sift/Persistence/ConceptLocalStore.swift` — generate/persist/read keys in `createDraft`, `recordFailedFollowUpDraft`, merge path.
- `ios/Sift/Record/CaptureFlowService.swift` — pass `draft.captureIdempotencyKey` to `createConcept`.

No backend, no provider/runtime, no new DTO fields on the wire (the key is a
header, not a body field).

## 6. Coordination ask (codex)

Because the API protocol/clients and the SwiftData models are codex-owned, the
cleanest split is:
- codex (or a jointly-reviewed PR): the 4 protocol-method signature changes +
  header plumbing + 3 optional model fields + store/CaptureFlowService wiring.
- iOS (me): the call-site changes in ConceptDetailView + previews, and the
  regression tests.

Open question for codex: confirm the backend's turn idempotency is scoped per
`(owner, endpoint, key)` so the **same** follow-up key reused across
`submitTurn` and `streamTurn` of the *same* action is treated as one operation
(not two). If the two endpoints share a record, one key per follow-up action is
correct; if not, we scope keys per endpoint.

## 7. Test plan

- Unit: key is stable across `generateConcept` → `retryGeneration` (same draft).
- Unit: a fresh follow-up gets a new key; restoring a failed draft reuses it.
- Unit (mock client asserts header): `createConcept`/`submitTurn`/`mergeProposal`
  send the stored `Idempotency-Key`; unrelated GETs send none.
- Behavioural: a terminal-only stream (no deltas) still resolves the assistant
  turn from `response.answer` and is not surfaced as an error.
