# Sift Backend

FastAPI backend for Sift.

The backend owns the trimmed Hermes-style runtime: model provider profiles, web retrieval providers, context-pack construction, structured output validation, patch/merge rules, proposal handling, and model telemetry. iOS calls this backend only; it never talks directly to upstream model providers.

## Local Setup

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
copy .env.example .env
uvicorn sift_backend.main:app --reload
```

Health check:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/health
```

Tests:

```powershell
pytest
```

MVP API smoke test, after `uvicorn` is running on `127.0.0.1:8000`, or with a temporary
server started by the script:

```bash
cd ..
python3 scripts/smoke-backend-mvp.py
python3 scripts/smoke-backend-mvp.py --start-server
python3 scripts/smoke-backend-mvp.py --start-server --check-web-search
```

Provider-backed E2E smoke check, useful before manual Simulator validation:

```bash
python3 scripts/smoke-backend-mvp.py \
  --start-server \
  --require-provider custom \
  --check-web-search \
  --require-web-search-used \
  --allow-model-variance \
  --capture "latest web search changes in 2026"
```

## Model Providers

Sift uses a trimmed Hermes-style runtime. Model access is configured through provider profiles:

- `openai`
- `deepseek`
- `openrouter`
- `nous`
- `kimi`
- `custom`
- `mock`

All non-mock profiles currently use the OpenAI-compatible Chat Completions adapter. Native Anthropic/Gemini adapters are intentionally not claimed until implemented.

```bash
cp .env.example .env
# then edit .env:
SIFT_RUNTIME_PROVIDER=deepseek
SIFT_RUNTIME_BASE_URL=https://api.deepseek.com/v1
SIFT_RUNTIME_API_KEY=your-provider-key
SIFT_RUNTIME_MODEL=deepseek-chat
SIFT_RUNTIME_WEB_SEARCH_ENABLED=true
SIFT_WEB_SEARCH_PROVIDER=ddgs
SIFT_WEB_SEARCH_API_KEY=
```

Process environment variables override `.env`, which is useful for temporary provider tests.

When web search is enabled, Sift performs retrieval before concept generation and follow-up answers. The default `ddgs` provider uses DuckDuckGo and does not require a separate API key. `tavily` remains available when `SIFT_WEB_SEARCH_API_KEY` is configured. Answers can return citations that iOS displays under the response.

Follow-up turns also expose `POST /v1/concepts/{concept_id}/turns/stream`, which returns newline-delimited JSON events:

- `{"type":"started"}`
- `{"type":"delta","delta":"..."}`
- `{"type":"completed","response":{...}}`

The backend streams user-visible answer deltas while buffering and validating the complete structured model JSON before applying note patches, proposals, citations, and persistence.

Provider profiles can be selected from the iOS Profile tab or configured directly:

```bash
SIFT_RUNTIME_PROVIDER=openrouter
SIFT_RUNTIME_BASE_URL=https://openrouter.ai/api/v1
SIFT_RUNTIME_API_KEY=your-provider-key
SIFT_RUNTIME_MODEL=openai/gpt-5.5
```

The iOS Profile tab can save the provider type, base URL, API key, and model. Saved provider settings are stored under `backend/.data/model-provider.json`, which is ignored by Git. API keys are returned to iOS only as a masked preview.

Provider model discovery uses `GET {baseURL}/models` when the selected provider exposes that endpoint.

If no provider key is configured, the backend uses deterministic mock concept cards and follow-up responses for local UI work.
