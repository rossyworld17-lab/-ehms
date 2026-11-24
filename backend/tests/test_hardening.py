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
    # release 1.2: own language preference; voucher PDFs check the permission of each voucher kind in the handler
    "/api/me/preferences", "/api/vouchers/{kind}/{voucher_id:int}.pdf",
    # release 1.3: website enquiries are open to website, guest-relations or events staff — checked in the handler
    "/api/hotels/{hotel_id:int}/website/enquiries", "/api/website/enquiries/{enquiry_id:int}/status",
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
    import base64
    from ehms import app as appmod
    from ehms import preflight
    monkeypatch.setattr(appmod.settings, "environment", "production")
    monkeypatch.setattr(appmod.settings, "seed_demo", False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://ehms:Str0ng-Database-Passw0rd-1@db:5432/ehms")
    monkeypatch.setenv("EHMS_DATA_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("EHMS_SECRET_KEY", "short")
    with pytest.raises(RuntimeError, match="EHMS_SECRET_KEY"):
        appmod.check_production_settings()
    monkeypatch.setenv("EHMS_SECRET_KEY", "CHANGE-ME-generate-with-python-c-import-secrets")
    with pytest.raises(RuntimeError):
        appmod.check_production_settings()
    monkeypatch.setenv("EHMS_SECRET_KEY", "k" * 48)
    appmod.check_production_settings()                     # everything required is now set
    monkeypatch.setattr(appmod.settings, "seed_demo", True)
    with pytest.raises(RuntimeError, match="[Dd]emo"):
        appmod.check_production_settings()
    monkeypatch.setattr(appmod.settings, "seed_demo", False)
    # 1.4: the data-encryption key, PostgreSQL and a strong database password are required in production
    monkeypatch.delenv("EHMS_DATA_KEY")
    with pytest.raises(RuntimeError, match="EHMS_DATA_KEY"):
        appmod.check_production_settings()
    monkeypatch.setenv("EHMS_DATA_KEY", base64.b64encode(b"x" * 32).decode())
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./ehms.db")
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        appmod.check_production_settings()
    monkeypatch.setenv("DATABASE_URL", "postgresql://ehms:ehms@db:5432/ehms")
    with pytest.raises(RuntimeError, match="password"):
        appmod.check_production_settings()
    monkeypatch.setenv("DATABASE_URL", "postgresql://ehms:Str0ng-Database-Passw0rd-1@db:5432/ehms")
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "*")
    with pytest.raises(RuntimeError, match="Forwarded"):
        appmod.check_production_settings()
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "127.0.0.1")
    levels = {name: level for level, name, _ in preflight.checks()}
    assert levels["Two-step verification"] == "OK" and levels["Public address"] == "WARN"


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


# ------------------------------------------------------------------ release 1.4 hardening
def test_sensitive_fields_are_encrypted_at_rest(client):
    from ehms.db import get_db
    client.login("hrmanager@demo.ehms")
    with get_db().tx() as c:
        e = c.one("SELECT id FROM employees WHERE bank_account_number IS NOT NULL ORDER BY id")
        raw = c.execute("SELECT bank_account_number, tax_id, pension_pin FROM employees WHERE id = ?", [e["id"]]).fetchone()
        assert all(str(v).startswith("enc:v1:") for v in raw if v)          # stored encrypted
        assert not str(c.one("SELECT bank_account_number FROM employees WHERE id = ?", [e["id"]])["bank_account_number"]).startswith("enc:")
    detail = client.get(f"/api/employees/{e['id']}").json()
    assert detail["bank_account_number"] and not detail["bank_account_number"].startswith("enc:")
    # a guest's identity number written through the API is encrypted too
    client.login("frontdesk@demo.ehms")
    g = client.post("/api/guests", {"first_name": "Enc", "last_name": "Test", "email": "enc.test@example.com", "id_type": "passport", "id_number": "A12345678", "force": True}).json()
    with get_db().tx() as c:
        stored = c.execute("SELECT id_number FROM guests WHERE id = ?", [g["id"]]).fetchone()[0]
    assert stored.startswith("enc:v1:") and "A12345678" not in stored


