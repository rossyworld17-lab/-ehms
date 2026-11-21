#!/bin/sh
# Nightly PostgreSQL backup with retention and verification.
# Used by the `backup` service in docker-compose.yml; can also be run from cron on the host.
set -eu
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
OUT=/backups/ehms-$STAMP.dump
pg_dump -h "${PGHOST:-db}" -U "${PGUSER:-ehms}" -d "${PGDATABASE:-ehms}" -Fc -f "$OUT"
# verify the archive is readable before trusting it
if pg_restore --list "$OUT" > /dev/null; then
  echo "$(date -u) backup OK: $OUT ($(du -h "$OUT" | cut -f1))"
else
  echo "$(date -u) BACKUP VERIFICATION FAILED: $OUT" >&2
  exit 1
fi
find /backups -name 'ehms-*.dump' -mtime +"${BACKUP_RETENTION_DAYS:-14}" -delete
