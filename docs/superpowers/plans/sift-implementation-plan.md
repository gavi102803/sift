# Plan: Sift MVP Implementation

**Generated**: 2026-06-22
**Estimated Complexity**: High

## Overview

Build Sift as a local-first iOS app that captures new concepts quickly, saves the raw capture before any AI call, generates progressive concept notes, and lets each concept card grow through a Sift-owned logical conversation.

The implementation should start with a narrow MVP:

- SwiftUI app shell with Record, Concept Library, and Profile tabs.
- SwiftData persistence for captures, concepts, notes, revisions, conversations, messages, tags, topics, relations, and update events.
- One system-managed default AI model behind a provider-agnostic adapter.
- Structured AI responses that separate answering from note updates.
- Revision-aware patch proposals for significant changes.
- No App Intents, multi-model UI, sync, sharing, or spaced repetition in MVP.

## Open-Source Research

Yes, we should look at related open-source projects before implementation, but only for targeted patterns:

- AI chat clients: streaming, provider abstraction, retry/error states, message persistence.
- SwiftData note/sample apps: model design, queries, search, list performance.
- Markdown or rich text renderers: note block rendering and editing trade-offs.
- Local-first note apps: export, persistence boundaries, and offline behavior.

Do not copy their product architecture directly. Sift's hard part is not chat UI; it is the reliable growth of a concept card through `ConceptNote`, `Conversation`, `CardMemory`, `NoteRevision`, `UpdateEvent`, and patch-based merges.

Initial references to review:

- Apple SwiftData documentation: https://developer.apple.com/documentation/SwiftData
- Apple SwiftUI NavigationStack documentation: https://developer.apple.com/documentation/SwiftUI/NavigationStack
- Apple App Intents documentation for post-MVP planning: https://developer.apple.com/documentation/AppIntents
- OpenAI Responses API documentation: https://platform.openai.com/docs/api-reference/responses
- OpenAI Structured Outputs guide: https://platform.openai.com/docs/guides/structured-outputs
- Swift Markdown package: https://github.com/swiftlang/swift-markdown
- MarkdownUI for SwiftUI rendering: https://github.com/gonzalezreal/swift-markdown-ui

Research output should be a short `docs/research/open-source-notes.md` file with:

- What project was reviewed.
- What pattern is worth borrowing.
- What should not be copied.
- Any license concern.

## Prerequisites

- macOS with current Xcode and iOS Simulator for build and runtime validation.
- iOS deployment target decision, recommended iOS 17+ for SwiftData and Observation.
- One default model/provider decision for MVP.
- API key handling decision: user-provided key, app-managed key, or local mock only during early development.
- Network access for AI calls.
- Git branch for implementation work, recommended `codex/sift-mvp`.

## Sprint 0: Research and Project Decisions

**Goal**: Avoid avoidable architecture churn before scaffolding the app.

**Demo/Validation**:

- `docs/research/open-source-notes.md` exists.
- Final decisions are recorded in `docs/decisions/sift-mvp-decisions.md`.

### Task 0.1: Review open-source AI chat clients

- **Location**: `docs/research/open-source-notes.md`
- **Description**: Review 2-3 SwiftUI AI chat/client projects for streaming, provider adapters, message persistence, cancellation, retries, and error UI.
- **Dependencies**: None
- **Acceptance Criteria**:
  - At least two candidate projects reviewed.
  - Each review lists useful patterns and rejected patterns.
  - License is noted.
- **Validation**:
  - Research notes are concise and actionable.

### Task 0.2: Review SwiftData note/list examples

- **Location**: `docs/research/open-source-notes.md`
- **Description**: Review SwiftData note or sample apps for schema design, query usage, searchable lists, and relationship modeling.
- **Dependencies**: None
- **Acceptance Criteria**:
  - At least two examples reviewed.
  - Query/list pitfalls are noted.
- **Validation**:
  - Notes explicitly map findings to Sift's `Concept`, `Tag`, `Topic`, and relation screens.

### Task 0.3: Decide MVP platform and provider constraints

- **Location**: `docs/decisions/sift-mvp-decisions.md`
- **Description**: Record deployment target, default model/provider, API key strategy, and whether voice input ships in MVP.
- **Dependencies**: Tasks 0.1, 0.2
- **Acceptance Criteria**:
  - Decisions are specific enough to scaffold the app.
  - Deferred items are explicitly marked.
- **Validation**:
  - No implementation task depends on an unresolved platform/provider choice.

