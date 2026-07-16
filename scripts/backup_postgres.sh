#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 || -z "${SIFT_POSTGRES_DSN:-}" ]]; then
  echo "usage: SIFT_POSTGRES_DSN=<postgres-dsn> scripts/backup_postgres.sh <backup-file>" >&2
  exit 2
fi

umask 077
pg_dump --format=custom --no-owner --no-privileges --file="$1" "$SIFT_POSTGRES_DSN"
echo "Backup created: $1"
