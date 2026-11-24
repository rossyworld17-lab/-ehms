"""Authentication: sign-in with lockout, MFA (TOTP), sessions, password change and reset. (FR-ADM-001/003)"""
from __future__ import annotations

import datetime as dt
import os
import hashlib
import secrets

from .. import security
from ..config import settings
from ..db import get_db, now_iso
from ..http import forbidden, ApiError, Ctx, audit, bad_request, route
from ..services import queue_notification


def _iso_in(minutes: int) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def user_profile(c, user_id: int) -> dict:
    u = c.one("SELECT id, organisation_id, email, full_name, phone, status, all_hotels, mfa_enabled, last_login_at, "
              "must_change_password, department_id, language FROM users WHERE id = ?", [user_id])
    roles = c.all("SELECT r.id, r.code, r.name FROM user_roles ur JOIN roles r ON r.id = ur.role_id WHERE ur.user_id = ? ORDER BY r.name", [user_id])
    perms = sorted({r["permission_code"] for r in c.all(
        "SELECT rp.permission_code FROM user_roles ur JOIN role_permissions rp ON rp.role_id = ur.role_id WHERE ur.user_id = ?", [user_id])})
    if u["all_hotels"]:
        hotels = c.all("SELECT id, code, name, currency, timezone FROM hotels WHERE organisation_id = ? AND active = 1 ORDER BY name", [u["organisation_id"]])
    else:
        hotels = c.all("SELECT h.id, h.code, h.name, h.currency, h.timezone FROM user_hotels uh JOIN hotels h ON h.id = uh.hotel_id "
                       "WHERE uh.user_id = ? AND h.active = 1 ORDER BY h.name", [user_id])
    from .predictive import logo_url
    for h in hotels:
        h["logo_url"] = logo_url(c, h["id"])
    u["roles"], u["permissions"], u["hotels"] = roles, perms, hotels
    u["mfa_enabled"] = bool(u["mfa_enabled"])
    from ..http import mfa_enrollment_required, mfa_policy
    u["mfa_policy"] = mfa_policy()
    u["mfa_enrollment_required"] = mfa_enrollment_required(u, set(perms))
    u["all_hotels"] = bool(u["all_hotels"])
    return u


@route("POST", "/api/auth/login", public=True, tag="auth", rate_limit=settings.login_rate_limit_per_minute,
       summary="Sign in with email and password")
def login(ctx: Ctx):
    email = str(ctx.field("email")).strip().lower()
    password = str(ctx.field("password"))
    db = get_db()
    error: ApiError | None = None
    # Failures are recorded in their own committed transaction, then the error is raised.
    with db.tx() as c:
        user = c.one("SELECT * FROM users WHERE lower(email) = ?", [email])
        now = dt.datetime.now(dt.timezone.utc)
        # failed sign-ins from one address across ALL accounts and server processes (password spraying)
        ip_limit = int(os.environ.get("EHMS_IP_MAX_FAILED_LOGINS", "20"))
        since = (now - dt.timedelta(minutes=settings.lockout_minutes)).isoformat().replace("+00:00", "Z")
        if ctx.ip and c.scalar("SELECT COUNT(*) FROM login_attempts WHERE ip = ? AND success = 0 AND created_at > ?", [ctx.ip, since]) >= ip_limit:
            c.insert("login_attempts", {"email": email, "user_id": user["id"] if user else None, "success": 0, "reason": "ip_blocked",
                                        "ip": ctx.ip, "user_agent": ctx.user_agent, "created_at": now_iso()})
            error = ApiError(429, "too_many_failures", f"Too many failed sign-ins from this network. Try again in {settings.lockout_minutes} minutes.")
            user = False

        def fail(reason: str, user_id=None):
            c.insert("login_attempts", {"email": email, "user_id": user_id, "success": 0, "reason": reason,
                                        "ip": ctx.ip, "user_agent": ctx.user_agent, "created_at": now_iso()})

        if user is False:
            pass
        elif not user:
            fail("unknown_user")
            security.hash_password(password)  # equalise timing
            error = ApiError(401, "invalid_credentials", "Incorrect email or password")
        elif user["locked_until"] and dt.datetime.fromisoformat(user["locked_until"].replace("Z", "+00:00")) > now:
            fail("locked", user["id"])
            error = ApiError(423, "account_locked", f"Account temporarily locked after repeated failed attempts. Try again in {settings.lockout_minutes} minutes or contact an administrator.")
        elif not security.verify_password(password, user["password_hash"]):
            failed = user["failed_logins"] + 1
            locked = _iso_in(settings.lockout_minutes) if failed >= settings.max_failed_logins else None
            c.execute("UPDATE users SET failed_logins = ?, locked_until = ? WHERE id = ?", [0 if locked else failed, locked, user["id"]])
            fail("bad_password", user["id"])
            if locked:
                audit(c, None, "auth.account_locked", "user", user["id"])
            error = ApiError(401, "invalid_credentials", "Incorrect email or password")
        elif user["status"] != "active":
            fail("inactive", user["id"])
            error = ApiError(403, "account_inactive", "This account is suspended or deactivated")
    if error:
        raise error
    with db.tx() as c:
        jti = security.new_jti()
        mfa_pending = bool(user["mfa_enabled"])
        c.insert("sessions", {"user_id": user["id"], "jti": jti, "ip": ctx.ip, "user_agent": ctx.user_agent,
                              "created_at": now_iso(), "last_seen_at": now_iso(),
                              "expires_at": _iso_in(5 if mfa_pending else 12 * 60), "mfa_pending": 1 if mfa_pending else 0})
        c.execute("UPDATE users SET failed_logins = 0, locked_until = NULL" + ("" if mfa_pending else ", last_login_at = ?") + " WHERE id = ?",
                  [user["id"]] if mfa_pending else [now_iso(), user["id"]])
        c.insert("login_attempts", {"email": email, "user_id": user["id"], "success": 1, "reason": "mfa_pending" if mfa_pending else "ok",
                                    "ip": ctx.ip, "user_agent": ctx.user_agent, "created_at": now_iso()})
        token = security.create_access_token(user["id"], jti, mfa_pending, minutes=5 if mfa_pending else 12 * 60)
        if mfa_pending:
            return {"mfa_required": True, "token": token}
        return {"mfa_required": False, "token": token, "user": user_profile(c, user["id"])}


