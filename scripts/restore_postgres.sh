#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "${SIFT_POSTGRES_DSN:-}" || "${SIFT_CONFIRM_RESTORE:-}" != "yes" ]]; then
  echo "usage: SIFT_POSTGRES_DSN=<postgres-dsn> SIFT_CONFIRM_RESTORE=yes scripts/restore_postgres.sh <backup-file>" >&2
  exit 2
fi

pg_restore --clean --if-exists --no-owner --no-privileges --dbname="$SIFT_POSTGRES_DSN" "$1"
echo "Restore completed from: $1"
