"""User, role, session and audit administration. (FR-ADM-001/002/006, Section 11)"""
from __future__ import annotations

import secrets

from .. import security
from ..services import paginate
from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..rbac import PERMISSIONS


def _org_user(c, ctx: Ctx, user_id) -> dict:
    u = c.one("SELECT * FROM users WHERE id = ? AND organisation_id = ?", [int(user_id), ctx.org_id])
    if not u:
        raise not_found("User")
    return u


def _public_user(c, u: dict) -> dict:
    roles = c.all("SELECT r.id, r.code, r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = ?", [u["id"]])
    hotels = c.all("SELECT h.id, h.code, h.name FROM user_hotels uh JOIN hotels h ON h.id = uh.hotel_id WHERE uh.user_id = ?", [u["id"]])
    return {k: u[k] for k in ("id", "email", "full_name", "phone", "status", "department_id", "last_login_at", "created_at")} | {
        "all_hotels": bool(u["all_hotels"]), "mfa_enabled": bool(u["mfa_enabled"]),
        "locked": bool(u["locked_until"] and u["locked_until"] > now_iso()), "roles": roles, "hotels": hotels}


def _set_roles_hotels(c, ctx: Ctx, user_id: int, role_ids, hotel_ids, all_hotels: bool) -> None:
    if role_ids is not None:
        valid = {r["id"] for r in c.all("SELECT id FROM roles WHERE organisation_id = ?", [ctx.org_id])}
        role_ids = [int(r) for r in role_ids]
        if not set(role_ids) <= valid:
            raise bad_request("One or more roles are invalid")
        # Only holders of every permission in a role may grant it (prevents privilege escalation)
        for rid in role_ids:
            perms = {r["permission_code"] for r in c.all("SELECT permission_code FROM role_permissions WHERE role_id = ?", [rid])}
            if not perms <= ctx.permissions:
                raise forbidden("You cannot assign a role with permissions you do not hold")
        c.execute("DELETE FROM user_roles WHERE user_id = ?", [user_id])
        for rid in role_ids:
            c.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", [user_id, rid])
    if hotel_ids is not None:
        valid_h = {h["id"] for h in c.all("SELECT id FROM hotels WHERE organisation_id = ?", [ctx.org_id])}
        hotel_ids = [int(h) for h in hotel_ids]
        if not set(hotel_ids) <= valid_h:
            raise bad_request("One or more hotels are invalid")
        if ctx.hotel_ids is not None and not set(hotel_ids) <= ctx.hotel_ids:
            raise forbidden("You can only assign hotels you have access to")
        c.execute("DELETE FROM user_hotels WHERE user_id = ?", [user_id])
        for hid in hotel_ids:
            c.execute("INSERT INTO user_hotels (user_id, hotel_id) VALUES (?, ?)", [user_id, hid])
    if all_hotels and ctx.hotel_ids is not None:
        raise forbidden("Only users with organisation-wide access can grant it")


@route("GET", "/api/admin/users", perm="admin.users.view", tag="admin", summary="List users")
def list_users(ctx: Ctx):
    search = ctx.q("search")
    with get_db().tx() as c:
        sql, params = "SELECT * FROM users WHERE organisation_id = ?", [ctx.org_id]
        if search:
            sql += " AND (lower(full_name) LIKE ? OR lower(email) LIKE ?)"
            params += [f"%{search.lower()}%"] * 2
        rows = c.all(sql + " ORDER BY full_name", params)
        return {"items": [_public_user(c, u) for u in rows]}


@route("POST", "/api/admin/users", perm="admin.users.manage", tag="admin", summary="Create a user account")
def create_user(ctx: Ctx):
    email = str(ctx.field("email")).strip().lower()
    if "@" not in email:
        raise bad_request("A valid email is required", {"field": "email"})
    full_name = ctx.field("full_name", kind=str)
    temp = ctx.field("password", required=False) or ("Tmp-" + secrets.token_urlsafe(9) + "9a")
    problems = security.password_problems(temp)
    if problems:
        raise bad_request("Password " + "; ".join(problems), {"field": "password"})
    with get_db().tx() as c:
        if c.one("SELECT id FROM users WHERE lower(email) = ?", [email]):
            raise conflict("A user with this email already exists")
        all_hotels = bool(ctx.field("all_hotels", required=False, default=False))
        uid = c.insert("users", {"organisation_id": ctx.org_id, "email": email, "full_name": full_name,
                                 "phone": ctx.field("phone", required=False), "department_id": ctx.field("department_id", required=False),
                                 "password_hash": security.hash_password(temp), "status": "active", "all_hotels": 1 if all_hotels else 0,
                                 "must_change_password": 1, "created_at": now_iso(), "password_changed_at": now_iso()})
        _set_roles_hotels(c, ctx, uid, ctx.field("role_ids", required=False, default=[]), ctx.field("hotel_ids", required=False, default=[]), all_hotels)
        audit(c, ctx, "user.created", "user", uid, email, new={"email": email, "full_name": full_name})
        out = _public_user(c, c.one("SELECT * FROM users WHERE id = ?", [uid]))
    out["temporary_password"] = temp if not ctx.field("password", required=False) else None
    out["_created"] = True
    return out


