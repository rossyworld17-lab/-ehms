"""Release 1.0 hardening: production start-up guards, SQL identifier validation, security headers, request size
limits, rate limits, and an automated authorisation audit of every API route (regression guard)."""
import inspect
import os
import re
import sys

import pytest

from ehms.db import Connection

# routes any signed-in user may call (self-service or hotel-scoped reference data)
SELF_SERVICE = {
    "/api/auth/mfa/verify", "/api/auth/logout", "/api/auth/me", "/api/auth/mfa/setup", "/api/auth/mfa/enable", "/api/auth/mfa/disable",
    "/api/auth/password", "/api/auth/sessions", "/api/hotels", "/api/hotels/{hotel_id:int}", "/api/hotels/{hotel_id:int}/taxes",
    "/api/hotels/{hotel_id:int}/payment-methods", "/api/payments/gateway-status", "/api/notifications/mine",
    "/api/notifications/{notification_id:int}/read", "/api/notifications/read-all", "/api/me/employee", "/api/me/leave", "/api/me/clock",
    "/api/payslips/{slip_id:int}.pdf", "/api/hotels/{hotel_id:int}/emergency-contacts",
    # release 1.1 self-service: each is limited to the signed-in employee's own record (or HR for letters)
    "/api/me/hr", "/api/me/requests", "/api/me/requests/{request_id:int}/cancel", "/api/me/leave/{leave_id:int}/cancel",
    "/api/me/appraisals/{appraisal_id:int}/acknowledge", "/api/hr/requests/{request_id:int}/letter.pdf",
}
SCOPE = re.compile(r"check_hotel|org_id|ctx\.user_id|organisation_id = \?|recipient = \?")


def _scoped(fn, depth=0) -> bool:
    src = inspect.getsource(fn)
    if SCOPE.search(src):
        return True
    if depth > 2:
        return False
    mod = sys.modules[fn.__module__]
    names = set(re.findall(r"\b(_?[a-z][a-z0-9_]*)\(c, ctx", src)) | set(re.findall(r"\b(_[a-z][a-z0-9_]*)\(", src)) | set(re.findall(r"return ([a-z_]+)\(ctx\)", src))
    for name in names:
        f = getattr(mod, name, None)
        if f is None and "pos_in_house" in name:
            from ehms.modules.pos import in_house as f
        if callable(f) and f is not fn and hasattr(f, "__code__"):
            try:
                if _scoped(f, depth + 1):
                    return True
            except (OSError, TypeError):
                pass
    return False


def test_every_route_is_authorised_and_scoped(client):
    from ehms.http import ROUTES
    unprotected = [r["path"] for r in ROUTES if not r["public"] and not r["perm"] and r["path"] not in SELF_SERVICE]
    assert not unprotected, f"routes without a permission: {unprotected}"
    # every public endpoint is rate-limited (the access-event intake is protected by its integration token instead)
    no_limit = [r["path"] for r in ROUTES if r["public"] and r["path"] != "/api/integrations/access-events" and "rate_limit=" not in inspect.getsource(r["fn"])]
    assert not no_limit, f"public routes without a rate limit: {no_limit}"
    unscoped = [f"{r['method']} {r['path']}" for r in ROUTES if "{" in r["path"] and not r["public"] and not _scoped(r["fn"])
                and r["path"] != "/api/hotels/{hotel_id:int}/laundry/in-house"]
    assert not unscoped, f"routes with an id but no hotel/organisation/user scope check: {unscoped}"


def test_sql_identifiers_are_validated():
    assert Connection._ident("reservations") == "reservations"
    for bad in ("x; DROP TABLE users", "name = 1 --", "Robert'", "a b", ""):
        with pytest.raises(ValueError):
            Connection._ident(bad)


def test_production_start_up_guards(monkeypatch):
    from ehms import app as appmod
    monkeypatch.setattr(appmod.settings, "environment", "production")
    monkeypatch.setattr(appmod.settings, "seed_demo", False)
    monkeypatch.setenv("EHMS_SECRET_KEY", "short")
    with pytest.raises(RuntimeError, match="EHMS_SECRET_KEY"):
        appmod.check_production_settings()
    monkeypatch.setenv("EHMS_SECRET_KEY", "CHANGE-ME-generate-with-python-c-import-secrets")
    with pytest.raises(RuntimeError):
        appmod.check_production_settings()
    monkeypatch.setenv("EHMS_SECRET_KEY", "k" * 48)
    appmod.check_production_settings()
    monkeypatch.setattr(appmod.settings, "seed_demo", True)
    with pytest.raises(RuntimeError, match="demo"):
        appmod.check_production_settings()


def test_security_headers_and_csp(client):
    r = client.get("/api/health")
    csp = r.headers.get("content-security-policy", "")
    assert "script-src 'self';" in csp and "unsafe-inline' ;" not in csp and "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert r.headers.get("x-frame-options") == "DENY" and r.headers.get("x-content-type-options") == "nosniff"
    docs = client.get("/api/docs").headers.get("content-security-policy", "")
    assert "script-src 'self' 'unsafe-inline'" in docs


def test_request_size_limit_and_public_rate_limit(client):
    os.environ["EHMS_MAX_BODY_MB"] = "0.001"
    try:
        r = client.post("/api/auth/login", {"email": "x@example.com", "password": "y" * 5000}, token=None)
        assert r.status_code == 413
    finally:
        os.environ.pop("EHMS_MAX_BODY_MB")
    from ehms.http import _rate
    _rate.clear()
    codes = [client.get("/api/public/hotels/CGL", token=None).status_code for _ in range(62)]
    assert codes[0] == 200 and 429 in codes
