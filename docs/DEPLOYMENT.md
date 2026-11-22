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

## Background worker (reminders and message delivery)
The web process runs a worker every `EHMS_WORKER_INTERVAL` seconds (default 60): day-before arrival reminders,
birthday greetings (consenting guests), daily low-stock and supplier-invoice alerts, and delivery of queued
email/SMS/WhatsApp messages (3 attempts, then `failed` with the provider error). Each reminder is sent once
(`job_runs`). With several app instances set `EHMS_WORKER=0` on all but one, or run it separately:
```bash
docker compose exec app python -m ehms.worker          # one cycle
docker compose exec app python -m ehms.worker --loop   # continuous
```
Administrators can also trigger a cycle from **Messaging → Delivery log → Run reminders & deliver now**.

## Email
Set `EHMS_SMTP_HOST`, `EHMS_SMTP_PORT`, `EHMS_SMTP_USER`, `EHMS_SMTP_PASSWORD`, `EHMS_SMTP_FROM`. Messages created
before a provider was configured stay `not_configured`; once configured, use **Retry** in the delivery log.

## SMS (Termii) and WhatsApp (Meta Cloud API)
- SMS: `EHMS_TERMII_API_KEY`, `EHMS_TERMII_SENDER` (an approved sender ID).
- WhatsApp: `EHMS_WHATSAPP_TOKEN`, `EHMS_WHATSAPP_PHONE_ID`. Free-text messages are only delivered inside
  WhatsApp's 24-hour customer-service window; for reminders outside it, register approved message templates
  with Meta. Both adapters are in `ehms/notify.py`; other providers can be added there.
Edit message wording per event and channel in **Administration → Messaging**.

## Online payments (Paystack / Flutterwave)
1. Set `PAYSTACK_SECRET_KEY` and/or `FLUTTERWAVE_SECRET_KEY` (+ `FLUTTERWAVE_WEBHOOK_HASH`), optionally
   `EHMS_PAYMENT_PROVIDER` (preferred provider) and `EHMS_PUBLIC_URL` (e.g. `https://hotel.example.com`).
2. Register the webhook URL with the provider:
   `https://<your-domain>/api/public/webhooks/paystack` or `.../flutterwave`.
3. Guests return to `https://<your-domain>/payment-return`, which confirms the payment with the provider.
An "Online payment" method (posting to *Online Payments Clearing*) is created automatically on first use.
A payment is recorded only after the provider's verify API confirms it with the expected amount and currency,
once per reference, whichever of the webhook or return page arrives first. Settlements from the provider are
reconciled against *Online Payments Clearing* in **Finance operations → Bank reconciliation**. Every call
and webhook is logged under **Finance operations → Online payments**.

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

## Documents and the assistant (release 0.9)
- Uploaded documents and scheduled-report files are stored in the `documents` volume (`EHMS_DOCUMENT_DIR`,
  `/data/documents` in the container). The `backup` service archives it next to each database dump
  (`ehms-documents-<stamp>.tar.gz`); restore both together (`restore.sh <dump> <documents archive>`).
- `EHMS_MAX_UPLOAD_MB` (default 10) limits uploads; `EHMS_MAX_BODY_MB` (default 16) limits any request body.
  If a reverse proxy sits in front, allow bodies of at least that size (e.g. Nginx `client_max_body_size 16m`).
- Optional Claude engine for Ask EHMS: `pip install anthropic`, then `EHMS_AI_PROVIDER=anthropic`,
  `ANTHROPIC_API_KEY=…` (and optionally `EHMS_AI_MODEL`). Leave unset to keep all data on your server.

## Production settings checklist (release 1.0)
- `EHMS_ENV=production` makes start-up refuse a missing/short/placeholder `EHMS_SECRET_KEY` and `EHMS_SEED_DEMO=1`.
- `FORWARDED_ALLOW_IPS` = the reverse proxy's address (the container trusts forwarded client addresses only from it);
  `WEB_CONCURRENCY` = number of app processes (≈ vCPUs); `EHMS_DB_POOL_SIZE` (default 10) per process — keep
  processes × pool below PostgreSQL `max_connections`.
- Add a login rate limit at the proxy as well (the built-in limiter is per process), e.g. Nginx
  `limit_req_zone $binary_remote_addr zone=login:10m rate=10r/m;` on `/api/auth/`.
- For more than one server, run the worker once separately (`EHMS_WORKER=0` on web processes).
- Performance and security reviews: [PERFORMANCE.md](PERFORMANCE.md), [SECURITY.md](SECURITY.md); go-live checklist:
  [ACCEPTANCE.md](ACCEPTANCE.md).

## Monitoring
`GET /api/health` (used by the container health check) returns database connectivity. Ship container logs to
your log platform; failed logins and lockouts are in the `login_attempts` table and audit trail.
