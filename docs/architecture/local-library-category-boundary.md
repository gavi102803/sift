# Local Library Category Boundary

Authoritative ownership contract for topics on iOS. Read this before touching
topic sync, the full-note editor, or any outbound note payload.

## The contract

```
Card metadata      = backend-managed tags + topics
Library categories = device-local organization only
                     = never uploaded
                     = never overwritten by backend
                     = never deleted by card refresh / full-note save
```

A topic belongs to the **local Library** iff its `source == "category"` — on
**both** the `Topic` and each `ConceptTopic` assignment. Everything else is
**backend-managed card metadata**.

A Library category and a card topic may share a name (e.g. both "AI"). They are
**separate `Topic` entities** and never reuse each other's `source`. They can
coexist and must never overwrite or be confused with one another.

## Single source of truth

`ios/Sift/Persistence/LibraryCategoryOwnership.swift`:

- `LibraryCategoryOwnership.categorySource` — the `"category"` marker.
- `LibraryCategoryOwnership.isCategory(_:)` — for `Topic`, `ConceptTopic`, or a raw `source`.
- `LibraryCategoryOwnership.cardAssignments(_:)` / `.categoryAssignments(_:)` — split an assignment list.
- `CardTopicProjection.cardTopicNames(conceptId:assignments:topics:)` — card-metadata topic names.
- `CardTopicProjection.categoryNames(conceptId:assignments:topics:)` — local category names.

A projection counts a topic only when **both** the assignment and the `Topic`
agree on category-ness, so a polluted assignment can never leak across.

## Guaranteed behaviours

| Event | Card topics | Library categories |
|---|---|---|
| Remote topic refresh (`ConceptDTO.topics`) | replaced | **preserved** |
| Full-note save response upsert | replaced | **preserved** |
| A remote topic removed | removed | **preserved** |
| Library create / assign category | untouched | written (local only) |
| SwiftData reload | — | **persist** |

Enforced in `ConceptLocalStore`:

- `replaceConceptTopics(conceptId:names:)` deletes/replaces **only**
  `cardAssignments` (`source != "category"`); category assignments are never touched.
- `findOrCreateTopic(named:)` (card topics) **excludes** `source == "category"`
  Topics from lookup, so a card topic never reuses a category `Topic`.
- Library category creation/lookup (`ConceptLibraryView`) only ever
  finds/creates `source == "category"` Topics + assignments.

## ⚠️ Codex integration points (full-note editor / outbound note payload)

When the full-note editor builds the `topics` field for the editor UI or for the
outbound `PUT /v1/concepts/{conceptId}/note` payload, it **must** use:

```swift
CardTopicProjection.cardTopicNames(
    conceptId: concept.id,
    assignments: <all ConceptTopic>,
    topics: <all Topic>
)
```

Do **not** read raw `ConceptTopic` assignments or re-derive `source == "category"`
inline. Using `cardTopicNames` guarantees local Library categories are never
shown in the editor's topic field and never uploaded. When applying a note-save
response locally, route topics through `replaceConceptTopics` (which preserves
categories) — do not delete `ConceptTopic` rows directly.
