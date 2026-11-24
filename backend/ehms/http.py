"""Small routing layer over Starlette: authentication, permission checks, JSON I/O,
error handling, rate limiting and an OpenAPI description generated from the route table."""
from __future__ import annotations

import datetime as dt
import json
import os
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Callable

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .config import settings
from .db import get_db, now_iso


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: Any = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details


def bad_request(msg: str, details: Any = None) -> ApiError:
    return ApiError(400, "bad_request", msg, details)


def not_found(what: str = "Record") -> ApiError:
    return ApiError(404, "not_found", f"{what} not found")


def conflict(msg: str, details: Any = None) -> ApiError:
    return ApiError(409, "conflict", msg, details)


def forbidden(msg: str = "You do not have permission to perform this action") -> ApiError:
    return ApiError(403, "forbidden", msg)


@dataclass
class Ctx:
    request: Request | None
    user: dict | None = None
    permissions: set[str] = field(default_factory=set)
    hotel_ids: set[int] | None = None   # None = all hotels in organisation
    session: dict | None = None
    body: Any = None
    path: dict = field(default_factory=dict)
    query: dict = field(default_factory=dict)
    raw: bytes = b""          # raw request body (webhook signature checks)

    @property
    def ip(self) -> str | None:
        if not self.request:
            return None
        fwd = self.request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[0].strip()
        return self.request.client.host if self.request.client else None

    @property
    def user_agent(self) -> str | None:
        return self.request.headers.get("user-agent", "")[:300] if self.request else None

    @property
    def user_id(self) -> int | None:
        return self.user["id"] if self.user else None

    @property
    def org_id(self) -> int | None:
        return self.user["organisation_id"] if self.user else None

    def can(self, perm: str) -> bool:
        return perm in self.permissions

    def require(self, perm: str) -> None:
        if perm not in self.permissions:
            raise forbidden(f"Missing permission: {perm}")

    def check_hotel(self, hotel_id: int | str | None) -> int:
        if hotel_id in (None, ""):
            raise bad_request("hotel_id is required")
        hid = int(hotel_id)
        if self.hotel_ids is not None and hid not in self.hotel_ids:
            raise forbidden("You are not assigned to this hotel")
        return hid

    # body helpers ---------------------------------------------------------
    def field(self, name: str, required: bool = True, default: Any = None, kind: type | None = None) -> Any:
        body = self.body if isinstance(self.body, dict) else {}
        if name not in body or body[name] in (None, ""):
            if required:
                raise bad_request(f"'{name}' is required", {"field": name})
            return default
        v = body[name]
        if kind is int:
            try:
                return int(v)
            except (TypeError, ValueError):
                raise bad_request(f"'{name}' must be a whole number", {"field": name})
        if kind is str:
            return str(v).strip()
        if kind is bool:
            return bool(v)
        return v

    def q(self, name: str, default: Any = None) -> Any:
        v = self.query.get(name)
        return default if v in (None, "") else v


ROUTES: list[dict] = []
_rate: dict[str, deque] = defaultdict(deque)
_rate_lock = threading.Lock()


def rate_limited(key: str, limit: int, window: float = 60.0) -> bool:
    now = time.time()
    with _rate_lock:
        q = _rate[key]
        while q and now - q[0] > window:
            q.popleft()
        if len(q) >= limit:
            return True
        q.append(now)
        return False


PRIVILEGED = frozenset({"admin.users.manage", "admin.roles.manage", "admin.settings.manage", "admin.sessions.manage", "admin.backups",
                        "payroll.approve", "payroll.pay", "payments.refund_approve", "accounting.post_manual", "accounting.close_period",
                        "finance.notes.approve", "finance.expenses.pay", "procurement.pay", "procurement.approve_high", "hr.accounts",
                        "website.manage", "finance.petty_cash.approve"})


def mfa_policy() -> str:
    """off | privileged | all — read at call time (EHMS_REQUIRE_MFA; production default: privileged)."""
    v = os.environ.get("EHMS_REQUIRE_MFA", "privileged" if settings.environment == "production" else "off").strip().lower()
    return v if v in ("off", "privileged", "all") else "privileged"