@route("POST", "/api/auth/mfa/verify", tag="auth", allow_mfa_pending=True, rate_limit=10,
       summary="Complete sign-in with a 6-digit authenticator code")
def mfa_verify(ctx: Ctx):
    code = str(ctx.field("code"))
    db = get_db()
    with db.tx() as c:
        user = c.one("SELECT * FROM users WHERE id = ?", [ctx.user_id])
        if not user["mfa_enabled"] or not user["mfa_secret"]:
            raise bad_request("Multi-factor authentication is not enabled for this account")
        ok = security.verify_totp(user["mfa_secret"], code)
        if not ok:
            c.insert("login_attempts", {"email": user["email"], "user_id": user["id"], "success": 0, "reason": "bad_mfa_code",
                                        "ip": ctx.ip, "user_agent": ctx.user_agent, "created_at": now_iso()})
    if not ok:
        raise ApiError(401, "invalid_mfa_code", "The verification code is incorrect or has expired")
    with db.tx() as c:
        jti = security.new_jti()
        c.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", [now_iso(), ctx.session["id"]])
        c.insert("sessions", {"user_id": user["id"], "jti": jti, "ip": ctx.ip, "user_agent": ctx.user_agent, "created_at": now_iso(),
                              "last_seen_at": now_iso(), "expires_at": _iso_in(12 * 60), "mfa_pending": 0})
        c.execute("UPDATE users SET last_login_at = ? WHERE id = ?", [now_iso(), user["id"]])
        return {"token": security.create_access_token(user["id"], jti, False, minutes=12 * 60), "user": user_profile(c, user["id"])}


@route("POST", "/api/auth/logout", tag="auth", allow_mfa_pending=True, summary="Sign out (revoke current session)", mfa_setup_ok=True)
def logout(ctx: Ctx):
    with get_db().tx() as c:
        c.execute("UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL", [now_iso(), ctx.session["id"]])
    return {"ok": True}


@route("GET", "/api/auth/me", tag="auth", summary="Current user profile, roles, permissions and hotels", mfa_setup_ok=True)
def me(ctx: Ctx):
    with get_db().tx() as c:
        return user_profile(c, ctx.user_id)


@route("POST", "/api/auth/mfa/setup", tag="auth", summary="Start MFA enrolment (returns secret and otpauth URI)", mfa_setup_ok=True)
def mfa_setup(ctx: Ctx):
    secret = security.new_totp_secret()
    with get_db().tx() as c:
        if ctx.user["mfa_enabled"]:
            raise bad_request("MFA is already enabled")
        c.update("users", ctx.user_id, {"mfa_secret": secret})  # encrypted at rest by the database layer
    return {"secret": secret, "otpauth_uri": security.totp_uri(secret, ctx.user["email"])}


@route("POST", "/api/auth/mfa/enable", tag="auth", summary="Confirm MFA enrolment with a code from the authenticator app", mfa_setup_ok=True)
def mfa_enable(ctx: Ctx):
    code = str(ctx.field("code"))
    with get_db().tx() as c:
        u = c.one("SELECT mfa_secret FROM users WHERE id = ?", [ctx.user_id])
        if not u["mfa_secret"] or not security.verify_totp(u["mfa_secret"], code):
            raise bad_request("The verification code is incorrect")
        c.execute("UPDATE users SET mfa_enabled = 1 WHERE id = ?", [ctx.user_id])
        audit(c, ctx, "auth.mfa_enabled", "user", ctx.user_id)
    return {"mfa_enabled": True}


