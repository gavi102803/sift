# Sift Product Design

Tagline: Keep what's worth understanding.

## Summary

Sift is a lightweight learning notes app for capturing new concepts encountered in work and daily life. The app helps users quickly "sift out" a concept worth understanding, generate an initial learning note with AI, and keep growing that note through follow-up questions over time.

The core product idea is not another general chat app or a heavy knowledge management system. Sift treats each concept card as a persistent learning session: the first query and all future follow-ups under the same concept share one conversation lineage, while different concept cards behave like separate sessions.

## Product Positioning

Users often hear new terms during work, meetings, reading, podcasts, or daily conversations. They may ask an AI model what the term means, understand it briefly, and then lose the explanation because it was never organized into a lasting personal note.

Sift solves this by making concept capture and long-term note growth the default behavior.

Primary promise:

> Hear a concept, capture it in seconds, and let it slowly become part of your knowledge.

## Core Principles

1. Fast capture comes first.
   Opening the app should immediately support typing or speaking a new concept.

2. Notes grow progressively.
   The first generated note should be short and useful, not a long encyclopedia entry.

3. AI answers and AI sedimentation are separate.
   A model response solves the current question. Note updates preserve durable learning.

4. Each concept card owns a continuous AI conversation.
   Follow-ups under one concept should preserve context even if the user returns much later.

5. Organization is automatic by default, editable by the user.
   AI suggests themes, tags, and related concepts. Users can correct them.

6. Model choice is flexible per follow-up.
   The concept card remains the same conversation, but the user may choose different models for different questions.

## MVP Scope

The first release should include:

- Quick text capture for a new concept.
- Optional voice input if implementation cost is acceptable.
- AI-generated progressive initial note.
- A concept library with automatic theme and tag grouping.
- Manual editing for title, tags, theme, note body, and related concepts.
- A concept detail screen with the note and follow-up input.
- One persistent conversation per concept card.
- Per-message model selection inside the same concept conversation.
- AI update decisions after each follow-up:
  - no update
  - automatic merge
  - user confirmation required
- Update proposal UI for important note changes.
- App Intents for "Capture New Concept" and "Continue Concept".

The first release should not include:

- Complex knowledge graph visualization.
- Daily spaced repetition.
- Collaboration or sharing.
- Public/community concept cards.
- Full version history.
- Heavy folder management.
- Multi-device realtime sync.
- Automated multi-model routing.

## Information Architecture

Sift uses three main tabs:

### Record

The default opening screen. It centers the capture action with a simple input area and quick controls.

Primary states:

- Empty state asking what new concept the user heard.
- Text input state.
- Generating state.
- Initial concept card result.
- Recently captured concepts.
- Concepts that can continue growing.

Primary actions:

- Type a concept or phrase.
- Use voice input.
- Submit.
- Continue asking after the initial note is generated.
- Save to the concept library. The system may save automatically while still showing the user that the concept was captured.

### Concept Library

The home for all saved concepts. It should feel like a calm personal knowledge shelf, not a dense database.

Primary capabilities:

- Search concepts.
- Filter by AI-generated themes.
- View tags.
- Browse recently updated concepts.
- Open a concept detail page.
- Edit tags and themes.

Default organization:

- AI automatically assigns themes such as AI, Product, Finance, Psychology, Methods, or Uncategorized.
- Each theme can show a small count and be collapsible.
- Concept cards show title, one-line explanation, tags, maturity, and recent activity.

### Profile

Settings and ownership controls.

Primary capabilities:

- Preferred default model.
- Available model providers.
- Privacy and local storage notes.
- Export options.
- App Intent and shortcut settings.

## Key Screens

### Record Screen

The record screen should be minimal. The main card asks a direct question such as "What new concept did you hear?"

Recommended controls:

- Microphone button for voice input.
- Add button for optional context or source attachment in a later release.
- Submit arrow button.
- Search button in the navigation bar.

The first tab may be named "Record" rather than "Home" to reinforce the main behavior.

### Concept Detail

The concept detail screen is the main learning surface.

Suggested sections:

- Concept title.
- Maturity label such as Initial, Growing, or Mature.
- Tags and related concepts.
- Current structured note.
- Suggested follow-up questions.
- Follow-up input fixed near the bottom.
- Model selector near the follow-up input.

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

## Data Model

### Concept

Represents the durable knowledge asset.

Fields:

- id
- title
- aliases
- oneLineExplanation
- maturity
- theme
- tags
- relatedConceptIds
- createdAt
- updatedAt
- conversationId

### ConceptNote

Represents the current user-facing note.

Fields:

- id
- conceptId
- sections
- lastMergedAt
- updatedAt

Recommended sections:

- whatItIs
- whyItMatters
- example
- commonMisunderstandings
- relatedConcepts
- userTakeaways

The MVP only needs the current note. Full version history can come later.

### Conversation

Represents the persistent AI conversation lineage for one concept card.

Fields:

- id
- conceptId
- initialQuery
- longTermSummary
- defaultModelId
- lastCompactedAt
- createdAt
- updatedAt

