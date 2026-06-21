# Sift Open-Source Research Notes

**Date**: 2026-06-22

## Research Goal

Identify open-source projects and libraries that can accelerate Sift without pulling the product toward a generic chat client or agent runtime.

Sift's core implementation risk is the growth and protection of a concept card:

```text
ConceptNote + Conversation + CardMemory + NoteRevision + UpdateEvent + patch merge
```

The research priority is therefore:

- Use libraries for narrow infrastructure.
- Borrow patterns for UI, streaming, validation, and architecture.
- Avoid reusing product runtimes that make chat threads or agents the center.

## Direct Dependencies

### MarkdownUI

Source:

- https://github.com/gonzalezreal/swift-markdown-ui

Use:

- Render AI answers in follow-up history.
- Render read-only Markdown fragments such as lists, links, tables, and code blocks.
- Keep rich answer display simple in SwiftUI.

Do not copy:

- Do not model the whole `ConceptNote` as one Markdown document.
- Do not build a Markdown editor in MVP.
- Do not re-render long streaming Markdown on every token if it causes UI jank.

License:

- MIT, based on repository metadata.

Decision:

- Introduce for read-only Markdown rendering.

### LiteLLM Proxy

Source:

- https://docs.litellm.ai/

Use:

- Self-hosted model gateway behind Sift Backend.
- Provider key management.
- OpenAI-compatible API surface.
- Model aliases such as `sift-explain`, `sift-curate`, and `sift-fast`.
- Provider fallback and usage logging.

Do not copy:

- Do not expose LiteLLM directly to iOS.
- Do not let LiteLLM model/provider choices leak into Sift domain models.

License:

- Check the repository/license during implementation before production deployment.

Decision:

- Introduce as infrastructure, not as the product memory layer.

## Pattern References

### MacPaw/OpenAI

Source:

- https://github.com/MacPaw/OpenAI

Use:

- Reference for Swift DTO shape around OpenAI-style APIs.
- Reference for streaming client ergonomics if needed.
- Temporary local prototypes only.

Do not copy:

- Do not use as a production iOS dependency for upstream model calls.
- Do not let SDK request/response types become Sift domain models.

License:

- Check repository license before copying code. Prefer no code copying.

Decision:

- Borrow ideas only.

### SwiftOpenAI

Source:

- https://github.com/jamesrochabrun/SwiftOpenAI

Use:

- Compare Swift modeling of Responses API, structured outputs, and streaming transport.
- Learn ergonomic API design for Swift DTOs.

Do not copy:

- Do not ship production iOS with direct provider SDK access.
- Do not make it a backend dependency unless the backend is Swift, which is not the MVP decision.

License:

- Check repository license before copying code. Prefer no code copying.

Decision:

- Borrow ideas only.

### openai-structured-outputs-samples

Source:

- https://github.com/openai/openai-structured-outputs-samples
- https://platform.openai.com/docs/guides/structured-outputs

Use:

- Design JSON Schema for `ConceptTurnResult`.
- Build valid and invalid fixtures.
- Define retry behavior when model output fails validation.

Do not copy:

- Do not copy application structure.
- Do not assume OpenAI-specific schema behavior covers every provider through LiteLLM.

License:

- Check repository license before copying code. Prefer schema ideas and tests only.

Decision:

- Borrow schema/test strategy.

### clean-architecture-swiftui

Source:

- https://github.com/nalexn/clean-architecture-swiftui

Use:

- Reference for feature organization.
- Reference for dependency injection and test structure.
- Reference for separating UI from networking/persistence.

Do not copy:

- Do not introduce a heavy global app state or Redux-like architecture in MVP.
- Do not add abstraction layers before the Record, Library, and Concept Detail flows require them.

License:

- Check repository license before copying code. Prefer pattern borrowing only.

Decision:

- Borrow lightweight organization ideas.

### Ayna

Source:

- https://github.com/sozercan/ayna

Use:

- Study streaming UI states.
- Study OpenAI-compatible endpoint handling.
- Study native SwiftUI chat interactions for follow-up answers.

Do not copy:

- Do not copy the multi-model chat product shape.
- Do not copy a foreground model picker into MVP.
- Do not reuse chat-thread data structures as Sift's concept/conversation model.

License:

- Check repository license before copying code. Prefer pattern borrowing only.

Decision:

- Borrow interaction and streaming ideas only.

## Not Introduced in MVP

### Exyte/Chat

Source:

- https://github.com/exyte/Chat

Reason:

- Sift is not a WhatsApp-style or ChatGPT-style infinite chat stream.
- `ConceptDetail` should be centered on the current knowledge card, the latest answer, update state, and follow-up input.

Decision:

- Do not introduce.

### ChatGPTSwiftUI

Source:

- https://github.com/alfianlosari/ChatGPTSwiftUI

Reason:

- Useful as a basic demo, but too chat-client-centered for Sift's product architecture.

Decision:

- Do not use as an architecture baseline.

### SwiftUI-Notes

Source:

- https://github.com/calda/SwiftUI-Notes

Reason:

- Its older storage/sync approach is not the MVP direction.
- Sift defers multi-device realtime sync.

Decision:

- Do not introduce.

### swift-markdown-engine

Source:

- https://github.com/nodes-app/swift-markdown-engine

Reason:

- It is oriented toward a richer Markdown editor stack than Sift needs in MVP.
- Sift keeps notes as structured `NoteBlock` data.

Decision:

- Do not introduce.

### Agent and Coding Runtimes

Examples:

- Codex CLI/runtime.
- Claude Code runtime.
- OpenAI Agents SDK.
- Claude Agent SDK.

Reason:

- Sift is not executing tools in a workspace.
- Sift does not need a coding-agent sandbox or file-system runtime.
- The product memory truth is `ConceptNote + CardMemory + Conversation`, not provider or agent sessions.

Decision:

- Do not introduce.

## Implementation Impact

### iOS

Use:

- SwiftUI.
- SwiftData.
- MarkdownUI.
- URLSession-based Sift API client.
- Mock Sift API client for previews and UI tests.

Avoid:

- Direct upstream model SDKs.
- Heavy chat UI frameworks.
- Markdown editor frameworks.

### Backend

Use:

- FastAPI.
- Pydantic.
- SQLAlchemy.
- Alembic.
- PostgreSQL.
- LiteLLM Proxy.
- JSON Schema validation for model outputs.

Avoid:

- Provider SDKs as domain model sources.
- Agent runtimes as the core orchestration layer.

## Follow-Up Checks During Implementation

- Verify licenses before copying any source code.
- Prefer package use or pattern borrowing over copied code.
- Add fixture tests for structured output before connecting real model calls.
- Keep `ConceptNote` structured even if AI answers render as Markdown.
- Keep LiteLLM and provider keys fully behind Sift Backend.
