# Sift

Keep what's worth understanding.

Sift is a lightweight learning-notes app for quickly capturing a concept, asking follow-up questions, and turning model answers into durable concept cards.

## Current MVP Shape

- iOS SwiftUI app source in `ios/Sift`.
- FastAPI backend in `backend`.
- Backend calls a self-hosted LiteLLM proxy when `SIFT_LITELLM_API_KEY` is configured.
- Without LiteLLM configuration, the backend and iOS app fall back to deterministic mock flows for local UI work.

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

Optional LiteLLM-backed model calls:

```bash
export SIFT_LITELLM_BASE_URL="http://127.0.0.1:4000"
export SIFT_LITELLM_API_KEY="your-litellm-key"
export SIFT_MODEL_EXPLAIN="sift-explain"
```

If `SIFT_LITELLM_API_KEY` is empty, `/v1/concepts/{id}/turns` uses the mock model service.

Run checks:

```bash
cd backend
./.venv/bin/python -m ruff check .
./.venv/bin/python -m pytest
```

## iOS

Create an iOS 17+ SwiftUI app target named `Sift` in Xcode and add the source files under `ios/Sift`.

For Simulator backend calls, set this environment variable in the Xcode scheme:

```text
SIFT_BACKEND_BASE_URL=http://127.0.0.1:8000
```

If no backend URL is configured, the app uses `MockSiftAPIClient`.

## Smoke Test

1. Start the backend on `127.0.0.1:8000`.
2. Launch the iOS app in Simulator with `SIFT_BACKEND_BASE_URL` configured.
3. On the record tab, capture a concept such as `RAG`.
4. Open the generated concept card.
5. Ask a follow-up question.
6. Confirm that the answer appears and low-risk updates are merged into the note.
7. Ask a definition-changing question such as `Define this more precisely`.
8. Confirm that a pending update card appears, then test both `Confirm` and `Skip`.