def mfa_enrollment_required(user: dict, perms: set[str]) -> bool:
    pol = mfa_policy()
    if pol == "off" or user.get("mfa_enabled"):
        return False
    return pol == "all" or bool(perms & PRIVILEGED)


def _authenticate(request: Request, allow_mfa_pending: bool, mfa_setup_ok: bool = False) -> tuple[dict, dict, set[str], set[int] | None]:
    from . import security
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise ApiError(401, "unauthenticated", "Sign in required")
    try:
        claims = security.decode_access_token(auth.split(" ", 1)[1].strip())
    except Exception:
        raise ApiError(401, "invalid_token", "Your session has expired. Please sign in again.")
    db = get_db()
    with db.tx() as c:
        sess = c.one("SELECT * FROM sessions WHERE jti = ?", [claims.get("jti")])
        if not sess or sess["revoked_at"]:
            raise ApiError(401, "session_revoked", "Your session has ended. Please sign in again.")
        now = dt.datetime.now(dt.timezone.utc)
        last_seen = dt.datetime.fromisoformat(sess["last_seen_at"].replace("Z", "+00:00"))
        expires = dt.datetime.fromisoformat(sess["expires_at"].replace("Z", "+00:00"))
        if now > expires or (now - last_seen).total_seconds() > settings.session_idle_minutes * 60:
            c.execute("UPDATE sessions SET revoked_at = ? WHERE id = ?", [now_iso(), sess["id"]])
            raise ApiError(401, "session_expired", "Your session expired due to inactivity. Please sign in again.")
        if sess["mfa_pending"] and not allow_mfa_pending:
            raise ApiError(401, "mfa_required", "Multi-factor verification required")
        if (now - last_seen).total_seconds() > 30:
            c.execute("UPDATE sessions SET last_seen_at = ? WHERE id = ?", [now_iso(), sess["id"]])
        user = c.one("SELECT * FROM users WHERE id = ?", [sess["user_id"]])
        if not user or user["status"] != "active":
            raise ApiError(401, "account_inactive", "This account is not active")
        perms = {r["permission_code"] for r in c.all(
            "SELECT DISTINCT rp.permission_code FROM user_roles ur JOIN role_permissions rp ON rp.role_id = ur.role_id WHERE ur.user_id = ?",
            [user["id"]])}
        hotel_ids = None if user["all_hotels"] else {r["hotel_id"] for r in c.all("SELECT hotel_id FROM user_hotels WHERE user_id = ?", [user["id"]])}
    if not mfa_setup_ok and mfa_enrollment_required(user, perms):
        raise ApiError(403, "mfa_enrollment_required", "Your role requires two-step verification. Set it up under My profile & security to continue.")
    return user, sess, perms, hotel_ids


def route(method: str, path: str, perm: str | None = None, public: bool = False, summary: str = "",
          tag: str = "general", allow_mfa_pending: bool = False, rate_limit: int | None = None, mfa_setup_ok: bool = False):
    def deco(fn: Callable[[Ctx], Any]):
        async def endpoint(request: Request) -> Response:
            try:
                if rate_limit and rate_limited(f"{path}:{request.client.host if request.client else '-'}", rate_limit):
                    raise ApiError(429, "rate_limited", "Too many attempts. Please wait a minute and try again.")
                body = None
                raw = b""
                if method in ("POST", "PUT", "PATCH", "DELETE"):
                    limit = int(float(os.environ.get("EHMS_MAX_BODY_MB", "16")) * 1024 * 1024)
                    if int(request.headers.get("content-length") or 0) > limit:
                        raise ApiError(413, "body_too_large", "The request is too large")
                    raw = await request.body()
                    if len(raw) > limit:
                        raise ApiError(413, "body_too_large", "The request is too large")
                    if raw:
                        try:
                            body = json.loads(raw)
                        except json.JSONDecodeError:
                            raise bad_request("Request body must be valid JSON")
                ctx = Ctx(request=request, body=body, path=dict(request.path_params), query=dict(request.query_params), raw=raw)
                if not public:
                    user, sess, perms, hotels = await run_in_threadpool(_authenticate, request, allow_mfa_pending, mfa_setup_ok or allow_mfa_pending)
                    ctx.user, ctx.session, ctx.permissions, ctx.hotel_ids = user, sess, perms, hotels
                    if perm:
                        ctx.require(perm)
                result = await run_in_threadpool(fn, ctx)
                if isinstance(result, Response):
                    return result
                status = 201 if method == "POST" and isinstance(result, dict) and result.get("_created") else 200
                if isinstance(result, dict):
                    result.pop("_created", None)
                return JSONResponse(result, status_code=status)
            except ApiError as e:
                return JSONResponse({"error": {"code": e.code, "message": e.message, "details": e.details}}, status_code=e.status)
            except Exception as e:  # pragma: no cover - unexpected
                from .db import IntegrityError
                if isinstance(e, IntegrityError):
                    return JSONResponse({"error": {"code": "integrity_error", "message": "The change conflicts with existing data", "details": str(e)[:300]}}, status_code=409)
                import logging
                logging.exception("Unhandled error")
                return JSONResponse({"error": {"code": "server_error", "message": "An unexpected error occurred"}}, status_code=500)

        ROUTES.append({"method": method, "path": path, "endpoint": endpoint, "perm": perm, "public": public,
                       "summary": summary or (fn.__doc__ or "").strip().split("\n")[0], "tag": tag, "name": fn.__name__, "fn": fn})
        return fn
    return deco


