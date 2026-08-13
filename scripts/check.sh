#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-all}"

if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT/backend/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

if [[ -x "$ROOT/cloudflare/.venv/bin/python" ]]; then
  WORKER_PYTHON="$ROOT/cloudflare/.venv/bin/python"
else
  WORKER_PYTHON="${WORKER_PYTHON:-python3}"
fi

check_backend() {
  cd "$ROOT"
  "$PYTHON" -m ruff check backend/src backend/tests scripts/smoke-backend-mvp.py scripts/local_mvp_doctor.py scripts/check_managed_deployment.py scripts/revoke_beta_owner.py scripts/evaluate_continuity.py scripts/model_run_metrics.py scripts/recovery_dogfood.py
  "$PYTHON" -m pytest backend
}

check_ios() {
  cd "$ROOT"
  xcodebuild test \
    -project ios/Sift.xcodeproj \
    -scheme Sift \
    -destination "${SIFT_IOS_TEST_DESTINATION:-platform=iOS Simulator,name=iPhone 17 Pro}" \
    CODE_SIGNING_ALLOWED=NO
}

check_worker() {
  cd "$ROOT/cloudflare"
  "$WORKER_PYTHON" -m ruff check src tests verification
  "$WORKER_PYTHON" -m pytest -q
}

case "$TARGET" in
  backend)
    check_backend
    ;;
  ios)
    check_ios
    ;;
  worker)
    check_worker
    ;;
  all)
    check_backend
    check_worker
    check_ios
    ;;
  *)
    echo "usage: scripts/check.sh [backend|worker|ios|all]" >&2
    exit 2
    ;;
esac
