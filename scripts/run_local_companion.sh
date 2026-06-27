#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
HOST="${SIFT_BACKEND_HOST:-127.0.0.1}"
PORT="${SIFT_BACKEND_PORT:-8000}"

cd "$BACKEND_DIR"
mkdir -p "$ROOT_DIR/.data"

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

echo "Starting Sift local companion at http://${HOST}:${PORT}"
echo "Simulator should use http://127.0.0.1:8000"
exec "$PYTHON" -m uvicorn sift_backend.main:create_app --factory --host "$HOST" --port "$PORT" --reload
