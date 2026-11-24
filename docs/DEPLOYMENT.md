# Going live: deployment, backup and recovery (release 1.4)

The production stack is one `docker compose` project on one server:

```
Internet ──443/80──▶ Caddy (HTTPS, automatic Let's Encrypt certificates)
                       │  edge network 172.30.10.0/24
                       ▼
                     EHMS app (website at /, staff system at /staff, API at /api)
                       │  internal network (no route to the internet)
                       ▼
                     PostgreSQL 16          EHMS worker (reminders, messages, reports, encrypted backups)
```

All EHMS containers run read-only, as a non-root user, with every Linux capability dropped and
`no-new-privileges`. Only Caddy publishes ports. The database is reachable only from the app and worker.

## 1. What you need
- A server: Ubuntu 22.04/24.04, 2 vCPU, 4 GB RAM and 40 GB disk is enough for one to three hotels
  (4 vCPU / 8 GB for a larger group). Any provider works: a local data centre, AWS, DigitalOcean, Hetzner, Azure.
- A domain name, e.g. `crestviewhotel.com`. Create a DNS **A record** (and AAAA for IPv6) for the domain
  and for `www` that points at the server's public IP address. Caddy obtains the certificate once DNS resolves.
- Ports 80 and 443 open in the provider's firewall.
- Optional now, needed later: an email (SMTP) account, Paystack/Flutterwave keys, a Termii SMS sender ID.

## 2. Install (about 15 minutes)
Copy the EHMS folder to the server (`git clone` of the private repository, or upload and unzip the release zip),
then:

```bash
cd /opt/ehms
sudo bash deploy/install.sh
```

The installer:
1. installs Docker if it is missing;
2. asks for the domain and an email for certificate notices, then writes `.env` with **random** values for
   `POSTGRES_PASSWORD`, `EHMS_SECRET_KEY` and `EHMS_DATA_KEY` (file mode 600);
3. shows `EHMS_DATA_KEY` once and asks you to store it in the hotel's password manager or safe — **without this
   key the encrypted ID/bank numbers and every backup are unreadable**;
4. builds and starts the stack, runs the go-live checks (`preflight`) and creates your company, first hotel
   and owner account (it prints a temporary password).

Then open `https://<your domain>/staff`, sign in, change the password and set up two-step verification
(required for owners, administrators, finance and HR — see `EHMS_REQUIRE_MFA`).

### Installing by hand
```bash
cp .env.example .env        # replace every CHANGE-ME (the comments show how to generate each value)
chmod 600 .env
docker compose up -d --build
docker compose exec app python -m ehms.preflight
docker compose exec app python -m ehms.seed bootstrap --org "Crestview Hotels Ltd" --org-code CHL \
  --hotel "Crestview Grand Lagos" --hotel-code CGL --admin-email owner@example.com --admin-name "Owner Name"
```

## 3. Go-live checks (preflight)
`docker compose exec app python -m ehms.preflight` prints every check. With `EHMS_ENV=production` the app
**refuses to start** while any check fails:

| Check | Fails when |
|---|---|
| Signing key | `EHMS_SECRET_KEY` shorter than 32 characters or a placeholder |
| Data encryption key | `EHMS_DATA_KEY` is not 32 random bytes in base64 |
| Separate keys | the two keys are the same |
| Demo data | `EHMS_SEED_DEMO=1` |
| Database / password | not PostgreSQL, or the database password is shorter than 16 characters |
| Cross-origin access | `EHMS_CORS_ORIGINS` lists a non-https origin |
| Forwarded addresses | `FORWARDED_ALLOW_IPS=*` |

Warnings (the app still starts): no https public address, two-step verification switched off, no email
provider, no payment provider.

## 4. Configuration reference
Every setting is in `.env.example` with a comment. After changing `.env`: `docker compose up -d`.

- **Email**: `EHMS_SMTP_HOST`, `EHMS_SMTP_PORT`, `EHMS_SMTP_USER`, `EHMS_SMTP_PASSWORD`, `EHMS_SMTP_FROM`.
  Messages created before a provider was configured stay `not_configured`; use **Retry** in the delivery log.
- **SMS / WhatsApp**: `EHMS_TERMII_API_KEY`, `EHMS_TERMII_SENDER`; `EHMS_WHATSAPP_TOKEN`, `EHMS_WHATSAPP_PHONE_ID`.
- **Online payments**: `PAYSTACK_SECRET_KEY` and/or `FLUTTERWAVE_SECRET_KEY` (+ `FLUTTERWAVE_WEBHOOK_HASH`).
  Register the webhook `https://<domain>/api/public/webhooks/paystack` (or `/flutterwave`) with the provider.
  A payment is recorded only after the provider's verify API confirms the amount and currency.
