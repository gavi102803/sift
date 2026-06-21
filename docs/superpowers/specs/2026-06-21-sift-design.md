# Sift Product Design

Tagline: Keep what's worth understanding.

## Summary

Sift is a lightweight learning notes app for capturing new concepts encountered in work and daily life. It helps users quickly "sift out" a concept worth understanding, generate an initial learning note with AI, and keep growing that note through follow-up questions over time.

The core product idea is not another general chat app or a heavy knowledge management system. Sift treats each concept card as a durable knowledge asset. Each card owns a logical AI conversation that preserves the learning journey for that concept, while different concept cards behave like separate conversations.

## Product Positioning

Users often hear new terms during work, meetings, reading, podcasts, or daily conversations. They may ask an AI model what the term means, understand it briefly, and then lose the explanation because it was never organized into a lasting personal note.

Sift solves this by making capture and long-term note growth the default behavior.

Primary promise:

> Hear a concept, capture it in seconds, and let it slowly become part of your knowledge.

## Core Principles

1. Fast capture comes first.
   Opening the app should immediately support typing or speaking a new concept.

2. Capture never depends on AI success.
   Once the user submits text, the original input must be saved locally. Model timeout, network failure, or generation failure must not lose the capture.

3. Notes grow progressively.
   The first generated note should be short and useful, not a long encyclopedia entry.

4. AI answers and AI sedimentation are separate.
   A model response solves the current question. Note updates preserve durable learning.

5. Each concept card owns a logical AI conversation.
   Follow-ups under one concept should preserve context even if the user returns much later. This conversation is a Sift-owned product concept, not a provider-owned remote session.

6. Organization is automatic by default, editable by the user.
   AI suggests topics, tags, and related concepts. Users can correct them.

7. The MVP uses one system-managed default model.
   The data model remains provider-agnostic and stores model metadata for future multi-model support, but the first release does not expose per-message model selection.

## MVP Scope

The first release should include:

- Quick text capture for a new concept or short phrase.
- Immediate local persistence of a capture draft before any AI generation begins.
- A capture state machine for drafts, generation, disambiguation, failure, and ready cards.
- AI-generated progressive initial concept card.
- A concept library with automatic topic and tag grouping.
- Manual editing for title, tags, topics, note blocks, and related concepts.
- A concept detail screen with the note and follow-up input.
- One logical conversation per concept card.
- A single system-managed default model for answer generation, update decisions, and note merging.
- Provider-agnostic model metadata in the data layer for future expansion.
- AI update decisions after each follow-up:
  - no update
  - automatic merge
  - user confirmation required
- Revision-aware update proposals for important note changes.
- User-edited note blocks protected from automatic AI overwrite.
- Immutable internal note revisions and merge events for traceability and future rollback.
- A lightweight answer source and confidence model.
- Search, tag editing, topic editing, and concept relation editing.

The first release should not include:

- Per-message foreground model selection.
- Automated multi-model routing.
- Complex knowledge graph visualization.
- Daily spaced repetition.
- Collaboration or sharing.
- Public/community concept cards.
- User-facing full version history.
- Heavy folder management.
- Multi-device realtime sync.
- App Intents or Shortcuts flows.

## Post-MVP System Integrations

System entry points are useful, but they should not compete with the first release's core loop.

V1.1 should consider a narrow system integration:

- Capture New Concept.
- Accept one text phrase.
- Create a local capture draft.
- Open the app to the Record screen.
- Keep AI generation and concept continuation inside the app.

V1.2 should consider:

- Spotlight search for existing concept cards.
- Tap-through into Concept Detail.

The previous "Continue Concept" intent is deferred. It requires entity lookup, ambiguity resolution, foreground/background transitions, network calls, and update presentation. Its value is lower than making in-app capture and card growth reliable.

## Information Architecture

Sift uses three main tabs:

### Record

The default opening screen. It centers the capture action with a simple input area and quick controls.

Primary states:

- Empty state asking what new concept the user heard.
- Text input state.
- Draft saved state.
- Pending generation state.
- Generating state.
- Needs disambiguation state.
- Generation failed state.
- Initial concept card result.
- Recently captured concepts.
- Concepts that can continue growing.

Primary actions:

- Type a concept or phrase.
- Use voice input if it ships after the text flow is stable.
- Submit.
- Retry generation if it fails.
- Resolve a duplicate or ambiguous concept.
- Continue asking after the initial note is generated.
- Open the saved draft later if the user exits mid-flow.