## Sprint 1: App Scaffold and Local Persistence

**Goal**: Create a runnable iOS app with local-first data models and a navigable shell.

**Demo/Validation**:

- App launches in Simulator.
- Record, Concept Library, and Profile tabs are visible.
- A local sample concept can be seeded and displayed.
- Unit tests validate model creation.

### Task 1.1: Create Xcode project

- **Location**: `Sift/`, `Sift.xcodeproj`
- **Description**: Create a SwiftUI iOS app named Sift with SwiftData enabled.
- **Dependencies**: Task 0.3
- **Acceptance Criteria**:
  - Project builds from Xcode.
  - App target and test target exist.
  - Bundle name and display name are Sift.
- **Validation**:
  - Run app in iOS Simulator.

### Task 1.2: Add app shell

- **Location**: `Sift/App/SiftApp.swift`, `Sift/App/AppView.swift`, `Sift/App/AppTab.swift`
- **Description**: Implement TabView with Record, Concept Library, and Profile tabs. Use per-tab NavigationStack.
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Three tabs render.
  - Each tab has a stable navigation root.
  - Feature views are placeholders only.
- **Validation**:
  - Build succeeds.
  - Manual simulator check confirms tabs work.

### Task 1.3: Define SwiftData models

- **Location**: `Sift/Persistence/Models/`
- **Description**: Add SwiftData models for `Concept`, `ConceptNote`, `NoteBlock`, `NoteRevision`, `UpdateEvent`, `Conversation`, `ModelThread`, `ConversationMessage`, `ConceptUpdateProposal`, `AnswerSource`, `Tag`, `ConceptTag`, `Topic`, `ConceptTopic`, and `ConceptRelation`.
- **Dependencies**: Task 1.1
- **Acceptance Criteria**:
  - Models match the design spec.
  - Relations avoid duplicate sources of truth.
  - Capture status and proposal status are enums.
- **Validation**:
  - Unit tests create, save, fetch, and delete a sample concept graph.

### Task 1.4: Add repository/service layer

- **Location**: `Sift/Persistence/Repositories/`
- **Description**: Add repository methods for creating capture drafts, transitioning capture status, fetching library concepts, adding messages, saving note revisions, and recording update events.
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - UI code does not directly own model mutation logic.
  - Capture draft creation is a single explicit method.
  - Update events are created whenever note data changes.
- **Validation**:
  - Repository unit tests cover draft creation, ready state, failure state, and note revision creation.

## Sprint 2: Record Flow Without AI

**Goal**: Make the core promise true locally: submitting a concept immediately saves it.

**Demo/Validation**:

- User can type a concept, submit it, close/reopen app, and see the saved draft.
- Failed generation can be simulated without data loss.

### Task 2.1: Build Record screen input

- **Location**: `Sift/Record/RecordView.swift`
- **Description**: Implement the minimal capture card, text field/editor, submit button, recent captures, and error/retry state placeholders.
- **Dependencies**: Tasks 1.2, 1.4
- **Acceptance Criteria**:
  - Submit is disabled for empty input.
  - Submit saves raw text locally before any async work starts.
  - Draft appears in recent captures.
- **Validation**:
  - UI test submits "RAG" and verifies a draft exists.

### Task 2.2: Implement capture state transitions

- **Location**: `Sift/Record/CaptureFlowService.swift`
- **Description**: Add state transitions for `draft`, `pendingGeneration`, `generating`, `needsDisambiguation`, `ready`, `generationFailed`, and `archived`.
- **Dependencies**: Task 2.1
- **Acceptance Criteria**:
  - Invalid transitions are rejected or ignored safely.
  - Failure leaves the raw capture recoverable.
- **Validation**:
  - Unit tests cover success, failure, retry, and archive transitions.

### Task 2.3: Add duplicate/disambiguation placeholder

- **Location**: `Sift/Record/DuplicateConceptResolver.swift`
- **Description**: Implement a simple local title/alias match before AI duplicate detection exists.
- **Dependencies**: Task 2.2
- **Acceptance Criteria**:
  - Exact duplicate title can route to existing concept.
  - Ambiguous match can create a `needsDisambiguation` state.
- **Validation**:
  - Unit tests for exact match, no match, and ambiguous match.

## Sprint 3: Concept Library and Detail UI

**Goal**: Make saved concepts browseable, searchable, editable, and inspectable.

**Demo/Validation**:

- User can browse concepts, search, open detail, edit tags/topics, and read note blocks.

