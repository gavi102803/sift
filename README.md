# Sift

Keep what's worth understanding.

Sift is a lightweight learning-notes app for quickly capturing a concept, asking follow-up questions, and turning model answers into durable concept cards.

## Current MVP Shape

- iOS SwiftUI app source in `ios/Sift`.
- FastAPI backend in `backend`.
- Backend uses a trimmed Hermes-style runtime with model provider profiles and web retrieval providers.
- Supported model profiles currently include `openai`, `deepseek`, `openrouter`, `nous`, `kimi`, `custom`, and `mock`.
- Without model configuration, the backend and iOS app fall back to deterministic mock flows for local UI work.

## Backend

From the repository root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m uvicorn sift_backend.main:app --reload --host 127.0.0.1 --port 8000
```

On macOS:

```bash
cd backend
python3 -m venv .venv
./.venv/bin/python -m pip install -e ".[dev]"
./.venv/bin/python -m uvicorn sift_backend.main:app --reload --host 127.0.0.1 --port 8000
```

Optional provider-backed concept generation and follow-up turns, with no-key DuckDuckGo
retrieval by default:

```bash
cp backend/.env.example backend/.env
# then edit backend/.env:
SIFT_RUNTIME_PROVIDER=deepseek
SIFT_RUNTIME_BASE_URL=https://api.deepseek.com/v1
SIFT_RUNTIME_API_KEY=your-provider-key
SIFT_RUNTIME_MODEL=deepseek-chat
SIFT_RUNTIME_WEB_SEARCH_ENABLED=true
SIFT_WEB_SEARCH_PROVIDER=ddgs
SIFT_WEB_SEARCH_API_KEY=
```

Process environment variables still override `backend/.env` for one-off runs.

If no provider key is configured, concept creation and follow-up turns use the mock model service.

When web search is enabled, Sift retrieves source context before concept generation and
follow-up answers. `ddgs` does not require a separate web search API key; `tavily` remains
available when `SIFT_WEB_SEARCH_API_KEY` is configured.

Run checks:

```bash
cd backend
./.venv/bin/python -m ruff check .
./.venv/bin/python -m pytest
```

Run the backend MVP smoke test after starting the backend, or let the script start it:

```bash
python3 scripts/smoke-backend-mvp.py
python3 scripts/smoke-backend-mvp.py --start-server
python3 scripts/smoke-backend-mvp.py --start-server --check-web-search
```

Strict provider E2E smoke check after adding runtime and web search keys to `backend/.env`:

```bash
python3 scripts/smoke-backend-mvp.py \
  --start-server \
  --require-provider deepseek \
  --check-web-search \
  --require-web-search-used \
  --allow-model-variance \
  --capture "latest web search changes in 2026"
```

## iOS

The iOS project lives at `ios/Sift.xcodeproj`.

Debug builds default to `http://127.0.0.1:8000` for Simulator backend calls. Override it
with this environment variable in the Xcode scheme when needed:

```text
SIFT_BACKEND_BASE_URL=http://127.0.0.1:8000
```

## Smoke Test

1. Start the backend on `127.0.0.1:8000`.
2. Launch the iOS app in Simulator.
3. On the record tab, capture a concept such as `RAG`.
4. Open the generated concept card.
5. Temporarily stop the backend, capture another concept, and confirm a failed draft remains
   visible with a retry button.
6. Restart the backend and use retry to generate the saved draft.
7. Ask a follow-up question.
8. Confirm that the answer appears and low-risk updates are merged into the note.
9. Ask a definition-changing question such as `Define this more precisely`.
10. Confirm that a pending update card appears, then test both `Confirm` and `Skip`.
11. Create a second concept, then add it under `Related Concepts` from the first card.
12. Remove the relation and confirm the related concept row disappears.
13. Reopen the concept card and confirm the conversation history still shows answer source
   details under assistant replies.
14. In Profile, run `Test Web Search` and confirm `Web Search Used` and `Citations`
    are visible when a web retrieval provider is configured.