Important rule:

One concept has one primary conversation. Switching models does not create a new conversation.

### ConversationMessage

Represents a user or assistant message inside a concept conversation.

Fields:

- id
- conversationId
- role
- content
- modelId
- createdAt
- mergedIntoNote
- updateMode

The modelId is stored per assistant response so users can see which model contributed each answer.

### ConceptUpdateProposal

Represents a note update that needs user confirmation.

Fields:

- id
- conceptId
- sourceMessageId
- proposedAdditions
- proposedModifications
- proposedRelations
- suggestedTags
- riskNote
- status
- createdAt
- resolvedAt

### Tag

Represents a manually editable or AI-generated tag.

Fields:

- id
- name
- source
- createdAt

### ConceptRelation

Represents a relationship between concepts.

Fields:

- id
- sourceConceptId
- targetConceptId
- relationType
- confidence
- source
- createdAt

## AI Conversation and Context Management

Sift should not depend on a model provider's server-side session memory as the only source of continuity. Instead, each request should build a context pack from local app data.

Context pack:

```text
System instruction:
You are the learning note assistant for this concept card.

Concept metadata:
Title, aliases, tags, maturity, related concepts.

Current note:
The latest structured ConceptNote.

Conversation summary:
The long-term summary of this concept's learning session.

Recent messages:
The most recent relevant turns.

User query:
The current follow-up question.

Output contract:
Answer, update decision, merge content, proposal content, tag suggestions,
relation suggestions, and summary patch.
```

The model should return structured output with:

```text
answer
updateMode: none | autoMerge | needsConfirmation
autoPatch
proposal
newRelations
suggestedTags
summaryPatch
```

### Same Concept, Same Conversation

When the user returns to a concept card later, Sift sends the same concept's note, summary, and recent messages to the selected model. This preserves the user's sense that the card remembers the learning journey.

### Different Concepts, Different Conversations

Different concept cards use separate conversations by default. Related concepts may link to each other, but they should not automatically merge sessions.

### Model Switching

Users can choose the model for each follow-up. For example, they may ask Claude for a deep explanation and GPT for an analogy.

Rules:

- Conversation continuity belongs to the concept, not to the model.
- Each model receives the same context pack format.
- Each assistant response stores the model used.
- The concept note can be updated by responses from different models.
- The UI should keep model switching lightweight, likely as a small selector beside the follow-up input.

## Merge Policy

After a model response, Sift classifies the note update.

### No Update

Use when the response is conversational, redundant, or not worth preserving.

### Automatic Merge

Use for low-risk additions such as:

- Better examples.
- Clarifying analogies.
- Related concepts.
- User-specific takeaways.
- Small elaborations.

### Needs Confirmation

Use for higher-risk changes such as:

- Redefining the concept.
- Reorganizing the note structure.
- Resolving conflicting explanations.
- Adding opinionated or uncertain claims.
- Changing relationships between important concepts.

## iOS Architecture

Recommended stack:

- SwiftUI for UI.
- SwiftData for local persistence.
- A small service layer for AI calls and context construction.
- App Intents for system entry points.

Suggested modules or folders:

- App
  - App shell, tabs, dependency graph, routing.
- Record
  - Quick capture flow and initial card generation.
- Library
  - Concept library, themes, tags, search.
- ConceptDetail
  - Note reading, follow-up, model selection, update proposals.
- AI
  - AIClient, model provider adapters, context pack builder, structured output parser.
- Persistence
  - SwiftData models and repositories.
- Intents
  - Capture new concept and continue concept intents.

Root app structure:

- Use TabView with Record, Concept Library, and Profile tabs.
- Use NavigationStack per tab.
- Install app-level services from one dependency graph modifier.
- Keep feature-local state inside feature views.
- Keep AI/networking out of SwiftUI body code paths.

## App Intents

The first App Intents release should be narrow and useful.

### Capture New Concept

Purpose:

Capture a concept from Siri, Shortcuts, Spotlight, or a widget.

Behavior:

- Accept a concept phrase or short text.
- Create a new concept and conversation.
- Generate the initial note if possible.
- Open the app to the new concept detail page when needed.

### Continue Concept

Purpose:

Ask a follow-up question under an existing concept.

Behavior:

- Let the system identify or search existing concepts.
- Accept a follow-up question.
- Append the question to the concept's conversation.
- Open the concept detail page to show the answer and update state.

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
- The initial AI note is useful without requiring more interaction.
- A user can return to the same concept days later and continue asking questions with preserved context.
- The note becomes cleaner and richer over time instead of becoming a long chat log.
- The concept library remains browsable without manual organization.
- Users can switch models per follow-up without losing the card's conversation continuity.

## Open Decisions

These are intentionally left for implementation planning:

- Which model providers to support in the first build.
- Whether API keys are user-provided or app-managed.
- Whether voice input ships in MVP or immediately after.
- Whether data sync is deferred entirely or implemented as simple iCloud persistence.
- Exact structured output schema for the first model provider.