### Concept Library

The home for all saved concepts. It should feel like a calm personal knowledge shelf, not a dense database.

Primary capabilities:

- Search concepts.
- Filter by AI-generated topics.
- View and edit tags.
- Browse recently updated concepts.
- Open a concept detail page.
- Edit topics.
- Accept, dismiss, or edit proposed concept relations.

Default organization:

- AI suggests topics such as AI, Product, Finance, Psychology, Methods, or Uncategorized.
- A concept may belong to multiple topics.
- Each topic can show a small count and be collapsible.
- Concept cards show title, one-line explanation, tags, maturity, capture status, and recent activity.

### Profile

Settings and ownership controls.

Primary capabilities:

- View the system-managed default model.
- Manage the model provider connection if required.
- Privacy and local storage notes.
- Export options.
- Future system integration settings.

## Key Screens

### Record Screen

The record screen should be minimal. The main card asks a direct question such as "What new concept did you hear?"

Recommended controls:

- Microphone button only after the text capture path is reliable.
- Add button for optional context or source attachment in a later release.
- Submit arrow button.
- Search button in the navigation bar.

The first tab may be named "Record" rather than "Home" to reinforce the main behavior.

### Concept Detail

The concept detail screen is the main learning surface.

Suggested sections:

- Concept title.
- Maturity label such as Initial, Growing, or Mature.
- Tags, topics, and related concepts.
- Source/confidence notice.
- Current structured note.
- Suggested follow-up questions.
- Follow-up input fixed near the bottom.

The MVP should not show a foreground model selector. A later release may add model selection once the merge and curation rules are stable.

The initial progressive note should include:

- What it is.
- Why it is worth remembering.
- One concrete example.
- Related concepts.
- Questions the user may ask next.

### Follow-Up Update Sheet

After a follow-up, Sift should show the model's answer first. Then it should decide how the note changes.

If the change is small, Sift can show a lightweight "Updated note" confirmation.

If the change is significant, Sift should show an update proposal with:

- Automatically merged additions.
- Changes requiring confirmation.
- New related concepts.
- A primary action labeled "Merge into note".
- A secondary action to keep the note unchanged.
- A clear note when the proposal is based on an older note revision and must be refreshed.

## Data Model

The data model should avoid duplicate sources of truth. Tags, topics, and relations should be represented through assignment tables rather than copied onto `Concept` and `ConceptNote`.

### Concept

Represents the durable knowledge asset.

Fields:

- id
- canonicalTitle
- displayTitle
- aliases
- language
- oneLineExplanation
- maturity
- captureStatus
- noteRevision
- createdAt
- updatedAt
- conversationId

### Capture Status

Represents the lifecycle of a user's submitted concept input.

Values:

- draft
- pendingGeneration
- generating
- needsDisambiguation
- ready
- generationFailed
- archived

Important rule:

Once the user submits input, the raw capture must be saved locally before the app calls the model. A failed model call can create a failed draft, but it must not erase the user's capture.

### ConceptNote

Represents the current user-facing note.

Fields:

- id
- conceptId
- revision
- blocks
- updatedAt
- updatedBy

Recommended note blocks:

- whatItIs
- whyItMatters
- example
- commonMisunderstandings
- relatedConceptsDisplay
- userTakeaways

`relatedConceptsDisplay` is only presentation content inside the note. The source of truth for relationships is `ConceptRelation`.

The MVP exposes only the current note, but stores immutable note revisions and merge events internally for traceability, rollback, and future version history.

### NoteBlock

Represents a structured block inside the current note.

Fields:

- id
- conceptNoteId
- blockType
- content
- source: ai | user | merged
- isUserLocked
- lastEditedBy
- updatedAt

Important rule:

Blocks manually edited by the user are protected by default. AI may append nearby clarification or create a proposal, but it must not automatically replace a user-locked block.

### NoteRevision

Represents an immutable snapshot created after a note merge or manual edit.

Fields:

- id
- conceptId
- revision
- snapshot
- sourceMessageId
- mergeMode
- createdAt

The MVP does not need to show a full revision browser, but these records must exist for internal traceability and future recovery.

### UpdateEvent

Represents why and how a note changed.

Fields:

- id
- conceptId
- noteRevision
- sourceMessageId
- proposalId
- eventType: manualEdit | autoMerge | confirmedMerge | dismissedProposal | retryGeneration
- actor: user | system | ai
- createdAt

### Conversation

Represents Sift's logical AI conversation lineage for one concept card.

Fields:

- id
- conceptId
- initialQuery
- cardMemory
- memoryRevision
- memoryUpdatedAt
- defaultModelId
- createdAt
- updatedAt

Important rule:

One concept has one primary logical conversation. Provider sessions or remote thread IDs may optimize a specific model integration, but they are not the source of truth for continuity.

`cardMemory` is not a transcript summary. It is the durable learning state the card should carry into future model calls:

- Why the user originally captured the concept.
- What the user has confirmed.
- What remains confusing.
- The explanation styles that worked for this user.
- Content the user manually edited or locked.
- Unresolved questions.
- Confirmed related concepts.

### ModelThread

Represents an optional provider-specific remote thread.

Fields:

- id
- conversationId
- providerId
- modelId
- remoteThreadId
- lastUsedAt

This lets future versions use provider sessions without making them the product's only memory source.

### ConversationMessage

Represents a user or assistant message inside a concept conversation.

Fields:

- id
- conversationId
- role
- content
- modelId
- providerId
- createdAt
- mergedIntoNote
- updateMode
- answerSourceId

The MVP uses one default model, but storing model/provider metadata keeps the data portable for future multi-model support.

### ConceptUpdateProposal

Represents a revision-aware note update that needs user confirmation.

Fields:

- id
- conceptId
- sourceMessageId
- baseNoteRevision
- patchOperations
- rationale
- confidence
- status: proposed | accepted | dismissed | stale
- createdAt
- resolvedAt

`patchOperations` should be a structured diff, not free text.

Example:

```json
[
  {
    "operation": "append",
    "targetBlockId": "example",
    "content": "In an enterprise knowledge base, RAG can retrieve product documents before generating an answer."
  },
  {
    "operation": "replace",
    "targetBlockId": "whatItIs",
    "oldValueHash": "abc123",
    "newContent": "RAG is a method where external information is retrieved first, then used by a model to generate an answer."
  }
]
```

When applying a proposal, Sift must verify that `baseNoteRevision` still matches the current note or that each operation can be safely rebased. If not, the proposal becomes stale and must be regenerated or manually reviewed.

### AnswerSource

Represents the source basis and confidence of an answer or note update.

Fields:

- id
- sourceType: modelKnowledge | userProvided | webVerified
- citations
- verifiedAt
- confidence
- uncertaintyNote

The MVP can keep UI lightweight:

- "Generated from model knowledge."
- "No external sources cited."
- "Verified with 3 sources."

For concepts that require time-sensitive accuracy, professional stakes, or external verification, the model should mark uncertainty or recommend verification rather than silently merging uncertain claims into the note body.

### Tag

Represents a manually editable or AI-generated tag.

Fields:

- id
- name
- source: ai | user
- createdAt

### ConceptTag

Represents the assignment of a tag to a concept.

Fields:

- conceptId
- tagId
- confidence
- source: ai | user

### Topic

Represents a broader grouping such as AI, Product, Finance, or Research Methods.

Fields:

- id
- name
- source: ai | user
- createdAt

### ConceptTopic

Represents the assignment of a topic to a concept.

Fields:

- conceptId
- topicId
- confidence
- source: ai | user

### ConceptRelation

Represents a relationship between concepts.

Fields:

- id
- sourceConceptId
- targetConceptId
- relationType
- status: proposed | accepted | dismissed
- confidence
- source: ai | user
- createdAt

## AI Conversation and Context Management

Sift should not depend on a model provider's server-side session memory as the only source of continuity. Instead, each request should build a context pack from local app data.

Context pack:

```text
System instruction:
You are the learning note assistant for this concept card.

Concept metadata:
Canonical title, display title, aliases, language, maturity, accepted topics,
accepted tags, accepted related concepts, and capture status.

Current note:
The latest structured ConceptNote with block metadata.

Card memory:
The durable learning state for this card.

Recent messages:
The most recent 6-10 relevant turns.

User query:
The current follow-up question.

Output contract:
Answer, source/confidence, update decision, patch operations, proposal content,
topic suggestions, tag suggestions, relation suggestions, and memory patch.
```

The model should return structured output with:

