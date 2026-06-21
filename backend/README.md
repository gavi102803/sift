# Sift Backend

FastAPI backend for Sift.

The backend owns model access, context-pack construction, structured output validation, patch/merge rules, proposal handling, and model telemetry. iOS calls this backend only; it never talks directly to LiteLLM or upstream model providers.

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

