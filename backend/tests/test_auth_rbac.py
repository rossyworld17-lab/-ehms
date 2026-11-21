"""Authentication, MFA, lockout, sessions, RBAC and hotel scoping (FR-ADM-001..003, FR-PRP-004)."""
from ehms import security


def test_login_success_and_profile(client):
    out = client.login("admin@demo.ehms")
    assert out["user"]["email"] == "admin@demo.ehms"
    assert "reservations.create" in out["user"]["permissions"]
    assert {h["code"] for h in out["user"]["hotels"]} == {"CGL", "CSA"}


def test_wrong_password_rejected_and_logged(client):
    r = client.post("/api/auth/login", {"email": "admin@demo.ehms", "password": "nope"}, token=None)
    assert r.status_code == 401
    client.login("admin@demo.ehms")
    attempts = client.get("/api/admin/login-attempts").json()["items"]
    assert any(a["reason"] == "bad_password" for a in attempts)


def test_lockout_after_repeated_failures(client):
    for _ in range(5):
        client.post("/api/auth/login", {"email": "frontdesk@demo.ehms", "password": "bad"}, token=None)
    r = client.post("/api/auth/login", {"email": "frontdesk@demo.ehms", "password": "Demo@12345"}, token=None)
    assert r.status_code == 423


def test_unauthenticated_requests_rejected(client, hotel_id):
    assert client.get(f"/api/hotels/{hotel_id}/rooms", token=None).status_code == 401
    assert client.get(f"/api/hotels/{hotel_id}/rooms", token="garbage").status_code == 401


def test_permissions_enforced(client, hotel_id):
    client.login("housekeeper@demo.ehms")
    r = client.post(f"/api/hotels/{hotel_id}/reservations", {"arrival": "2030-01-01", "departure": "2030-01-02", "room_type_id": 1, "guest_id": 1})
    assert r.status_code == 403
    assert client.get("/api/admin/users").status_code == 403
    assert client.get(f"/api/hotels/{hotel_id}/housekeeping/tasks").status_code == 200


def test_hotel_scope_enforced(client):
    client.login("frontdesk@demo.ehms")
    hotels = client.get("/api/hotels").json()["items"]
    assert [h["code"] for h in hotels] == ["CGL"]
    from ehms.db import get_db
    with get_db().tx() as c:
        other = c.scalar("SELECT id FROM hotels WHERE code = 'CSA'")
    assert client.get(f"/api/hotels/{other}/rooms").status_code == 403


def test_logout_and_session_revocation(client):
    client.login("frontdesk@demo.ehms")
    token = client.token
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me", token=token).status_code == 401
    # admin revokes another user's session
    client.login("frontdesk@demo.ehms")
    victim = client.token
    client.login("admin@demo.ehms")
    users = client.get("/api/admin/users").json()["items"]
    uid = next(u["id"] for u in users if u["email"] == "frontdesk@demo.ehms")
    sessions = client.get(f"/api/admin/users/{uid}/sessions").json()["items"]
    for s in sessions:
        assert client.post(f"/api/admin/sessions/{s['id']}/revoke").status_code == 200
    assert client.get("/api/auth/me", token=victim).status_code == 401


def test_mfa_enrolment_and_login(client):
    client.login("gm@demo.ehms")
    setup = client.post("/api/auth/mfa/setup").json()
    assert client.post("/api/auth/mfa/enable", {"code": "000000"}).status_code == 400
    assert client.post("/api/auth/mfa/enable", {"code": security.totp_now(setup["secret"])}).status_code == 200
    r = client.post("/api/auth/login", {"email": "gm@demo.ehms", "password": "Demo@12345"}, token=None).json()
    assert r["mfa_required"] is True
    pending = r["token"]
    assert client.get("/api/auth/me", token=pending).status_code == 401  # cannot use app before MFA
    bad = client.post("/api/auth/mfa/verify", {"code": "123456"}, token=pending)
    assert bad.status_code == 401
    ok = client.post("/api/auth/mfa/verify", {"code": security.totp_now(setup["secret"])}, token=pending)
    assert ok.status_code == 200
    assert client.get("/api/auth/me", token=ok.json()["token"]).status_code == 200


def test_user_admin_and_suspension(client, hotel_id):
    client.login("admin@demo.ehms")
    roles = client.get("/api/admin/roles").json()["items"]
    rid = next(r["id"] for r in roles if r["code"] == "receptionist")
    weak = client.post("/api/admin/users", {"email": "new@demo.ehms", "full_name": "New Person", "password": "short", "role_ids": [rid], "hotel_ids": [hotel_id]})
    assert weak.status_code == 400
    r = client.post("/api/admin/users", {"email": "new@demo.ehms", "full_name": "New Person", "password": "Welcome@2026x", "role_ids": [rid], "hotel_ids": [hotel_id]})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    assert client.post(f"/api/admin/users/{uid}/status", {"status": "suspended"}).status_code == 200
    r = client.post("/api/auth/login", {"email": "new@demo.ehms", "password": "Welcome@2026x"}, token=None)
    assert r.status_code == 403
    logs = client.get("/api/admin/audit-logs", params={"entity": "user", "entity_id": str(uid)}).json()["items"]
    assert {l["action"] for l in logs} >= {"user.created", "user.status_changed"}


def test_cannot_grant_permissions_you_lack(client, hotel_id):
    client.login("admin@demo.ehms")
    role = client.post("/api/admin/roles", {"name": "User Clerk", "permissions": ["admin.users.view", "admin.users.manage"]}).json()
    u = client.post("/api/admin/users", {"email": "clerk@demo.ehms", "full_name": "Clerk", "password": "Welcome@2026x",
                                         "role_ids": [role["id"]], "hotel_ids": [hotel_id]}).json()
    roles = client.get("/api/admin/roles").json()["items"]
    super_id = next(r["id"] for r in roles if r["code"] == "super_admin")
    client.login("clerk@demo.ehms", "Welcome@2026x")
    r = client.patch(f"/api/admin/users/{u['id']}", {"role_ids": [super_id]})
    assert r.status_code == 403  # privilege escalation blocked


def test_password_hashing():
    h = security.hash_password("Correct-Horse-9")
    assert h.startswith("scrypt$") and security.verify_password("Correct-Horse-9", h)
    assert not security.verify_password("wrong", h)