- **Security**: `EHMS_REQUIRE_MFA` (`privileged` default, `all`, `off`), `EHMS_ACCESS_TOKEN_MINUTES`,
  `EHMS_SESSION_IDLE_MINUTES`, `EHMS_MAX_FAILED_LOGINS`, `EHMS_LOCKOUT_MINUTES`, `EHMS_IP_MAX_FAILED_LOGINS`,
  `EHMS_MIN_PASSWORD_LENGTH`, `EHMS_API_DOCS` (off in production), `EHMS_SECURITY_CONTACT` (publishes
  `/.well-known/security.txt`).
- **Website and app**: `EHMS_WEBSITE_HOTEL` (hotel code shown at the main address), `EHMS_APP_NAME`,
  `EHMS_ANDROID_PACKAGE`, `EHMS_ANDROID_SHA256` (see [ANDROID_APP.md](ANDROID_APP.md)).
- **Assistant**: leave `EHMS_AI_PROVIDER` empty to keep all data on your server; `anthropic` + `ANTHROPIC_API_KEY`
  enables the Claude engine for Ask EHMS.
- **Uploads**: `EHMS_MAX_UPLOAD_MB` (default 10).

## 5. Backups
- The worker takes a **daily backup** of the whole database and all uploaded files, encrypts it with
  `EHMS_DATA_KEY` (AES-256-GCM, `.zip.enc`), test-restores it into a temporary database to prove it is readable,
  and deletes backups older than `EHMS_BACKUP_RETENTION_DAYS` (default 14). Failures raise an alert on the
  dashboard. Backups are kept in the `ehms-data` volume (`/data/backups`) with owner-only permissions.
- Take one now: **Administration → Backups → Back up now**, or `docker compose exec app python -m ehms.backup create`.
- **Copy backups off the server every day.** A backup on the same disk does not survive the loss of the server:
  ```bash
  sudo crontab -e
  # 02:30 daily, to another server over SSH (or a mounted disk path)
  30 2 * * * cd /opt/ehms && bash deploy/offsite-backup.sh backup@backup-host:/srv/ehms
  ```
  Backups are already encrypted, so any storage you control is safe. Keep `EHMS_DATA_KEY` **separately** from them.

## 6. Restore / disaster recovery
On the same or a new server (installed as in §2 with the **same `EHMS_DATA_KEY`**):
```bash
docker compose cp ehms-backup-<stamp>.zip.enc app:/data/backups/
docker compose exec app python -m ehms.backup verify /data/backups/ehms-backup-<stamp>.zip.enc
docker compose exec app python -m ehms.backup restore /data/backups/ehms-backup-<stamp>.zip.enc
docker compose restart app worker
```
Restoring is deliberately a server-side command (it replaces all data); **Administration → Backups** lists, verifies and
downloads backups.
Recovery point = the last backup (daily); recovery time ≈ 30 minutes on a prepared server. Rehearse a restore on a
spare server at least every quarter and record it.

## 7. Updates and rollback
```bash
git pull                     # or unzip the new release over the folder, keeping .env
sudo bash deploy/update.sh   # takes a verified backup, rebuilds, restarts, runs preflight and a health check
```
Database migrations run automatically at start-up and are forward-only. To roll back: restore the backup taken by
`update.sh` (§6) after checking out the previous release (`git checkout v1.3.0`, `docker compose up -d --build`).

## 8. Monitoring
- `GET https://<domain>/api/health` returns `{"status":"ok","version":…,"database":"postgresql"}`. Point an uptime
  monitor (e.g. UptimeRobot, Better Stack) at it.
- `docker compose ps` shows container health; `docker compose logs -f app worker` shows logs.
- Security events: failed logins and lockouts (`login_attempts`), the audit trail (**Administration → Audit log**,
  tamper-protected) and the backup register.
- Certificates renew automatically; Caddy logs any renewal problem.

## 9. Scaling
- `WEB_CONCURRENCY` = number of app processes (≈ vCPUs); `EHMS_DB_POOL_SIZE` (default 10) per process — keep
  processes × pool below PostgreSQL `max_connections` (100).
- For several app servers behind a load balancer, keep one worker service, put PostgreSQL on a managed service, and
  share `/data` (documents, website photos) on network storage.

## 10. Hardening the host
- Enable automatic security updates: `sudo apt install unattended-upgrades`.
- SSH with keys only (`PasswordAuthentication no`), and a host firewall allowing only 22, 80 and 443:
  `sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable`.
- Limit who can read `/opt/ehms/.env` (the installer sets mode 600).

## Windows demo
`start_demo_windows.bat` still runs the single-computer demo with fictional data (SQLite). It is for evaluation and
training only. Do not use it for a live hotel.