@route("POST", "/api/auth/mfa/disable", tag="auth", summary="Disable MFA (requires password and current code)")
def mfa_disable(ctx: Ctx):
    password, code = str(ctx.field("password")), str(ctx.field("code"))
    with get_db().tx() as c:
        u = c.one("SELECT * FROM users WHERE id = ?", [ctx.user_id])
        if not security.verify_password(password, u["password_hash"]) or not u["mfa_secret"] or not security.verify_totp(u["mfa_secret"], code):
            raise bad_request("Password or verification code is incorrect")
        from ..http import mfa_enrollment_required
        if mfa_enrollment_required({**u, "mfa_enabled": 0}, ctx.permissions):
            raise forbidden("Your role requires two-step verification, so it cannot be turned off")
        c.execute("UPDATE users SET mfa_enabled = 0, mfa_secret = NULL WHERE id = ?", [ctx.user_id])
        audit(c, ctx, "auth.mfa_disabled", "user", ctx.user_id)
    return {"mfa_enabled": False}


@route("POST", "/api/auth/password", tag="auth", summary="Change own password", mfa_setup_ok=True)
def change_password(ctx: Ctx):
    current, new = str(ctx.field("current_password")), str(ctx.field("new_password"))
    problems = security.password_problems(new, ctx.user.get("email"), ctx.user.get("full_name"))
    if problems:
        raise bad_request("Password " + "; ".join(problems), {"field": "new_password"})
    with get_db().tx() as c:
        u = c.one("SELECT password_hash FROM users WHERE id = ?", [ctx.user_id])
        if not security.verify_password(current, u["password_hash"]):
            raise bad_request("Current password is incorrect", {"field": "current_password"})
        c.execute("UPDATE users SET password_hash = ?, password_changed_at = ?, must_change_password = 0 WHERE id = ?",
                  [security.hash_password(new), now_iso(), ctx.user_id])
        c.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND id <> ? AND revoked_at IS NULL", [now_iso(), ctx.user_id, ctx.session["id"]])
        audit(c, ctx, "auth.password_changed", "user", ctx.user_id)
    return {"ok": True}


@route("POST", "/api/auth/password-reset/request", public=True, tag="auth", rate_limit=5,
       summary="Request a password-reset link by email")
def reset_request(ctx: Ctx):
    email = str(ctx.field("email")).strip().lower()
    with get_db().tx() as c:
        u = c.one("SELECT id, email FROM users WHERE lower(email) = ? AND status = 'active'", [email])
        if u:
            token = secrets.token_urlsafe(32)
            c.insert("password_resets", {"user_id": u["id"], "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                                         "expires_at": _iso_in(30), "created_at": now_iso()})
            queue_notification(c, None, "email", u["email"], "EHMS password reset",
                               f"Use this code to reset your EHMS password within 30 minutes:\n\n{token}\n\nIf you did not request this, ignore this message.",
                               "user", u["id"])
    # Same response whether or not the account exists (prevents account enumeration)
    return {"ok": True, "message": "If the email is registered, reset instructions have been sent."}


@route("POST", "/api/auth/password-reset/confirm", public=True, tag="auth", rate_limit=10, summary="Set a new password using a reset code")
def reset_confirm(ctx: Ctx):
    token, new = str(ctx.field("token")), str(ctx.field("new_password"))
    with get_db().tx() as c:
        r = c.one("SELECT * FROM password_resets WHERE token_hash = ?", [hashlib.sha256(token.encode()).hexdigest()])
        if not r or r["used_at"] or dt.datetime.fromisoformat(r["expires_at"].replace("Z", "+00:00")) < dt.datetime.now(dt.timezone.utc):
            raise bad_request("This reset code is invalid or has expired")
        u = c.one("SELECT email, full_name FROM users WHERE id = ?", [r["user_id"]])
        problems = security.password_problems(new, u["email"], u["full_name"])
        if problems:
            raise bad_request("Password " + "; ".join(problems), {"field": "new_password"})
        c.execute("UPDATE password_resets SET used_at = ? WHERE id = ?", [now_iso(), r["id"]])
        c.execute("UPDATE users SET password_hash = ?, password_changed_at = ?, failed_logins = 0, locked_until = NULL WHERE id = ?",
                  [security.hash_password(new), now_iso(), r["user_id"]])
        c.execute("UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL", [now_iso(), r["user_id"]])
        audit(c, None, "auth.password_reset", "user", r["user_id"])
    return {"ok": True}


@route("GET", "/api/auth/sessions", tag="auth", summary="List my active sessions", mfa_setup_ok=True)
def my_sessions(ctx: Ctx):
    with get_db().tx() as c:
        rows = c.all("SELECT id, ip, user_agent, created_at, last_seen_at, expires_at FROM sessions "
                     "WHERE user_id = ? AND revoked_at IS NULL AND mfa_pending = 0 ORDER BY last_seen_at DESC", [ctx.user_id])
    for r in rows:
        r["current"] = r["id"] == ctx.session["id"]
    return {"items": rows}
