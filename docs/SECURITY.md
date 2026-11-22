# Security review — release 1.0

This is the internal security review carried out for release 1.0. It is not a substitute for an independent
penetration test, which should be commissioned before go-live (see "Residual risks").

## Controls

| Area | Control | Where |
|---|---|---|
| Authentication | Passwords hashed with scrypt (per-user salt), constant-time comparison; minimum length and complexity; lockout after 5 failures for 15 minutes; failed and successful logins recorded | `security.py`, `modules/auth.py`, `login_attempts` |
| Multi-factor | TOTP (RFC 6238) enrolment with verification; MFA-pending sessions can only complete MFA | `modules/auth.py` |
| Sessions | Short-lived signed tokens (HS256 pinned) bound to a server-side session (revocable); idle timeout 30 min; logout and administrator revocation; token kept in `sessionStorage` (cleared when the tab closes), never in cookies — so cross-site request forgery does not apply | `http.py`, `api.ts` |
| Authorisation | 122 permissions, 29 role templates, custom roles; every non-public endpoint declares a permission or is self-service; every endpoint taking a record id checks the hotel / organisation / user scope. Both rules are enforced by an automated test over all 383 routes (`test_hardening.py`) | `rbac.py`, `http.py` |
| Segregation of duties | Maker-checker on refunds, requisitions, purchase orders, supplier invoices, expense claims, payroll, leave, pricing rules, credit/debit notes, work-order verification, unusual-transaction reviews | each module, tested |
| Data scope | Multi-property: users see only assigned hotels; documents, reports and the assistant are filtered by permission and hotel | `http.py`, `documents.py`, `assistant.py` |
| Input validation | Typed field parsing, money as integer minor units, dates parsed strictly, enumerations checked; SQL always parameterised — table/column names come from code and are validated as plain identifiers in the database layer | `http.py`, `db.py` |
| Output / XSS | React escapes all output; Content-Security-Policy `script-src 'self'` (no inline scripts in the application), `object-src 'none'`, `frame-ancestors 'none'`; `X-Frame-Options: DENY`, `nosniff`, strict referrer policy; HSTS in production | `app.py` |
| File uploads | Extension whitelist plus content-signature check, size limit, sanitised names, random storage keys outside the web root, SHA-256 integrity check on every download, `Content-Disposition` and `nosniff` on downloads | `documents.py` |
| Rate limiting | Every public endpoint (login, password reset, booking engine, surveys, payment status, webhooks) is rate-limited per client address; request bodies limited to 16 MB | `http.py` |
| Integrations | Payment webhooks verified by HMAC signature and confirmed with the provider before crediting; access-control intake protected by a token; outbound calls logged with retries | `gateways.py`, `online.py`, `security.py` (module) |
| Audit | Append-only audit trail (database triggers prevent change or deletion), also for journal lines, stock movements and folio lines; document access history including refused attempts | migrations, `http.audit` |
| Secrets | Production start-up refuses a missing, short or placeholder `EHMS_SECRET_KEY` and refuses demo data; `.env` is never committed; API keys only in environment variables | `app.py`, `.env.example` |
| Network | TLS terminated at the reverse proxy; the app trusts `X-Forwarded-For` only from `FORWARDED_ALLOW_IPS` (default localhost) so clients cannot spoof their address to evade rate limits | `Dockerfile`, `DEPLOYMENT.md` |
| Data protection (NDPA 2023) | Consent captured for marketing; identity numbers masked; ID scans confidential and write-only for reception; applicants anonymised; retention periods per document category with legal hold; the optional external AI engine receives only aggregated figures and is off unless configured | various |
| Backup | Daily verified `pg_dump` plus documents archive, retention, documented restore | `deploy/` |

## Checks performed for 1.0

1. **Route authorisation audit** (automated, now a permanent test): every route either public (14, all
   rate-limited or token-protected), self-service (21, listed in the test) or permission-protected; every route
   with an id in its path performs a scope check (directly or in its loader).
2. **SQL injection review**: all f-string SQL fragments were reviewed — they interpolate only constants, placeholder
   lists or table names from fixed maps. Column-name keys of insert/update dictionaries come from whitelists;
   the database layer now rejects anything that is not a plain identifier.
3. **Authentication review**: algorithm pinning, session binding, idle expiry, lockout, MFA, reset-token handling
   (single use, expiring, same response whether or not the email exists).
4. **Header review**: CSP tightened (inline scripts no longer allowed outside the API reference page).
5. **Configuration review**: production guards added; forwarded-address trust restricted.
6. **Dependency review**: runtime dependencies are Starlette, Uvicorn, PyJWT, ReportLab, openpyxl, psycopg (plus
   optional `anthropic`); keep them updated with `pip list --outdated` monthly and rebuild the image.

## Findings fixed in 1.0

| # | Finding | Risk | Fix |
|---|---|---|---|
| 1 | Without `EHMS_SECRET_KEY` each process generated its own key — tokens failed at random with several workers and were invalidated on restart | Availability / misconfiguration | Production refuses to start without a strong shared key |
| 2 | The container trusted `X-Forwarded-For` from any source, so a client could rotate its apparent address to bypass rate limits | Brute-force protection bypass | Trust only `FORWARDED_ALLOW_IPS` |
| 3 | CSP allowed inline scripts | XSS impact | `script-src 'self'` for the application |
| 4 | Public hotel profile and payment webhooks had no rate limit | Resource abuse | Rate limits added |
| 5 | Column names in generic insert/update were not validated (callers were safe, but there was no safety net) | Defence in depth | Identifier validation |
| 6 | Notification panel could not be closed with keyboard or touch | Accessibility | Closes on Escape, outside click and navigation |

## Residual risks and recommendations

- Commission an **independent penetration test** and fix findings before go-live.
- The rate limiter is per process; behind several processes or servers the effective limit multiplies. Add a
  shared limiter at the reverse proxy or WAF (e.g. Nginx `limit_req`) for login and public endpoints.
- Encrypt the database and documents volumes at rest (cloud disk encryption or LUKS) and the off-site backup copy.
- Rotate `EHMS_SECRET_KEY` (signs everyone out) and provider keys at least yearly and when staff with access leave.
- Enforce MFA for all administrator, finance and HR roles by policy; the system supports it for every user.
- Keep the external AI engine off unless the hotel's data-protection assessment approves it.
