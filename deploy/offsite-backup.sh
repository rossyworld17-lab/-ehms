#!/usr/bin/env bash
# Copy EHMS's encrypted backups off the server (run daily from cron). Backups are already encrypted with
# EHMS_DATA_KEY, so they are safe on any storage you control.
#   sudo bash deploy/offsite-backup.sh /mnt/usb-drive/ehms           (a mounted disk)
#   sudo bash deploy/offsite-backup.sh user@backup-host:/srv/ehms     (another server, over SSH)
# Cron (02:30 every day):  30 2 * * * cd /opt/ehms && bash deploy/offsite-backup.sh user@backup-host:/srv/ehms
set -euo pipefail
cd "$(dirname "$0")/.."
DEST=${1:?usage: offsite-backup.sh <local folder or user@host:/path>}
TMP=$(mktemp -d)
docker compose cp app:/data/backups/. "$TMP/"
if [[ "$DEST" == *:* ]]; then rsync -a "$TMP/" "$DEST/"; else mkdir -p "$DEST" && cp -n "$TMP"/* "$DEST/" 2>/dev/null || true; fi
rm -rf "$TMP"
echo "Copied $(ls "$DEST" 2>/dev/null | wc -l) backup file(s) to $DEST"
