#!/usr/bin/env bash
# Update EHMS to a newer release. Database migrations run automatically at start-up; a verified backup is taken first.
#   git pull   (or unzip the new release over this folder, keeping .env)
#   sudo bash deploy/update.sh
set -euo pipefail
cd "$(dirname "$0")/.."
echo "== Backup before update"
docker compose exec -T app python -m ehms.backup create
echo "== Rebuild and restart"
docker compose up -d --build
docker compose exec -T app python -m ehms.preflight || true
docker compose exec -T app python -c "import urllib.request,json;print(json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health')))"