### Task 3.1: Build Concept Library list

- **Location**: `Sift/Library/ConceptLibraryView.swift`
- **Description**: Implement grouped concept list by topic with search and recent sorting.
- **Dependencies**: Tasks 1.3, 1.4
- **Acceptance Criteria**:
  - Concepts can appear under multiple topics.
  - Uncategorized concepts are visible.
  - Search checks title, aliases, one-line explanation, tags, and topics.
- **Validation**:
  - Seed sample data and verify grouping/search in previews and Simulator.

### Task 3.2: Build Concept Detail shell

- **Location**: `Sift/ConceptDetail/ConceptDetailView.swift`
- **Description**: Implement title, maturity, capture status, source/confidence notice, note blocks, related concepts, and follow-up input placeholder.
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Detail page renders ready concepts and failed drafts.
  - User-locked blocks are visually distinguishable in edit mode.
- **Validation**:
  - SwiftUI previews for ready, failed, and empty-note states.

### Task 3.3: Add manual editing

- **Location**: `Sift/ConceptDetail/NoteBlockEditor.swift`, `Sift/Library/TagTopicEditor.swift`
- **Description**: Let users edit note blocks, tags, topics, and accepted/dismissed relations.
- **Dependencies**: Task 3.2
- **Acceptance Criteria**:
  - Manual edits create `NoteRevision` and `UpdateEvent`.
  - Edited blocks default to `isUserLocked = true`.
- **Validation**:
  - Unit tests verify revision and lock creation after manual edit.

## Sprint 4: AI Provider Adapter and Structured Output

**Goal**: Connect one default model through a provider-agnostic interface with mockable structured responses.

**Demo/Validation**:

- App can generate an initial concept card from a real or mocked model.
- Tests run against a mock provider without network access.

### Task 4.1: Define AI adapter contracts

- **Location**: `Sift/AI/AIClient.swift`, `Sift/AI/AIProvider.swift`, `Sift/AI/AIResponseModels.swift`
- **Description**: Define request/response types for initial generation and follow-up responses, including `AnswerSource`, update mode, patch operations, topic/tag suggestions, relation suggestions, and memory patch.
- **Dependencies**: Task 1.3
- **Acceptance Criteria**:
  - Contracts are provider-agnostic.
  - Structured output can be decoded from JSON.
  - Mock provider conforms to the same interface.
- **Validation**:
  - Unit tests decode valid output and reject malformed output.

### Task 4.2: Build context pack builder

- **Location**: `Sift/AI/ContextPackBuilder.swift`
- **Description**: Build the prompt/context package from concept metadata, current note blocks, card memory, recent 6-10 messages, and user query.
- **Dependencies**: Tasks 1.4, 4.1
- **Acceptance Criteria**:
  - Provider sessions are optional.
  - User-locked blocks and source/confidence metadata are included.
  - Output contract is explicit.
- **Validation**:
  - Snapshot tests for context pack shape.

### Task 4.3: Implement default provider

- **Location**: `Sift/AI/Providers/DefaultAIProvider.swift`
- **Description**: Implement the chosen model provider using the adapter contract. Keep API key loading isolated.
- **Dependencies**: Tasks 0.3, 4.1, 4.2
- **Acceptance Criteria**:
  - API key is not hard-coded.
  - Network errors map to recoverable app errors.
  - Timeouts and cancellation are handled.
- **Validation**:
  - Manual generation test in Simulator.
  - Unit tests with mocked transport.

### Task 4.4: Add mock provider for development

- **Location**: `Sift/AI/Providers/MockAIProvider.swift`
- **Description**: Add deterministic initial-card and follow-up responses for previews, UI tests, and offline development.
- **Dependencies**: Task 4.1
- **Acceptance Criteria**:
  - Mock can return success, timeout-like failure, auto-merge, and proposal cases.
- **Validation**:
  - UI tests use mock provider only.

## Sprint 5: Initial Generation Flow

**Goal**: Turn a saved capture draft into a ready progressive concept card.

**Demo/Validation**:

- User submits "RAG"; app saves draft, generates a card, creates note blocks, assigns topics/tags, creates conversation, and shows detail.

### Task 5.1: Implement initial generation service

- **Location**: `Sift/AI/InitialConceptGenerationService.swift`
- **Description**: Call the AI provider for a saved capture, parse structured output, create concept note blocks, conversation, first messages, source, tags, topics, relations, and revisions.
- **Dependencies**: Tasks 2.2, 4.3, 4.4
- **Acceptance Criteria**:
  - Raw capture exists before model call.
  - Generation success transitions capture to `ready`.
  - Generation failure transitions to `generationFailed`.
  - Initial note creates `NoteRevision` and `UpdateEvent`.