@route("PATCH", "/api/admin/users/{user_id:int}", perm="admin.users.manage", tag="admin", summary="Update a user, roles and hotel access")
def update_user(ctx: Ctx):
    with get_db().tx() as c:
        u = _org_user(c, ctx, ctx.path["user_id"])
        changes = {}
        for f in ("full_name", "phone", "department_id"):
            if isinstance(ctx.body, dict) and f in ctx.body:
                changes[f] = ctx.body[f]
        if isinstance(ctx.body, dict) and "all_hotels" in ctx.body:
            changes["all_hotels"] = 1 if ctx.body["all_hotels"] else 0
        c.update("users", u["id"], changes)
        _set_roles_hotels(c, ctx, u["id"], (ctx.body or {}).get("role_ids"), (ctx.body or {}).get("hotel_ids"), bool(changes.get("all_hotels")))
        audit(c, ctx, "user.updated", "user", u["id"], u["email"], old={k: u.get(k) for k in changes}, new=changes | {
            "role_ids": (ctx.body or {}).get("role_ids"), "hotel_ids": (ctx.body or {}).get("hotel_ids")})
        return _public_user(c, c.one("SELECT * FROM users WHERE id = ?", [u["id"]]))


@route("POST", "/api/admin/users/{user_id:int}/status", perm="admin.users.manage", tag="admin", summary="Activate, suspend or deactivate a user")
def set_status(ctx: Ctx):
    status = ctx.field("status", kind=str)
    if status not in ("active", "suspended", "deactivated"):
        raise bad_request("status must be active, suspended or deactivated")
    with get_db().tx() as c:
        u = _org_user(c, ctx, ctx.path["user_id"])
        if u["id"] == ctx.user_id and status != "active":
            raise bad_request("You cannot suspend or deactivate your own account")
        c.execute("UPDATE users SET status = ?, failed_logins = 0, locked_until = NULL WHERE id = ?", [status, u["id"]])
        if status != "active":
            c.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", [now_iso(), u["id"]])
        audit(c, ctx, "user.status_changed", "user", u["id"], u["email"], old={"status": u["status"]}, new={"status": status})
        return _public_user(c, c.one("SELECT * FROM users WHERE id = ?", [u["id"]]))


@route("POST", "/api/admin/users/{user_id:int}/reset-password", perm="admin.users.manage", tag="admin",
       summary="Issue a temporary password and end the user's sessions")
def admin_reset_password(ctx: Ctx):
    temp = "Tmp-" + secrets.token_urlsafe(9) + "9a"
    with get_db().tx() as c:
        u = _org_user(c, ctx, ctx.path["user_id"])
        c.execute("UPDATE users SET password_hash = ?, must_change_password = 1, failed_logins = 0, locked_until = NULL, password_changed_at = ? WHERE id = ?",
                  [security.hash_password(temp), now_iso(), u["id"]])
        c.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", [now_iso(), u["id"]])
        audit(c, ctx, "user.password_reset_by_admin", "user", u["id"], u["email"])
    return {"temporary_password": temp}


@route("GET", "/api/admin/users/{user_id:int}/sessions", perm="admin.sessions.manage", tag="admin", summary="List a user's active sessions")
def user_sessions(ctx: Ctx):
    with get_db().tx() as c:
        u = _org_user(c, ctx, ctx.path["user_id"])
        return {"items": c.all("SELECT id, ip, user_agent, created_at, last_seen_at, expires_at FROM sessions "
                               "WHERE user_id = ? AND revoked_at IS NULL ORDER BY last_seen_at DESC", [u["id"]])}


@route("POST", "/api/admin/sessions/{session_id:int}/revoke", perm="admin.sessions.manage", tag="admin", summary="Revoke an active session")
def revoke_session(ctx: Ctx):
    with get_db().tx() as c:
        s = c.one("SELECT s.* FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.id = ? AND u.organisation_id = ?",
                  [ctx.path["session_id"], ctx.org_id])
        if not s:
            raise not_found("Session")
        c.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", [now_iso(), s["id"]])
        audit(c, ctx, "session.revoked", "session", s["id"], new={"user_id": s["user_id"]})
    return {"ok": True}


@route("GET", "/api/admin/permissions", perm="admin.users.view", tag="admin", summary="Permission catalogue")
def list_permissions(ctx: Ctx):
    return {"items": [{"code": k, "module": m, "description": d} for k, (m, d) in PERMISSIONS.items()]}


