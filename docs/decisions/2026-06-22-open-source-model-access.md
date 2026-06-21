# ADR: Open-Source Dependencies and Model Access

**Date**: 2026-06-22
**Status**: Accepted

## Context

Sift's core product is not a general agent runtime, coding agent, or multi-model chat client. The durable domain objects are:

- `Concept`
- `ConceptNote`
- `Conversation`
- `CardMemory`
- `NoteRevision`
- `UpdateProposal`
- `UpdateEvent`

Provider sessions, remote thread IDs, and SDK-specific conversation objects may be useful implementation details, but they must not become the product's memory source.

## Decision

Sift will not reuse Codex, Claude Code, OpenAI Agents SDK, or Claude Agent SDK as the production runtime.

Production model access will use:

```text
iOS App
  -> Sift Backend
  -> Self-hosted LiteLLM Proxy
  -> OpenAI / Anthropic / Gemini / other providers
```

The iOS app must not hold upstream provider API keys. It calls only Sift Backend APIs.

Sift Backend owns:

- Authentication and quota controls.
- Context pack construction.
- LiteLLM calls through model aliases.
- SSE streaming to the iOS app.
- Structured output validation.
- Patch/merge rules.
- Update proposal creation.
- Model, token, latency, cost, and failure logging.

LiteLLM owns:

- Multi-provider API normalization.
- Provider key management.
- Model aliases.
- Provider fallback configuration.
- Unified provider errors where possible.

Recommended model aliases:

```text
sift-explain
sift-curate
sift-fast
```

The business layer should call model aliases, not hard-code upstream provider model names.

## MVP Model Strategy

MVP keeps multi-provider capability in the backend architecture but exposes no foreground model picker.

Initial policy:

```text
explanation model: system default alias
curator model: system default or fixed internal alias
```

The explanation model answers the user's immediate question. The curator model or service produces update decisions, patch operations, tag/topic suggestions, concept relations, and `CardMemory` updates.

Future versions may add internal routing or an advanced "explain with another model" action, but note updates must still pass through Sift's unified curator and patch engine.

## Conversation and Context Rules

One `Concept` card equals one logical Sift conversation. Different concepts are isolated by default.

Do not treat provider fields such as `threadId`, `previous_response_id`, or provider-specific sessions as the only conversation truth. They can be stored as optimization metadata, but Sift continuity must come from the app/backend data layer.

Each model call should construct a context pack:

```text
1. System instructions
2. Concept metadata
3. Current ConceptNote
4. CardMemory
5. Recent 6-10 conversation turns
6. Current user query
7. Strict structured-output schema
```

MVP does not need complex compaction. Store full raw message history in the database, keep current `ConceptNote`, keep `CardMemory`, and update `CardMemory` when context grows too large.

## Structured Output Contract

The backend must not ask models to return arbitrary Markdown and then infer business changes from prose. Concept turns must return a structured contract similar to:

```ts
type ConceptTurnResult = {
  answer: string
  updateDecision: {
    mode: "none" | "autoMerge" | "needsConfirmation"
    reason: string
  }
  autoPatch?: PatchOperation[]
  proposal?: {
    baseNoteRevision: number
    patchOperations: PatchOperation[]
    rationale: string
  }
  relations: ConceptRelationSuggestion[]
  suggestedTags: TagSuggestion[]
  memoryPatch: {
    confirmedUnderstanding?: string[]
    openQuestions?: string[]
    userPreferences?: string[]
  }
  modelMeta: {
    provider: string
    model: string
    latencyMs?: number
    inputTokens?: number
    outputTokens?: number
  }
}
```

Patch operations must be structured operations, not natural-language suggestions:

```ts
type PatchOperation =
  | { operation: "append"; targetBlockId: string; content: string }
  | { operation: "replace"; targetBlockId: string; oldValueHash: string; newContent: string }
  | { operation: "addRelation"; targetConceptId: string; relationType: string }
```

The backend must validate schema, check `baseNoteRevision`, verify target block existence, and respect user-locked blocks before writing changes.

## Dependency Policy

### Directly Introduce

#### MarkdownUI

Use for SwiftUI Markdown rendering in AI answers and follow-up history.

Constraints:

- Do not model the entire `ConceptNote` as one Markdown document.
- Keep core notes as structured `NoteBlock` records.
- Do not build a complex Markdown editor in MVP.
- Avoid reparsing long streaming text on every token.

#### LiteLLM Proxy

Use as the self-hosted model gateway.

Constraints:

- Do not expose LiteLLM directly to iOS.
- Route all app traffic through Sift Backend.
- Use aliases such as `sift-explain`, `sift-curate`, and `sift-fast`.

### Borrow Patterns, Do Not Fork

#### MacPaw/OpenAI and SwiftOpenAI

Use as references for OpenAI-compatible Swift modeling, streaming transport ideas, and temporary client-side prototypes only.

Constraints:

- Production iOS does not hold upstream model API keys.
- SDK DTOs must not become Sift domain models.
- If the backend is not Swift, these are not production backend dependencies.

#### openai-structured-outputs-samples

Use as a reference for JSON Schema design, strict structured outputs, validation, retry, and fixtures.

#### clean-architecture-swiftui

Borrow feature organization, repositories, dependency injection, and test setup ideas.

Do not copy a heavy global app state, interactor, or Redux-like architecture unless the MVP actually needs it.

#### Ayna

Borrow ideas for provider abstraction, streaming state, OpenAI-compatible endpoints, Keychain/local storage patterns, and native SwiftUI chat interactions.

Do not reuse its multi-model chat product shape, foreground model picker, chat data model, or chat-centered information architecture.

### Do Not Introduce for MVP

- Exyte/Chat.
- ChatGPTSwiftUI as an architecture baseline.
- SwiftUI-Notes storage/sync patterns.
- swift-markdown-engine.
- Codex CLI, Codex app-server, Claude Code runtime, or coding-agent runtimes.
- OpenAI Agents SDK or Claude Agent SDK as the product runtime.

## Non-Negotiable Architecture Rules

1. iOS does not store upstream provider API keys.
2. LiteLLM is never directly exposed to the client.
3. Provider sessions are not product conversation truth.
4. `ConceptNote + CardMemory + Conversation` are the long-term context source.
5. AI answers and note updates are separate.
6. AI cannot overwrite user-edited content without validation and explicit rules.
7. Automatic merges must record `UpdateEvent` and `NoteRevision`.
8. All model outputs pass through unified schema validation.
9. Multi-provider support must not turn MVP into a general chat client.
10. The product center is the growing `Concept` card, not a chat thread.

## Sources

- LiteLLM documentation: https://docs.litellm.ai/
- MarkdownUI: https://github.com/gonzalezreal/swift-markdown-ui
- OpenAI Structured Outputs: https://platform.openai.com/docs/guides/structured-outputs
- Apple SwiftData: https://developer.apple.com/documentation/SwiftData
