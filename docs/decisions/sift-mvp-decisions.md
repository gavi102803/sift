# Sift MVP Decisions

**Date**: 2026-06-22
**Status**: Accepted for MVP

## Product Scope

MVP focuses on the core loop:

```text
capture locally -> generate initial concept card -> browse concept library
-> continue asking under the same concept -> update note through validated patches
```

Deferred:

- Foreground model selection.
- App Intents and Shortcuts.
- Multi-device realtime sync.
- Daily review or spaced repetition.
- Public sharing or collaboration.
- Complex knowledge graph visualization.

## iOS Target

Decision:

- Target iOS 17+.
- Use SwiftUI, SwiftData, and Observation-era SwiftUI patterns.
- Use native `NavigationStack` per tab.
- Use local SwiftData persistence for draft recovery and offline-visible concept state.

Rationale:

- SwiftData and the Observation model reduce boilerplate for the local-first MVP.
- The app needs reliable local draft persistence before any network/model call.
- Supporting iOS 16 would force extra state ownership and persistence compatibility work too early.

## iOS Dependencies

Decision:

- Required: SwiftUI.
- Required: SwiftData.
- Required: URLSession-based Sift API client.
- Required if streaming ships in MVP: URLSession/SSE streaming support.
- Required: MarkdownUI for read-only Markdown rendering in AI answers and follow-up history.

Not used in production iOS:

- OpenAI Swift SDKs.
- Anthropic SDKs.
- Gemini SDKs.
- LiteLLM direct client access.
- OpenAI Agents SDK, Claude Agent SDK, Codex runtime, or Claude Code runtime.

Rationale:

- iOS should not hold upstream provider API keys.
- Sift domain models must not inherit provider SDK DTOs.
- MarkdownUI helps render rich model answers while keeping `ConceptNote` as structured `NoteBlock` data.

## Backend Stack

Decision:

- Use Python FastAPI for Sift Backend.
- Use Pydantic for request/response schemas and structured model output validation.
- Use PostgreSQL as the authoritative server database.
- Use SQLAlchemy for persistence.
- Use Alembic for migrations.
- Use pytest for backend tests.

Rationale:

- FastAPI and Pydantic are a good fit for schema-first API design and strict model-output validation.
- Python keeps backend development close to LiteLLM's ecosystem.
- PostgreSQL is a mature default for relational concept, revision, event, and proposal data.
- Alembic gives explicit migrations once the data model stabilizes.

## Model Gateway

Decision:

- Use self-hosted LiteLLM Proxy behind Sift Backend.
- Do not expose LiteLLM directly to iOS.
- Sift Backend calls model aliases, not upstream model names.

Initial aliases:

```text
sift-explain
sift-curate
sift-fast
```

Initial provider strategy:

- Configure both OpenAI and Anthropic in LiteLLM when keys are available.
- Enable only one default model path in MVP user flows.
- Use `sift-explain` for user-facing answers.
- Use `sift-curate` for update decisions, patch generation, topic/tag suggestions, relation suggestions, and `CardMemory` updates.
- Keep `sift-fast` reserved for low-latency classification/deduplication later.

Rationale:

- LiteLLM gives multi-provider capability without making the app a multi-model client.
- Model aliasing lets the product change providers without changing business code.
- Separating explanation from curation keeps future multi-model support from corrupting note merges.

## API Key Strategy

Decision:

- Provider API keys are backend/LiteLLM-managed only.
- iOS stores no upstream provider keys.
- Local development uses `.env`/local config ignored by Git.
- Production should use managed secrets in the hosting environment.

Rationale:

- Prevents key extraction from the iOS app.
- Lets the backend enforce auth, quota, cost logging, and fallback policy.

## Sift Backend API Surface

Initial endpoints:

```text
GET  /health
POST /v1/concepts
POST /v1/concepts/{conceptId}/turns
POST /v1/update-proposals/{proposalId}/merge
POST /v1/update-proposals/{proposalId}/dismiss
```

MVP behavior:

- iOS creates or stores a local draft before calling `/v1/concepts`.
- Backend validates structured model output before returning generated note data.
- Backend applies patch operations only after checking note revision, block existence, old value hash, and user lock status.
- Backend creates `NoteRevision` and `UpdateEvent` for every note mutation.

## Data Ownership

Decision:

- iOS stores local copies for fast UI, draft recovery, and offline visibility.
- Backend is authoritative for AI-generated concepts, conversations, patch application, revisions, update events, and model telemetry.

Rationale:

- The app must not lose user captures during network failures.
- The backend must own validation and merge safety because it owns model calls and authoritative revision history.

## Voice Input

Decision:

- Defer voice input until after the text capture path is reliable.

Rationale:

- The MVP promise is "capture in seconds", but text capture plus local persistence is the core reliability test.
- Voice adds permissions, transcription, error states, and UX polish that can distract from the main loop.

## Open-Source Reuse

Directly introduce:

- MarkdownUI for read-only Markdown rendering.
- LiteLLM Proxy for the model gateway.

Borrow patterns only:

- MacPaw/OpenAI and SwiftOpenAI for OpenAI-compatible DTO/streaming ideas.
- openai-structured-outputs-samples for schema and fixture strategy.
- clean-architecture-swiftui for feature organization and tests.
- Ayna for streaming and provider abstraction ideas.

Do not introduce:

- Exyte/Chat.
- ChatGPTSwiftUI as an architecture baseline.
- SwiftUI-Notes storage/sync model.
- swift-markdown-engine.
- Agent/coding runtimes.

## Validation Before Sprint 1

Sprint 1 can start when:

- This decision file is committed.
- `docs/research/open-source-notes.md` exists.
- The implementation branch exists.
- The backend stack choice is no longer open.
- The iOS target is no longer open.

## Source References

- Apple SwiftData: https://developer.apple.com/documentation/SwiftData
- Apple NavigationStack: https://developer.apple.com/documentation/SwiftUI/NavigationStack
- FastAPI documentation: https://fastapi.tiangolo.com/
- Pydantic documentation: https://docs.pydantic.dev/
- SQLAlchemy documentation: https://docs.sqlalchemy.org/
- Alembic documentation: https://alembic.sqlalchemy.org/
- LiteLLM documentation: https://docs.litellm.ai/
- MarkdownUI: https://github.com/gonzalezreal/swift-markdown-ui
- OpenAI Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
