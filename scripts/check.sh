#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-all}"

if [[ -x "$ROOT/backend/.venv/bin/python" ]]; then
  PYTHON="$ROOT/backend/.venv/bin/python"
else
  PYTHON="${PYTHON:-python3}"
fi

check_backend() {
  cd "$ROOT"
  "$PYTHON" -m ruff check backend/src backend/tests scripts/smoke-backend-mvp.py scripts/local_mvp_doctor.py scripts/check_managed_deployment.py scripts/revoke_beta_owner.py
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

case "$TARGET" in
  backend)
    check_backend
    ;;
  ios)
    check_ios
    ;;
  all)
    check_backend
    check_ios
    ;;
  *)
    echo "usage: scripts/check.sh [backend|ios|all]" >&2
    exit 2
    ;;
esac
