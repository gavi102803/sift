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

All non-mock profiles currently use the lightweight runtime adapter layer. Provider configuration is not read from `.env`; use the iOS Profile screen, which persists provider-specific base URLs, API keys, models, and web retrieval settings in `.data/model-provider.json`.

When web search is enabled, Sift performs retrieval before concept generation and follow-up answers. The default `ddgs` provider uses DuckDuckGo and does not require a separate API key. API-key web providers are configured from the Profile screen. Answers can return citations that iOS displays under the response.

Follow-up turns also expose `POST /v1/concepts/{concept_id}/turns/stream`, which returns newline-delimited JSON events:

- `{"type":"started"}`
- `{"type":"delta","delta":"..."}`
- `{"type":"completed","response":{...}}`

The backend streams user-visible answer deltas while buffering and validating the complete structured model JSON before applying note patches, proposals, citations, and persistence.

The iOS Profile tab can save the provider type, base URL, API key, and model. Saved provider settings are stored under `.data/model-provider.json`, which is ignored by Git. API keys are returned to iOS only as a masked preview.

Provider model discovery uses `GET {baseURL}/models` when the selected provider exposes that endpoint.

If no provider key is configured, the backend uses deterministic mock concept cards and follow-up responses for local UI work.