def test_crypto_values_and_files(tmp_path):
    from ehms import crypto
    v = crypto.encrypt_value("0123456789")
    assert v.startswith("enc:v1:") and v != crypto.encrypt_value("0123456789")     # random nonce
    assert crypto.decrypt_value(v) == "0123456789" and crypto.encrypt_value(v) == v
    assert crypto.decrypt_value(v[:-4] + "AAAA") == "[encrypted — key mismatch]"
    src = tmp_path / "a.bin"
    src.write_bytes(os.urandom(crypto.CHUNK * 2 + 123))
    crypto.encrypt_file(str(src), str(tmp_path / "a.enc"))
    crypto.decrypt_file(str(tmp_path / "a.enc"), str(tmp_path / "a.out"))
    assert (tmp_path / "a.out").read_bytes() == src.read_bytes()
    data = (tmp_path / "a.enc").read_bytes()
    (tmp_path / "t.enc").write_bytes(data[: len(data) - crypto.CHUNK // 2])          # truncated
    with pytest.raises(ValueError):
        crypto.decrypt_file(str(tmp_path / "t.enc"), str(tmp_path / "t.out"))


def test_mfa_required_for_privileged_accounts(client, monkeypatch):
    from ehms import security
    monkeypatch.setenv("EHMS_REQUIRE_MFA", "privileged")
    client.login("gm@demo.ehms")
    me = client.get("/api/auth/me").json()
    assert me["mfa_enrollment_required"] is True
    blocked = client.get("/api/admin/users")
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "mfa_enrollment_required"
    secret = client.post("/api/auth/mfa/setup", {}).json()["secret"]
    assert client.post("/api/auth/mfa/enable", {"code": security.totp_now(secret)}).status_code == 200
    assert client.get("/api/admin/users").status_code == 200
    client.login("waiter@demo.ehms")                               # not privileged: no change
    assert client.get("/api/auth/me").json()["mfa_enrollment_required"] is False
    monkeypatch.setenv("EHMS_REQUIRE_MFA", "all")
    assert client.get("/api/auth/me").json()["mfa_enrollment_required"] is True


def test_password_blocklist_and_ip_throttle(client, monkeypatch):
    from ehms import security
    assert security.password_problems("Password123!")
    assert security.password_problems("Welcome2026")
    assert any("name" in p for p in security.password_problems("Adebayo-Strong-2026", "ngozi@hotel.ng", "Ngozi Adebayo"))
    assert not security.password_problems("Blue-Mango-Harbour-71")
    monkeypatch.setenv("EHMS_IP_MAX_FAILED_LOGINS", "3")
    for i in range(3):
        assert client.post("/api/auth/login", {"email": f"nobody{i}@demo.ehms", "password": "x"}, token=None).status_code == 401
    r = client.post("/api/auth/login", {"email": "admin@demo.ehms", "password": "Demo@12345"}, token=None)
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_many_failures"   # even the right password, from this address


def test_hardened_headers_assetlinks_and_manifest(client, monkeypatch):
    r = client.get("/api/health")
    assert r.headers.get("cross-origin-opener-policy") == "same-origin" and "payment=()" in r.headers.get("permissions-policy", "")
    assert client.get("/.well-known/assetlinks.json").json() == []
    monkeypatch.setenv("EHMS_ANDROID_PACKAGE", "ng.hotel.ehms")
    monkeypatch.setenv("EHMS_ANDROID_SHA256", "aa:bb:cc")
    al = client.get("/.well-known/assetlinks.json").json()
    assert al[0]["target"]["package_name"] == "ng.hotel.ehms" and al[0]["target"]["sha256_cert_fingerprints"] == ["AA:BB:CC"]
    m = client.get("/manifest.webmanifest").json()
    assert m["display"] == "standalone" and any(i["purpose"] == "maskable" for i in m["icons"])
    assert client.get("/.well-known/security.txt").status_code == 404
    monkeypatch.setenv("EHMS_SECURITY_CONTACT", "security@hotel.example")
    assert "mailto:security@hotel.example" in client.get("/.well-known/security.txt").text
