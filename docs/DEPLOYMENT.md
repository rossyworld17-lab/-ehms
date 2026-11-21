# Deployment, backup and recovery

## Requirements
Docker 24+ with Compose, a Linux server (2 vCPU / 4 GB RAM is ample for a single hotel), a domain name and TLS.

## Install
```bash
git clone <your-repo> ehms && cd ehms
cp .env.example .env
python3 -c "import secrets;print(secrets.token_urlsafe(48))"   # paste into EHMS_SECRET_KEY
# set a strong POSTGRES_PASSWORD
docker compose up -d --build
docker compose logs -f app        # migrations run automatically on start
docker compose exec app python -m ehms.seed bootstrap --org "Your Company Ltd" --org-code YCL \
   --hotel "Your Hotel" --hotel-code YH --admin-email you@example.com --admin-name "Your Name"
```

## TLS / reverse proxy
Expose the app only through HTTPS. Example Caddyfile:
```
hotel.example.com {
    reverse_proxy 127.0.0.1:8000
}
```
Set `EHMS_ENV=production` (enables HSTS). The app trusts `X-Forwarded-For` from the proxy for audit IPs.

## Email
Set `EHMS_SMTP_HOST`, `EHMS_SMTP_PORT`, `EHMS_SMTP_USER`, `EHMS_SMTP_PASSWORD`, `EHMS_SMTP_FROM`. Queued messages
are delivered by:
```bash
docker compose exec app python -c "from ehms.notify import deliver_queued; print(deliver_queued())"
```
Schedule it every minute (host cron or a small worker container). Messages created before SMTP was configured
stay `not_configured` and are not re-sent automatically.

## SMS / WhatsApp
Adapters are an integration point in `ehms/notify.py` (`provider_for` and `deliver_queued`). Add the chosen
provider (e.g. Termii, Twilio, Meta WhatsApp Cloud API) under its commercial terms; until then messages are
recorded as `not_configured`.

## Online payments (Paystack / Flutterwave)
Online card payments must be confirmed by the gateway, never typed in. To enable:
1. Add a payment method of kind **online** mapped to *Online Payments Clearing*.
2. Implement the gateway adapter: initialise a transaction, and a webhook endpoint that verifies the signature
   (`x-paystack-signature` HMAC-SHA512 / Flutterwave `verif-hash`), re-queries the transaction status, and then
   posts the payment using the same posting function as manual payments with the gateway reference as the
   idempotency key.
3. Set `PAYSTACK_SECRET_KEY` or `FLUTTERWAVE_SECRET_KEY`. The booking engine shows "pay online" only when set.
This adapter is scheduled in the roadmap (Phase 6b); the system returns HTTP 501 for online payments until then.

## Backups
The `backup` service runs `deploy/backup.sh` daily: `pg_dump` custom format, verified with `pg_restore --list`,
retention `BACKUP_RETENTION_DAYS` (default 14). Copy the `backups` volume off-site (e.g. object storage) with
your preferred tool. Manual backup:
```bash
docker compose exec backup /bin/sh /backup.sh
```

## Restore / disaster recovery
```bash
docker compose stop app
docker compose run --rm -v "$PWD/deploy:/deploy" backup /bin/sh /deploy/restore.sh /backups/ehms-<stamp>.dump
docker compose start app
```
Test a restore into a staging server at least quarterly. Recovery point = last backup (add PostgreSQL WAL
archiving for point-in-time recovery if required).

## Upgrades
`git pull && docker compose up -d --build`. New migrations apply automatically; take a backup first.

## Monitoring
`GET /api/health` (used by the container health check) returns database connectivity. Ship container logs to
your log platform; failed logins and lockouts are in the `login_attempts` table and audit trail.
