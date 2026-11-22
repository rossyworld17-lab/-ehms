#!/bin/sh
# Restore a backup into the database (DESTROYS current data). Stop the app first:
#   docker compose stop app
#   docker compose run --rm -v "$PWD/deploy:/deploy" backup /bin/sh /deploy/restore.sh /backups/ehms-YYYYMMDDTHHMMSSZ.dump
#   docker compose start app
set -eu
FILE=${1:?usage: restore.sh /backups/ehms-<stamp>.dump}
pg_restore -h "${PGHOST:-db}" -U "${PGUSER:-ehms}" -d "${PGDATABASE:-ehms}" --clean --if-exists --no-owner "$FILE"
echo "Restored $FILE"
# Restore the matching documents archive, if given (mount the documents volume read-write at /documents):
#   ... restore.sh /backups/ehms-<stamp>.dump /backups/ehms-documents-<stamp>.tar.gz
if [ "${2:-}" != "" ]; then
  tar -xzf "$2" -C /documents && echo "Restored documents from $2"
fi