- **Validation**:
  - Unit tests for success, malformed output, timeout, and retry.

### Task 5.2: Wire generation into Record UI

- **Location**: `Sift/Record/RecordView.swift`, `Sift/Record/CaptureGenerationViewModel.swift`
- **Description**: Start generation after local save, show progress, handle retry, and route to detail on success.
- **Dependencies**: Task 5.1
- **Acceptance Criteria**:
  - User can leave and return while generation state persists.
  - Failed drafts show retry.
- **Validation**:
  - UI tests for success and failure with mock provider.

## Sprint 6: Follow-Up Conversation and Merge Engine

**Goal**: Let a concept card grow through follow-ups while protecting user edits and note integrity.

**Demo/Validation**:

- User asks a follow-up under a concept.
- App stores message, shows answer, auto-merges small updates, or shows a revision-aware proposal.

### Task 6.1: Implement follow-up service

- **Location**: `Sift/AI/FollowUpService.swift`
- **Description**: Append user message, build context pack, call default provider, save assistant message, update card memory, and hand off update decision.
- **Dependencies**: Tasks 4.2, 5.1
- **Acceptance Criteria**:
  - Follow-ups use the concept's logical conversation.
  - Recent messages and card memory are included.
  - Network failure does not corrupt conversation state.
- **Validation**:
  - Unit tests for successful answer, failed answer, and message persistence.

### Task 6.2: Implement patch operation engine

- **Location**: `Sift/AI/PatchOperationEngine.swift`
- **Description**: Apply append/replace/add-block operations against a base note revision, using hashes for replace safety.
- **Dependencies**: Task 6.1
- **Acceptance Criteria**:
  - Auto-merge cannot replace user-locked blocks.
  - Replace operations verify old value hash.
  - Stale proposals are detected.
- **Validation**:
  - Unit tests cover append, replace, stale base revision, locked block, and invalid target.

### Task 6.3: Build update proposal UI

- **Location**: `Sift/ConceptDetail/UpdateProposalSheet.swift`
- **Description**: Show proposed patch operations, rationale, confidence, stale state, accept, dismiss, and regenerate actions.
- **Dependencies**: Task 6.2
- **Acceptance Criteria**:
  - Accepted proposal creates `NoteRevision` and `UpdateEvent`.
  - Dismissed proposal is retained with dismissed status.
  - Stale proposal cannot be blindly applied.
- **Validation**:
  - UI tests for accept, dismiss, and stale proposal.

### Task 6.4: Wire follow-up input

- **Location**: `Sift/ConceptDetail/ConceptDetailView.swift`, `Sift/ConceptDetail/FollowUpComposer.swift`
- **Description**: Add follow-up input, loading state, answer display, source notice, auto-merge toast, and proposal presentation.
- **Dependencies**: Tasks 6.1, 6.3
- **Acceptance Criteria**:
  - Follow-up input is disabled while submitting.
  - Answer is visible before or alongside merge result.
  - Source/confidence is visible but lightweight.
- **Validation**:
  - Simulator walkthrough with mock provider.

## Sprint 7: Reliability, Search, and Polish

**Goal**: Make the MVP stable enough for daily personal use.

**Demo/Validation**:

- A user can capture, generate, search, follow up, edit, recover failed drafts, and inspect source notices in a clean UI.

### Task 7.1: Improve search and filtering

- **Location**: `Sift/Library/ConceptSearchService.swift`, `Sift/Library/ConceptLibraryView.swift`
- **Description**: Add query normalization, alias search, tag/topic filtering, and recently updated sorting.
- **Dependencies**: Task 3.1
- **Acceptance Criteria**:
  - Search handles title, aliases, tags, topics, and one-line explanation.
  - Filtering works with multi-topic concepts.
- **Validation**:
  - Unit tests for search matching.

### Task 7.2: Add source/confidence UI

- **Location**: `Sift/ConceptDetail/AnswerSourceView.swift`
- **Description**: Show lightweight source labels such as "Generated from model knowledge" or "No external sources cited."
- **Dependencies**: Tasks 4.1, 6.4
- **Acceptance Criteria**:
  - Source label appears on generated answers and note updates.
  - Uncertainty notes are visible when present.
- **Validation**:
  - Previews for model knowledge, user-provided, and verified source states.