def starlette_routes() -> list[Route]:
    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    for r in ROUTES:
        grouped[r["path"]][r["method"]] = r["endpoint"]
    out = []
    for path, methods in grouped.items():
        def make(methods=methods):
            async def dispatch(request: Request) -> Response:
                ep = methods.get(request.method)
                if ep is None:
                    return JSONResponse({"error": {"code": "method_not_allowed", "message": "Method not allowed"}}, status_code=405)
                return await ep(request)
            return dispatch
        out.append(Route(path, make(), methods=list(methods)))
    return out


def openapi_spec() -> dict:
    paths: dict[str, dict] = defaultdict(dict)
    for r in ROUTES:
        op: dict[str, Any] = {"summary": r["summary"], "tags": [r["tag"]], "operationId": r["name"],
                              "responses": {"200": {"description": "Success"}, "400": {"description": "Validation error"},
                                            "401": {"description": "Not authenticated"}, "403": {"description": "Permission denied"}}}
        if not r["public"]:
            op["security"] = [{"bearerAuth": []}]
        if r["perm"]:
            op["description"] = f"Requires permission `{r['perm']}`."
        params = [p.strip("{}").split(":")[0] for p in r["path"].split("/") if p.startswith("{")]
        if params:
            op["parameters"] = [{"name": p, "in": "path", "required": True, "schema": {"type": "string"}} for p in params]
        if r["method"] in ("POST", "PUT", "PATCH"):
            op["requestBody"] = {"content": {"application/json": {"schema": {"type": "object"}}}}
        clean = "/".join(("{" + p.strip("{}").split(":")[0] + "}") if p.startswith("{") else p for p in r["path"].split("/"))
        paths[clean][r["method"].lower()] = op
    from . import __version__
    return {"openapi": "3.0.3", "info": {"title": "EHMS API", "version": __version__,
                                         "description": "Enterprise Hotel Management System REST API. Money values are integers in minor units (kobo for NGN)."},
            "components": {"securitySchemes": {"bearerAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}},
            "paths": dict(paths)}


def audit(c, ctx: Ctx | None, action: str, entity: str | None = None, entity_id: Any = None,
          reference: str | None = None, old: Any = None, new: Any = None, hotel_id: int | None = None) -> None:
    c.insert("audit_logs", {
        "organisation_id": ctx.org_id if ctx else None,
        "hotel_id": hotel_id,
        "user_id": ctx.user_id if ctx else None,
        "action": action, "entity": entity, "entity_id": None if entity_id is None else str(entity_id),
        "reference": reference,
        "old_value": None if old is None else json.dumps(old, default=str)[:20000],
        "new_value": None if new is None else json.dumps(new, default=str)[:20000],
        "ip": ctx.ip if ctx else None, "user_agent": ctx.user_agent if ctx else None,
        "created_at": now_iso(),
    })
