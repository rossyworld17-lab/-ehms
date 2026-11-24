#!/usr/bin/env bash
# EHMS one-command installer for a fresh Ubuntu 22.04 / 24.04 server (2 vCPU, 4 GB RAM, 40 GB disk or more).
#   1. Point your domain's DNS A record (e.g. ehms.myhotel.com) at this server's public IP.
#   2. Copy the EHMS folder to the server (git clone of your private repository, or unzip the release zip).
#   3. From that folder:   sudo bash deploy/install.sh
# It installs Docker, writes .env with random secrets, starts HTTPS + EHMS + PostgreSQL + worker, runs the go-live
# checks and creates your organisation, first hotel and owner account.
set -euo pipefail
cd "$(dirname "$0")/.."
[ "$(id -u)" = 0 ] || { echo "Run with sudo: sudo bash deploy/install.sh"; exit 1; }

ask() { local v; read -r -p "$1: " v; while [ -z "$v" ]; do read -r -p "$1 (required): " v; done; printf '%s' "$v"; }
rand() { python3 -c "import secrets;print(secrets.token_urlsafe($1))"; }

if ! command -v docker >/dev/null 2>&1; then
  echo "== Installing Docker"
  apt-get update -qq && apt-get install -y -qq ca-certificates curl python3 >/dev/null
  curl -fsSL https://get.docker.com | sh
fi
command -v python3 >/dev/null || apt-get install -y -qq python3

if [ -f .env ]; then
  echo "== .env exists — keeping your settings and secrets"
else
  echo "== Settings"
  DOMAIN=$(ask "Domain for EHMS (DNS must already point here, e.g. ehms.myhotel.com)")
  EMAIL=$(ask "Email for certificate notices (e.g. it@myhotel.com)")
  sed -e "s#^EHMS_DOMAIN=.*#EHMS_DOMAIN=$DOMAIN#" \
      -e "s#^ACME_EMAIL=.*#ACME_EMAIL=$EMAIL#" \
      -e "s#^EHMS_PUBLIC_URL=.*#EHMS_PUBLIC_URL=https://$DOMAIN#" \
      -e "s#^POSTGRES_PASSWORD=.*#POSTGRES_PASSWORD=$(rand 32)#" \
      -e "s#^EHMS_SECRET_KEY=.*#EHMS_SECRET_KEY=$(rand 48)#" \
      -e "s#^EHMS_DATA_KEY=.*#EHMS_DATA_KEY=$(python3 -c 'import base64,os;print(base64.b64encode(os.urandom(32)).decode())')#" \
      -e "s#^EHMS_SECURITY_CONTACT=.*#EHMS_SECURITY_CONTACT=$EMAIL#" \
      .env.example > .env
  chmod 600 .env
  echo
  echo "  !! Copy EHMS_DATA_KEY from .env into your password manager NOW. Without it, backups cannot be restored."
  grep '^EHMS_DATA_KEY=' .env
  read -r -p "  Press Enter once you have saved it… " _
fi

echo "== Building and starting (first build takes a few minutes)"
docker compose up -d --build
echo -n "== Waiting for EHMS to start"
for i in $(seq 1 60); do
  if docker compose exec -T app python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health')" >/dev/null 2>&1; then echo " ok"; break; fi
  echo -n "."; sleep 3
done

echo "== Go-live checks"
docker compose exec -T app python -m ehms.preflight || true

if [ "$(docker compose exec -T db psql -U ehms -d ehms -tAc 'SELECT COUNT(*) FROM organisations' 2>/dev/null | tr -d '[:space:]')" = "0" ]; then
  echo "== Create your organisation, first hotel and owner account"
  ORG=$(ask "Company name (e.g. Crestview Hotels Ltd)")
  ORGC=$(ask "Company short code (letters, e.g. CHL)")
  HOTEL=$(ask "Hotel name")
  HOTELC=$(ask "Hotel short code (letters, e.g. CGL)")
  ADMIN=$(ask "Owner's email")
  ADMINN=$(ask "Owner's full name")
  docker compose exec -T app python -m ehms.seed bootstrap --org "$ORG" --org-code "$ORGC" --hotel "$HOTEL" --hotel-code "$HOTELC" \
    --admin-email "$ADMIN" --admin-name "$ADMINN"
fi

DOMAIN=$(grep '^EHMS_DOMAIN=' .env | cut -d= -f2)
cat <<MSG

EHMS is live:
  Website:        https://$DOMAIN
  Staff sign-in:  https://$DOMAIN/staff   (change the temporary password, then set up two-step verification)

Next steps (docs/DEPLOYMENT.md has the details):
  - Hotel settings, rooms & rates, users and roles; publish the website (Administration → Website)
  - Email/SMS/payment keys in .env, then: docker compose up -d
  - Copy backups off the server daily: sudo bash deploy/offsite-backup.sh <destination>
  - Updates: sudo bash deploy/update.sh
MSG