### Task 7.3: Add failure recovery paths

- **Location**: `Sift/Record/RecordView.swift`, `Sift/ConceptDetail/ConceptDetailView.swift`
- **Description**: Add retry, archive, and recover flows for failed captures and failed follow-ups.
- **Dependencies**: Tasks 2.2, 5.2, 6.4
- **Acceptance Criteria**:
  - Failed capture can retry or archive.
  - Failed follow-up keeps user question recoverable.
  - Error messages are concise and non-technical.
- **Validation**:
  - UI tests simulate provider failure and recovery.

### Task 7.4: Add accessibility and empty states

- **Location**: `Sift/Record/`, `Sift/Library/`, `Sift/ConceptDetail/`
- **Description**: Add accessibility labels, Dynamic Type checks, empty library state, empty note state, and clear loading states.
- **Dependencies**: Tasks 3.1, 3.2, 6.4
- **Acceptance Criteria**:
  - Buttons and fields have meaningful accessibility labels.
  - Dynamic Type does not break key screens.
  - Empty states do not explain the app in marketing copy.
- **Validation**:
  - Manual accessibility inspector pass.

## Sprint 8: Test Hardening and Release Candidate

**Goal**: Prepare an internal MVP build with confidence in data integrity.

**Demo/Validation**:

- Full smoke test passes on Simulator and device.
- Data integrity tests pass.
- Release checklist is complete.

### Task 8.1: Add end-to-end smoke tests

- **Location**: `SiftUITests/`
- **Description**: Cover capture, generation, library search, detail open, follow-up, proposal merge, manual edit, and failure retry using the mock provider.
- **Dependencies**: Sprints 1-7
- **Acceptance Criteria**:
  - Core happy path has UI test coverage.
  - Failure/retry path has UI test coverage.
- **Validation**:
  - Run UI tests locally.

### Task 8.2: Add data integrity tests

- **Location**: `SiftTests/DataIntegrityTests.swift`
- **Description**: Verify no note mutation occurs without `NoteRevision` and `UpdateEvent`, and AI cannot overwrite user-locked blocks automatically.
- **Dependencies**: Sprints 1-7
- **Acceptance Criteria**:
  - Tests fail if note is changed without audit records.
  - Tests fail if auto-merge replaces locked content.
- **Validation**:
  - Run unit tests.

### Task 8.3: Create internal release checklist

- **Location**: `docs/release/sift-mvp-checklist.md`
- **Description**: Document manual QA scenarios, privacy checks, API key handling, known limitations, and deferred features.
- **Dependencies**: Sprints 1-7
- **Acceptance Criteria**:
  - Checklist covers capture loss prevention, AI failure, follow-up, merge, manual edit, and search.
- **Validation**:
  - Run through checklist once on a clean install.

## Testing Strategy

- Unit tests for SwiftData repositories, capture transitions, patch operations, context pack construction, structured output decoding, and data integrity.
- UI tests with mock provider for capture, generation, follow-up, proposal handling, search, and failure recovery.
- Snapshot or preview checks for Record, Library, Concept Detail, update proposal, and source notice states.
- Manual Simulator checks for navigation, keyboard behavior, loading states, Dynamic Type, and offline/failure behavior.
- Device smoke test before any real usage build.

## Potential Risks and Gotchas

- SwiftData schema churn can become expensive. Keep migrations simple during MVP and freeze model names before real user testing.
- AI structured output can drift. Treat decoding failure as recoverable and keep the original capture/message.
- Provider latency can make the app feel broken. Always show saved draft and progress before model completion.
- Patch-based merging is the core risk. Keep operations few and heavily tested before adding richer edits.
- User-locked blocks must be respected everywhere, including proposal acceptance and future model-generated patches.
- Source/confidence UI must stay lightweight, but uncertainty must not be hidden for sensitive or time-sensitive concepts.
- Multi-model selection is intentionally deferred; adding it early would turn MVP into an AI client instead of a learning notes app.
- Windows workspace cannot build an iOS app directly. Actual Xcode build and Simulator validation require macOS.

## Rollback Plan

- If AI integration is unstable, keep mock provider and ship local capture/library/detail first.
- If patch merge is unstable, disable automatic merge and route all updates through proposals.
- If SwiftData relations become difficult, simplify library grouping to query through explicit repository methods while preserving model truth sources.
- If source/confidence is not ready, display "Generated from model knowledge, no external sources cited" and prevent uncertain content from auto-merging.