@route("GET", "/api/admin/roles", perm="admin.users.view", tag="admin", summary="List roles with permissions")
def list_roles(ctx: Ctx):
    with get_db().tx() as c:
        roles = c.all("SELECT * FROM roles WHERE organisation_id = ? ORDER BY name", [ctx.org_id])
        for r in roles:
            r["permissions"] = [p["permission_code"] for p in c.all("SELECT permission_code FROM role_permissions WHERE role_id = ? ORDER BY permission_code", [r["id"]])]
            r["user_count"] = c.scalar("SELECT COUNT(*) FROM user_roles WHERE role_id = ?", [r["id"]])
            r["is_system"] = bool(r["is_system"])
    return {"items": roles}


def _validate_perms(ctx: Ctx, perms) -> list[str]:
    perms = list(dict.fromkeys(perms or []))
    unknown = [p for p in perms if p not in PERMISSIONS]
    if unknown:
        raise bad_request(f"Unknown permissions: {', '.join(unknown)}")
    if not set(perms) <= ctx.permissions:
        raise forbidden("You cannot grant permissions you do not hold")
    return perms


@route("POST", "/api/admin/roles", perm="admin.roles.manage", tag="admin", summary="Create a custom role")
def create_role(ctx: Ctx):
    name = ctx.field("name", kind=str)
    code = (ctx.field("code", required=False, kind=str) or name).lower().replace(" ", "_")[:60]
    perms = _validate_perms(ctx, ctx.field("permissions", required=False, default=[]))
    with get_db().tx() as c:
        if c.one("SELECT id FROM roles WHERE organisation_id = ? AND code = ?", [ctx.org_id, code]):
            raise conflict("A role with this code already exists")
        rid = c.insert("roles", {"organisation_id": ctx.org_id, "code": code, "name": name,
                                 "description": ctx.field("description", required=False), "is_system": 0})
        for p in perms:
            c.execute("INSERT INTO role_permissions (role_id, permission_code) VALUES (?, ?)", [rid, p])
        audit(c, ctx, "role.created", "role", rid, code, new={"permissions": perms})
    return {"id": rid, "code": code, "name": name, "permissions": perms, "_created": True}


@route("PUT", "/api/admin/roles/{role_id:int}", perm="admin.roles.manage", tag="admin", summary="Update a role's name and permissions")
def update_role(ctx: Ctx):
    perms = _validate_perms(ctx, ctx.field("permissions", default=[]))
    with get_db().tx() as c:
        r = c.one("SELECT * FROM roles WHERE id = ? AND organisation_id = ?", [ctx.path["role_id"], ctx.org_id])
        if not r:
            raise not_found("Role")
        old = [p["permission_code"] for p in c.all("SELECT permission_code FROM role_permissions WHERE role_id = ?", [r["id"]])]
        removed = set(old) - set(perms)
        if not removed <= ctx.permissions:
            raise forbidden("You cannot remove permissions you do not hold")
        c.update("roles", r["id"], {"name": ctx.field("name", required=False, default=r["name"]),
                                    "description": ctx.field("description", required=False, default=r["description"])})
        c.execute("DELETE FROM role_permissions WHERE role_id = ?", [r["id"]])
        for p in perms:
            c.execute("INSERT INTO role_permissions (role_id, permission_code) VALUES (?, ?)", [r["id"], p])
        audit(c, ctx, "role.permissions_changed", "role", r["id"], r["code"], old={"permissions": old}, new={"permissions": perms})
    return {"id": r["id"], "permissions": perms}


@route("GET", "/api/admin/audit-logs", perm="admin.audit.view", tag="admin", summary="Search the audit trail")
def audit_logs(ctx: Ctx):
    sql = ("SELECT a.*, u.full_name AS user_name, u.email AS user_email FROM audit_logs a LEFT JOIN users u ON u.id = a.user_id "
           "WHERE (a.organisation_id = ? OR a.organisation_id IS NULL)")
    params: list = [ctx.org_id]
    for key, col in (("entity", "a.entity"), ("action", "a.action"), ("user_id", "a.user_id"), ("entity_id", "a.entity_id")):
        if ctx.q(key):
            sql += f" AND {col} = ?"
            params.append(ctx.q(key))
    if ctx.q("from"):
        sql += " AND a.created_at >= ?"
        params.append(ctx.q("from"))
    if ctx.q("to"):
        sql += " AND a.created_at <= ?"
        params.append(ctx.q("to") + "T23:59:59Z")
    with get_db().tx() as c:
        return paginate(c, ctx, sql, params, "a.id DESC", default_size=min(int(ctx.q("limit", 200)), 1000), max_size=1000)


@route("GET", "/api/admin/login-attempts", perm="admin.audit.view", tag="admin", summary="Login history including failed attempts")
def login_attempts(ctx: Ctx):
    with get_db().tx() as c:
        rows = c.all("SELECT la.* FROM login_attempts la LEFT JOIN users u ON u.id = la.user_id "
                     "WHERE u.organisation_id = ? OR la.user_id IS NULL ORDER BY la.id DESC LIMIT 300", [ctx.org_id])
    return {"items": rows}
