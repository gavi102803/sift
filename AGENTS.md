# Sift Engineering Instructions

These instructions apply to the whole repository. More specific `AGENTS.md` files may add
constraints for a subtree, but must not weaken the product invariants or dependency rules below.

## Working Principles

- Make the smallest change that satisfies the request. Do not mix feature work with unrelated
  cleanup or a broad architecture migration.
- Before coding, state assumptions and define a verifiable success condition. If behavior is
  ambiguous and the choice changes product semantics, ask before implementing.
- Preserve the local-first product promise: save a capture or question before starting fallible
  network or model work, and keep it recoverable after failures.
- Treat the backend as authoritative for AI-generated concepts, conversation history, note
  mutations, revisions, proposals, provenance, and owner scope. Treat iOS as authoritative only
  for local drafts and explicitly device-local organization.
- AI output must not mutate durable knowledge until it has passed schema validation and the
  revision, hash, target, and user-lock checks required by the domain.
- Do not expose provider secrets in source, Git, logs, analytics, errors, fixtures, snapshots, or
  API responses. Production credentials require the security design documented in
  `docs/contracts/managed-byok-beta.md`.

## Frontend Architecture: Feature-Sliced Design

The iOS app under `ios/` is the frontend. New frontend code must follow an iOS adaptation of
Feature-Sliced Design (FSD). FSD is a dependency and ownership model, not a reason for a one-shot
folder rewrite.

### Target layers

From highest to lowest:

1. `App` — composition root, app lifecycle, dependency injection, root routing, global theme.
2. `Pages` — route-level screen composition; pages coordinate widgets and features but contain no
   reusable business rules.
3. `Widgets` — substantial reusable UI compositions made from features and entities.
4. `Features` — user actions and use cases such as capture, retry, follow-up, edit note, manage
   relation, or configure provider.
5. `Entities` — frontend representations and presentation rules for concepts, turns, proposals,
   providers, and other domain nouns.
6. `Shared` — domain-neutral UI primitives, API transport, persistence primitives, utilities, and
   generated resources.

Create a layer only when the change needs it. A small feature does not require every layer.

### Dependency rules

- Dependencies point downward only: `App -> Pages -> Widgets -> Features -> Entities -> Shared`.
- A lower layer must never import or refer to a higher layer.
- Slices at the same layer must not reach into each other's internals. Put genuinely shared domain
  behavior in `Entities` and domain-neutral behavior in `Shared`.
- Each slice exposes a small public surface. Do not couple callers to another slice's private views,
  state, helpers, or persistence details.
- Provider/API DTOs stay at the transport boundary. Map them to entity or feature state before UI
  composition when behavior is attached to the data.
- SwiftUI views render state and emit user intent. Do not put URLSession calls, stream parsing,
  SwiftData mutation policy, note merge rules, or credential policy directly in `body` or page
  helpers.
- Feature state owns one user interaction. App-wide mutable state requires an explicit documented
  reason; do not introduce a global store by default.

### Migration from the current layout

- Existing `Record`, `Library`, `ConceptDetail`, and `Profile` folders contain a mixture of pages,
  features, and entities. Do not move them wholesale merely to satisfy naming.
- New slices should use the target layers. When changing an existing large file, extract only the
  coherent behavior needed by that change and leave unrelated code untouched.
- `API` and low-level persistence mechanisms migrate toward `Shared`; domain models and rules migrate
  toward `Entities`; user operations migrate toward `Features`; route screens migrate toward
  `Pages`.
- Until layers become separate Swift modules, enforce boundaries through folder ownership, public
  interfaces, review, and tests. Do not use the single Xcode target as permission for arbitrary
  cross-layer access.

### Frontend verification

- Unit-test entity rules and feature state transitions without rendering full screens.
- Test API mapping, streaming terminal states, local persistence, idempotency, and failure recovery.
- Add UI tests for critical cross-feature journeys; previews are visual aids, not release evidence.
- Any capture or follow-up change must prove that input survives network failure and relaunch.

## Backend Architecture: Domain-Driven Design

The Python service under `backend/` must evolve through pragmatic DDD. Use bounded contexts and
ports where they protect product rules; do not create ceremonial abstractions around simple CRUD.

### Bounded contexts

Use these current context boundaries unless a design record justifies a change:

- `concepts` — capture lifecycle, concept cards, conversations, organization, and relations.
- `knowledge_mutation` — note blocks, revisions, locks, patches, proposals, and audit events.
- `model_runtime` — provider protocols, capability policy, retrieval, structured generation, and
  provenance. It supplies results; it does not own concept truth.
- `identity_access` — principals, authentication, owner scope, activation, and credentials.

Cross-context collaboration goes through explicit application ports, identifiers, or events. Do not
import another context's ORM records or modify its tables directly.

### Layers and dependency direction

Within a context, use:

- `domain` — aggregates, entities, value objects, domain services, policies, and domain errors.
- `application` — use cases, commands/queries, transaction boundaries, and ports.
- `infrastructure` — SQLAlchemy repositories, model/web provider adapters, credential stores, and
  other port implementations.
- `interfaces` — FastAPI routes, request/response schemas, streaming encoders, and error mapping.

Dependencies point inward: `interfaces` and `infrastructure` may depend on `application`; application
depends on `domain` and port protocols; domain depends on none of FastAPI, Pydantic, SQLAlchemy,
HTTPX, or provider SDK details. The composition root wires implementations to ports.

### Domain rules

- Use the product's ubiquitous language consistently: Concept, Capture Attempt, Turn, Note Block,
  Note Revision, Update Proposal, Source, Claim, and Learning State.
- Put invariants on the aggregate or domain policy that owns them. HTTP handlers and repositories
  must not independently reimplement merge, owner-scope, or lock rules.
- Domain and application code raise typed domain/application errors. The interface layer maps them
  to HTTP status and stable public error codes; domain code must not raise `HTTPException`.
- Repositories return domain objects and are defined as application ports. They do not import API
  DTOs or application service implementations.
- A use case defines one atomic transaction. Note content, revision, and update event must commit or
  roll back together.
- Every owner-scoped read and write derives owner identity from the authenticated principal, never
  from a client-supplied owner ID.
- Provider adapters may vary by protocol, but capability differences stay behind runtime ports and
  must not leak into concept business rules.

### Migration from the current layout

- Do not perform a big-bang rewrite of `ConceptService`, `PersistentConceptStore`, or runtime code.
- New backend behavior should enter through an application use case and a port. When modifying an
  existing oversized service, extract only the relevant invariant or use case and protect it with
  characterization tests first.
- Remove a legacy path only after all callers have moved and equivalent tests pass.
- Transport aliases and backward compatibility belong in interface schemas, not domain objects.

### Backend verification

- Domain tests cover invariants without FastAPI, SQLAlchemy, filesystem, network, or model calls.
- Application tests use in-memory fakes for ports and cover success, rejection, retry, idempotency,
  and transaction behavior.
- Adapter tests cover persistence migrations, owner isolation, secret redaction, provider payloads,
  streaming, and outbound network safety.
- API contract tests verify stable status codes and response/error shapes.

## Definition of Done

A change is complete only when:

- every changed line traces to the requested behavior;
- relevant automated tests and lint pass from the same working directory used by CI;
- architecture dependencies still follow the FSD or DDD direction above;
- product invariants, owner scope, idempotency, provenance, and secret handling are preserved;
- user-facing behavior and operational contracts are documented when they changed; and
- unfinished release gates are described honestly as planned or partial, never as implemented.
