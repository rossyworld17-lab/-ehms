"""Go-live readiness check (release 1.4).

    python -m ehms.preflight          # prints every check; exit code 1 if any check FAILS

In production (EHMS_ENV=production) the server runs the same checks at start-up and refuses to start while any
check fails, so an unsafe configuration can never go live by accident. Warnings are printed but do not stop it.
"""
from __future__ import annotations

import base64
import os
import sys
from urllib.parse import urlparse

PLACEHOLDERS = ("change-me", "changeme", "replace-me", "dev-secret", "secret", "example", "local-dev")


def checks() -> list[tuple[str, str, str]]:
    """[(level, name, message)] with level FAIL | WARN | OK."""
    from .config import settings
    out: list[tuple[str, str, str]] = []
    prod = settings.environment == "production"

    def add(ok: bool, name: str, good: str, bad: str, fail: bool = True):
        out.append(("OK" if ok else ("FAIL" if fail else "WARN"), name, good if ok else bad))

    key = os.environ.get("EHMS_SECRET_KEY", "")
    add(len(key) >= 32 and not any(p in key.lower() for p in PLACEHOLDERS), "Signing key",
        "EHMS_SECRET_KEY is set and strong", "EHMS_SECRET_KEY must be a random value of at least 32 characters (python -c \"import secrets;print(secrets.token_urlsafe(48))\")")
    dk = os.environ.get("EHMS_DATA_KEY", "")
    try:
        dk_ok = len(base64.b64decode(dk, validate=True)) == 32
    except Exception:
        dk_ok = False
    add(dk_ok, "Data encryption key", "EHMS_DATA_KEY is set (32 bytes)",
        "EHMS_DATA_KEY must be 32 random bytes in base64 (python -c \"import base64,os;print(base64.b64encode(os.urandom(32)).decode())\"); keep a copy offline",
        fail=prod)
    add(dk != key or not dk, "Separate keys", "Signing and encryption keys differ", "EHMS_DATA_KEY must not equal EHMS_SECRET_KEY")
    add(not settings.seed_demo, "Demo data", "Demo data is off",
        "EHMS_SEED_DEMO=1 loads fictional demo data — unset it for a live hotel", fail=prod)
    db = os.environ.get("DATABASE_URL", "sqlite:///./ehms.db")
    add(db.startswith("postgres") or os.environ.get("EHMS_ALLOW_SQLITE") == "1", "Database", "PostgreSQL",
        "Use PostgreSQL for a live hotel (DATABASE_URL=postgresql://…); SQLite is for the demo", fail=prod)
    if db.startswith("postgres"):
        pw = urlparse(db).password or ""
        add(len(pw) >= 16 and pw.lower() not in ("ehms", "postgres", "password"), "Database password", "Strong database password",
            "Use a database password of at least 16 random characters", fail=prod)
    url = os.environ.get("EHMS_PUBLIC_URL", "")
    add(url.startswith("https://"), "Public address", f"EHMS_PUBLIC_URL = {url}", "Set EHMS_PUBLIC_URL to the hotel's https:// address (links in emails, payments, the Android app)",
        fail=False)
    mfa = os.environ.get("EHMS_REQUIRE_MFA", "privileged" if prod else "off")
    add(mfa in ("privileged", "all"), "Two-step verification", f"Required for {mfa} accounts", "EHMS_REQUIRE_MFA=off — administrators and finance can sign in with a password alone",
        fail=False)
    cors = [o for o in os.environ.get("EHMS_CORS_ORIGINS", "").split(",") if o]
    add(all(o.startswith("https://") for o in cors), "Cross-origin access", "No insecure cross-origin callers", "EHMS_CORS_ORIGINS lists a non-https origin")
    add(bool(os.environ.get("EHMS_SMTP_HOST") or os.environ.get("SMTP_HOST")), "Email", "SMTP configured",
        "No email provider: confirmations, invoices and password resets are recorded but not sent", fail=False)
    add(bool(os.environ.get("PAYSTACK_SECRET_KEY") or os.environ.get("FLUTTERWAVE_SECRET_KEY")), "Online payments", "A payment provider is configured",
        "No payment provider: the booking engine offers pay-at-hotel only", fail=False)
    fwd = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
    add(fwd != "*", "Forwarded addresses", f"Trusted proxy: {fwd}", "FORWARDED_ALLOW_IPS=* lets clients fake their address and evade rate limits")
    return out


def errors() -> list[str]:
    return [f"{name}: {msg}" for level, name, msg in checks() if level == "FAIL"]


def main() -> int:  # pragma: no cover - command line
    res = checks()
    width = max(len(n) for _, n, _ in res)
    for level, name, msg in res:
        print(f"[{level:4}] {name.ljust(width)}  {msg}")
    fails = sum(1 for r in res if r[0] == "FAIL")
    warns = sum(1 for r in res if r[0] == "WARN")
    print(f"\n{fails} failing, {warns} warnings — {'NOT ready' if fails else 'ready'} for {os.environ.get('EHMS_ENV', 'development')}")
    return 1 if fails else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
