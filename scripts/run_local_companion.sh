#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
HOST="${SIFT_BACKEND_HOST:-127.0.0.1}"
PORT="${SIFT_BACKEND_PORT:-8000}"
TAILNET_MODE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --tailnet)
      HOST="0.0.0.0"
      TAILNET_MODE=1
      shift
      ;;
    --host)
      HOST="${2:?--host requires a value}"
      shift 2
      ;;
    --port)
      PORT="${2:?--port requires a value}"
      shift 2
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: scripts/run_local_companion.sh [--tailnet] [--host HOST] [--port PORT]

Defaults:
  host: 127.0.0.1
  port: 8000

Options:
  --tailnet     Bind to 0.0.0.0 for Personal Tailscale dogfood.
                Use only on a trusted private network.
  --host HOST   Override bind host.
  --port PORT   Override port.
USAGE
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 2
      ;;
  esac
done

cd "$BACKEND_DIR"
mkdir -p "$ROOT_DIR/.data"

if [[ -x "$BACKEND_DIR/.venv/bin/python" ]]; then
  PYTHON="$BACKEND_DIR/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

echo "Starting Sift local companion at http://${HOST}:${PORT}"
echo "Simulator should use http://127.0.0.1:8000"
if [[ "$TAILNET_MODE" == "1" || "$HOST" == "0.0.0.0" ]]; then
  echo "Personal Tailnet dogfood: configure iPhone with https://<mac-machine>.<tailnet>.ts.net"
  echo "Do not expose this local backend to the public internet."
fi
exec "$PYTHON" -m uvicorn sift_backend.main:create_app --factory --host "$HOST" --port "$PORT" --reload
