# Sift MVP Release Checklist

Date: 2026-06-24
Status: Internal MVP validation

## Required Local Setup

- Backend is running on `http://127.0.0.1:8000`.
- `GET /health` returns `{"status": "ok"}`.
- `GET /v1/app-status` reports:
  - `modelProvider=openai`
  - `webSearchEnabled=true`
  - `databaseURL=sqlite:///./.data/sift.db`
- iOS Simulator launches the `Sift` scheme with `SIFT_BACKEND_BASE_URL=http://127.0.0.1:8000`.
- `backend/.env` exists locally and is ignored by Git.

## Automated Gates

- Backend unit/integration tests pass: `backend/.venv/bin/python -m pytest backend`.
- Backend lint passes: `backend/.venv/bin/python -m ruff check backend scripts/smoke-backend-mvp.py`.
- iOS unit tests pass through the shared `Sift` scheme:
  - `SiftTests/ConceptLocalStoreTests/testGenerateFailureLeavesRecoverableDraft`
  - `SiftTests/ConceptLocalStoreTests/testSuccessfulGenerationReplacesLocalDraftWithRemoteConcept`
  - `SiftTests/ConceptLocalStoreTests/testManualNoteEditCreatesAuditRecordsAndLocksBlock`
  - `SiftTests/ConceptLocalStoreTests/testManualSummaryAndOrganizationEditPersistsAuditTagsAndTopics`
  - `SiftTests/ConceptLocalStoreTests/testFailedFollowUpDraftsAreRecoverableDedupedAndClearable`
  - `SiftTests/ConceptLocalStoreTests/testRemotePruneKeepsLocalFailureRecoveryDrafts`
  - `SiftTests/ConceptLocalStoreTests/testOrganizationDedupesTagsAndTopicsCaseInsensitively`
  - `SiftTests/ConceptLocalStoreTests/testProposalAndRelationLifecycleArePersisted`
  - `SiftTests/ConceptLocalStoreTests/testConceptSearchMatchesTitleExplanationAliasesTagsAndTopics`
- Strict OpenAI smoke passes:
  - provider diagnostic reports OpenAI
  - web search diagnostic reports `webSearchUsed=true`
  - initial capture returns `answerSource.sourceType=webVerified`
  - follow-up turn is stored with answer source
  - unsafe proposal merges are rejected safely with `hashMismatch`, `lockedBlock`, `staleRevision`, or `missingConcept`
- iOS build/run succeeds in Simulator with no XcodeBuildMCP warnings/errors.

## Manual Simulator QA

1. Launch Sift on the Record tab.
2. Confirm the Record screen does not show `Could not connect to the server`.
3. Capture a new concept such as `RAG evaluation`.
4. Confirm Sift navigates immediately into the saved draft detail while generation is pending.
5. Confirm generation updates the draft into a ready concept card with note blocks.
6. Open the generated concept detail.
7. Confirm title, maturity, capture status, note content, and source/confidence notice are visible.
8. Ask a follow-up question.
9. Confirm the assistant answer bubble appears immediately and fills incrementally while the model response streams.
10. Confirm the final answer persists after leaving/reopening the card.
11. If a pending update proposal appears, test `Confirm`.
12. Ask another definition-changing follow-up and test `Skip`.
13. Return to Record and tap the microphone button in the capture field.
14. Grant Speech Recognition and Microphone permissions if prompted.
15. Speak a short concept and confirm the transcript fills the capture field.
16. Edit the title, explanation, tags, and topics from the detail edit button.
17. Edit a note block and confirm it becomes user-authored/locked.
18. Create a second concept.
19. Add it from the first card's Related Concepts menu.
20. Remove the relation and confirm the row disappears.
21. Use Library search for title, explanation, tag, topic, and alias-like text.
22. Open Profile.
23. Run model diagnostic.
24. Run web search diagnostic and confirm citations count is shown.
25. In Provider Settings, switch to `OpenAI-compatible`, enter a compatible base URL and API key, load models, pick a model, and save.
26. Confirm the saved API key is shown only as a masked preview.
27. Run model diagnostic again and confirm the provider reports `openai_compatible`.
28. Switch back to `OpenAI Responses` before validating web search diagnostics.

## Failure Recovery QA

1. Stop the backend.
2. Capture a concept.
3. Confirm the local draft remains visible with generation failure state.
4. Restart the backend.
5. Tap retry and confirm the draft can become a ready concept.
6. In an existing concept, stop the backend and submit a follow-up.
7. Confirm the question remains recoverable in the composer after reopening the card.
8. Archive a failed capture and confirm it disappears from Record and Library.

## Data Integrity Checks

- Every backend note mutation records an internal `note_revisions` row.
- Every backend note mutation records an `update_events` row.
- Automatic patch application rejects stale revisions.
- Automatic patch application rejects user-locked blocks.
- Replace patches require matching `oldValueHash`.
- Proposal relation patches reject missing target concepts rather than partially merging.
- iOS local manual note edits create local `NoteRevision` and `UpdateEvent` records.

## Privacy And Key Handling

- No upstream provider key is stored in iOS.
- `backend/.env` is ignored by Git.
- Runtime provider settings are stored under `backend/.data/model-provider.json`, which is ignored by Git.
- `.env.example` contains only placeholders.
- API errors shown in iOS do not expose the full API key.
- The backend is the only component that calls OpenAI or LiteLLM.

## Known MVP Limitations

- Managed Beta activation, token lifecycle, owner isolation, and ephemeral BYOK relay are implemented
  at repository level; real hosted deployment and signed-device evidence are still pending.
- Multi-device sync is not implemented.
- App Intents, Shortcuts, Spotlight, sharing, collaboration, and spaced repetition are deferred.
- The iOS app uses local SwiftData mirrors plus backend authority; conflict handling beyond the current MVP flows is not complete.
- Initial concept and follow-up generation, including legacy compatibility endpoints, use persistent
  ModelRun tasks; the DeepSeek 20-turn live recovery protocol passed on 2026-07-19.
- The privacy-safe CLI report covers run reliability plus capture, follow-up, seven-day reuse,
  restore, and review-decision aggregates; it is not a hosted analytics dashboard or cohort system.
- The 20-turn recovery runner is resumable and cost-gated, and its Mock process-kill rehearsal is
  automated; the equivalent DeepSeek run completed with 20 successful follow-ups, 42 unique turns,
  Backend kill/restart recovery, idempotent replay, early-context recall, and a live Simulator App
  terminate/relaunch follow-up recovery. Multi-day and signed-device evidence remain gates.
- Revision browsing, preview, online restore, offline disable behavior, and periodic-review Proposal
  refresh are covered on Simulator; signed-device validation remains a release gate.
- Complex relation suggestions without an existing target concept are not auto-created.
- Real device validation is still required before any broader internal release.