```text
answer
answerSource
updateMode: none | autoMerge | needsConfirmation
autoPatchOperations
proposalPatchOperations
newRelations
suggestedTags
suggestedTopics
memoryPatch
uncertaintyNote
```

### Same Concept, Same Logical Conversation

When the user returns to a concept card later, Sift sends the same concept's note, card memory, and recent messages to the default model. This preserves the user's sense that the card remembers the learning journey.

### Different Concepts, Different Conversations

Different concept cards use separate conversations by default. Related concepts may link to each other, but they should not automatically merge sessions.

### Model Strategy

The MVP uses one system-managed default model. The user does not choose the model per follow-up.

The data layer still stores `modelId`, `providerId`, and optional `ModelThread` records so future versions can support multiple providers without rewriting the conversation model.

Future multi-model support should separate answering from curation:

- The user may choose a response model for a specific explanation.
- A unified curator model or curation service should still perform update decisions, note merging, and conflict handling.
- If two models disagree, Sift should present that as uncertainty or a proposal rather than automatically overwriting the card.

## Merge Policy

After a model response, Sift classifies the note update.

### No Update

Use when the response is conversational, redundant, unsupported, uncertain, or not worth preserving.

### Automatic Merge

Use for low-risk additions such as:

- Better examples.
- Clarifying analogies.
- User-specific takeaways.
- Small elaborations.
- Low-risk related concept suggestions.

Automatic merge must not replace user-locked blocks.

### Needs Confirmation

Use for higher-risk changes such as:

- Redefining the concept.
- Reorganizing the note structure.
- Resolving conflicting explanations.
- Adding opinionated or uncertain claims.
- Changing relationships between important concepts.
- Updating a block the user manually edited.

### Stale Proposal

Use when a proposal was generated against an older note revision and can no longer be applied cleanly. The user should be asked to regenerate or review the change manually.

## iOS Architecture

Recommended stack:

- SwiftUI for UI.
- SwiftData for local persistence.
- A small service layer for AI calls and context construction.
- Provider adapter interfaces for future model expansion.

Suggested modules or folders:

- App
  - App shell, tabs, dependency graph, routing.
- Record
  - Quick capture flow, local draft persistence, generation states, duplicate handling.
- Library
  - Concept library, topics, tags, relations, search.
- ConceptDetail
  - Note reading, follow-up, update proposals, manual edits, source notices.
- AI
  - AIClient, default model adapter, context pack builder, structured output parser, curator/merge service.
- Persistence
  - SwiftData models and repositories.
- SystemIntegrations
  - Deferred App Intents and Spotlight integration.

Root app structure:

- Use TabView with Record, Concept Library, and Profile tabs.
- Use NavigationStack per tab.
- Install app-level services from one dependency graph modifier.
- Keep feature-local state inside feature views.
- Keep AI/networking out of SwiftUI body code paths.

## UX Tone

Sift should feel quiet, precise, and low-friction.

Visual direction:

- Paper-like white or warm neutral surfaces.
- Clear typography.
- Low visual noise.
- Native iOS controls where possible.
- Concept cards with restrained borders and spacing.
- Avoid turning the app into a flashy AI chat interface.

The concept UI reference is a strong baseline:

- Minimal record screen.
- Progressive concept card.
- Follow-up update sheet with automatic merge and confirmation sections.
- Theme-grouped concept library.

Recommended copy style:

- Short.
- Concrete.
- Learning-oriented.
- Avoid productivity jargon.

## Success Criteria

The MVP succeeds if:

- A user can capture a new concept in about 10 seconds.
- A submitted capture is saved locally before any AI generation begins.
- The initial AI note is useful without requiring more interaction.
- A user can return to the same concept days later and continue asking questions with preserved logical context.
- The note becomes cleaner and richer over time instead of becoming a long chat log.
- Automatic merges are low-risk and never overwrite protected user edits.
- Significant changes are represented as revision-aware proposals.
- The concept library remains browsable without manual organization.
- The app can explain whether an answer came from model knowledge, user-provided context, or verified external sources.

## Open Decisions

These are intentionally left for implementation planning:

- Which single default model/provider to use in the first build.
- Whether API keys are user-provided or app-managed.
- Whether voice input ships in MVP or immediately after.
- Whether data sync is deferred entirely or implemented as simple iCloud persistence.
- Exact structured output schema for the first model provider.
- Exact patch operation schema for note updates.
- Whether web verification is implemented in MVP or represented only by the source model.
