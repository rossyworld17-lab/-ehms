"""Full HR suite (release 1.1): HR dashboard with alerts, job history (promotions, transfers, pay changes,
confirmation), training and certifications, appraisals shared with and acknowledged by the employee, staff
requests (salary advance, loan, employment letter, change of personal details, shift swap, grievance) decided by
HR, leave cancellation, leave calendar, all-staff balances, leave adjustments, public holidays, and system logins
created by HR for staff. Employees use all of it themselves through My HR."""
from __future__ import annotations

import datetime as dt
import io
import json
import secrets

from starlette.responses import Response

from .. import security
from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, next_number, parse_date, queue_notification, to_minor
from .hr import DEPARTMENTS, _employee, _me, holidays, leave_balances

REQUEST_KINDS = ("salary_advance", "loan", "letter", "data_change", "shift_swap", "grievance", "other")
SELF_EDITABLE = ("phone", "email", "address", "next_of_kin", "emergency_contact", "bank_name", "bank_account_number", "qualifications")
HISTORY_KINDS = ("promotion", "transfer", "salary_change", "confirmation", "title_change", "demotion")
TRAINING_KINDS = ("training", "certification", "licence", "induction")


def _notify_perm(c, hotel_id: int, perm: str, subject: str, body: str, entity: str, eid) -> None:
    from ..worker import _users_with
    for uid in _users_with(c, hotel_id, perm):
        queue_notification(c, hotel_id, "in_app", str(uid), subject, body, entity, eid)


def _notify_employee(c, e: dict, subject: str, body: str, entity: str, eid) -> None:
    if e.get("user_id"):
        queue_notification(c, e["hotel_id"], "in_app", str(e["user_id"]), subject, body, entity, eid)


def _name(e: dict) -> str:
    return f"{e['first_name']} {e['last_name']}"


def employee_extras(c, ctx: Ctx, e: dict) -> dict:
    """Extra sections of the employee profile (job history, training, appraisals, requests, line manager, login)."""
    out: dict = {
        "history": c.all("SELECT h.*, u.full_name AS by_name FROM employee_history h JOIN users u ON u.id = h.created_by WHERE h.employee_id = ? "
                         "ORDER BY h.effective_date DESC, h.id DESC", [e["id"]]),
        "trainings": c.all("SELECT * FROM trainings WHERE employee_id = ? ORDER BY COALESCE(completed_on, created_at) DESC", [e["id"]]),
        "line_manager": c.one("SELECT id, first_name, last_name, position FROM employees WHERE id = ?", [e["line_manager_id"]]) if e.get("line_manager_id") else None,
        "direct_reports": c.all("SELECT id, first_name, last_name, position FROM employees WHERE line_manager_id = ? AND status = 'active' ORDER BY first_name", [e["id"]]),
        "login": None,
    }
    if e.get("user_id"):
        u = c.one("SELECT id, email, status, last_login_at FROM users WHERE id = ?", [e["user_id"]])
        if u:
            u["roles"] = [r["name"] for r in c.all("SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id WHERE ur.user_id = ?", [u["id"]])]
        out["login"] = u
    out["appraisals"] = c.all("SELECT a.*, u.full_name AS reviewer FROM appraisals a JOIN users u ON u.id = a.reviewer_id WHERE a.employee_id = ? ORDER BY a.id DESC",
                              [e["id"]]) if (ctx.can("hr.performance") or ctx.can("hr.records")) else None
    out["welfare"] = c.all("SELECT * FROM welfare_records WHERE employee_id = ? ORDER BY support_date DESC", [e["id"]]) if ctx.can("hr.records") else None
    sql = "SELECT * FROM staff_requests WHERE employee_id = ?" + ("" if ctx.can("hr.records") else " AND confidential = 0")
    out["requests"] = c.all(sql + " ORDER BY id DESC LIMIT 50", [e["id"]])
    for a in out["appraisals"] or []:
        a["criteria"] = json.loads(a["criteria"] or "[]")
    return out


# ------------------------------------------------------------------ dashboard
@route("GET", "/api/hotels/{hotel_id:int}/hr/dashboard", perm="hr.view", tag="hr",
       summary="HR dashboard: headcount, who is on leave, pending approvals, probation/contract/certification alerts, birthdays, staff without logins")
def dashboard(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        t = today.isoformat()
        emps = c.all("SELECT * FROM employees WHERE hotel_id = ?", [hid])
        active = [e for e in emps if e["status"] == "active"]
        m0 = today.replace(day=1).isoformat()
        soon = lambda d, n: d and t <= str(d)[:10] <= (today + dt.timedelta(days=n)).isoformat()  # noqa: E731
        by_dept: dict[str, int] = {}
        for e in active:
            by_dept[e["department"]] = by_dept.get(e["department"], 0) + 1
        on_leave = c.all("SELECT l.*, e.first_name, e.last_name, e.department, t.name AS leave_type FROM leave_requests l JOIN employees e ON e.id = l.employee_id "
                         "JOIN leave_types t ON t.id = l.leave_type_id WHERE e.hotel_id = ? AND l.status = 'approved' AND l.start_date <= ? AND l.end_date >= ? "
                         "ORDER BY l.end_date", [hid, t, t])

        def md(d):
            return str(d)[5:10] if d else None
        birthdays = []
        for e in active:
            if e["date_of_birth"]:
                for k in range(0, 15):
                    if md(e["date_of_birth"]) == (today + dt.timedelta(days=k)).isoformat()[5:10]:
                        birthdays.append({"id": e["id"], "name": _name(e), "department": e["department"], "date": (today + dt.timedelta(days=k)).isoformat()})
        anniversaries = [{"id": e["id"], "name": _name(e), "years": today.year - int(str(e["hire_date"])[:4]), "date": f"{today.year}-{str(e['hire_date'])[5:10]}"}
                         for e in active if str(e["hire_date"])[5:7] == t[5:7] and today.year > int(str(e["hire_date"])[:4])]
        certs = c.all("SELECT tr.*, e.first_name, e.last_name FROM trainings tr JOIN employees e ON e.id = tr.employee_id WHERE e.hotel_id = ? AND e.status = 'active' "
                      "AND tr.expires_on IS NOT NULL AND tr.expires_on <= ? ORDER BY tr.expires_on", [hid, (today + dt.timedelta(days=60)).isoformat()])
        unlinked_users = c.all("SELECT u.id, u.full_name, u.email FROM users u LEFT JOIN user_hotels uh ON uh.user_id = u.id AND uh.hotel_id = ? "
                               "WHERE u.organisation_id = ? AND u.status = 'active' AND (u.all_hotels = 0 AND uh.hotel_id IS NOT NULL) "
                               "AND NOT EXISTS (SELECT 1 FROM employees x WHERE x.user_id = u.id) ORDER BY u.full_name", [hid, ctx.org_id])
        pending_requests = c.all("SELECT kind, COUNT(*) AS n FROM staff_requests r JOIN employees e ON e.id = r.employee_id WHERE e.hotel_id = ? AND r.status = 'submitted' "
                                 + ("" if ctx.can("hr.records") else "AND r.confidential = 0 ") + "GROUP BY kind", [hid])
        out = {
            "date": t,
            "headcount": len(active), "by_department": sorted([{"department": k, "count": v} for k, v in by_dept.items()], key=lambda x: -x["count"]),
            "joiners_this_month": [{"id": e["id"], "name": _name(e), "position": e["position"], "hire_date": e["hire_date"]} for e in emps if str(e["hire_date"])[:10] >= m0],
            "leavers_this_month": [{"id": e["id"], "name": _name(e), "status": e["status"], "exit_date": e["exit_date"]} for e in emps if e["exit_date"] and str(e["exit_date"])[:10] >= m0],
            "on_leave_today": [{"name": f"{l['first_name']} {l['last_name']}", "department": l["department"], "type": l["leave_type"], "until": l["end_date"]} for l in on_leave],
            "pending": {
                "leave": c.scalar("SELECT COUNT(*) FROM leave_requests l JOIN employees e ON e.id = l.employee_id WHERE e.hotel_id = ? AND l.status = 'pending'", [hid]),
                "requests": sum(r["n"] for r in pending_requests), "requests_by_kind": {r["kind"]: r["n"] for r in pending_requests},
                "appraisals_unacknowledged": c.scalar("SELECT COUNT(*) FROM appraisals a JOIN employees e ON e.id = a.employee_id WHERE e.hotel_id = ? AND a.status = 'shared'", [hid]),
            },
            "alerts": {
                "probation_ending": [{"id": e["id"], "name": _name(e), "date": e["probation_end_date"]} for e in active if soon(e["probation_end_date"], 30)],
                "contracts_ending": [{"id": e["id"], "name": _name(e), "date": e["contract_end_date"]} for e in active if soon(e["contract_end_date"], 60)],
                "certifications_expiring": [{"id": x["employee_id"], "name": f"{x['first_name']} {x['last_name']}", "title": x["title"], "date": x["expires_on"],
                                             "expired": str(x["expires_on"])[:10] < t} for x in certs],
            },
            "birthdays": sorted(birthdays, key=lambda x: x["date"]), "anniversaries": anniversaries,
            "staff_without_login": [{"id": e["id"], "name": _name(e), "department": e["department"], "email": e["email"]} for e in active if not e["user_id"]],
            "logins_without_employee": unlinked_users,
            "holidays": c.all("SELECT * FROM public_holidays WHERE hotel_id = ? AND holiday_date >= ? ORDER BY holiday_date LIMIT 5", [hid, t]),
        }
    return out


# ------------------------------------------------------------------ job history
@route("POST", "/api/employees/{employee_id:int}/history", perm="hr.manage", tag="hr",
       summary="Record a promotion, transfer, pay change, title change, demotion or confirmation (kind, effective_date, position, department, basic_salary, line_manager_id, note); the change is applied to the record")
def add_history(ctx: Ctx):
    kind = ctx.field("kind", kind=str)
    if kind not in HISTORY_KINDS:
        raise bad_request(f"kind must be one of {', '.join(HISTORY_KINDS)}")
    eff = parse_date(ctx.field("effective_date", kind=str), "effective_date").isoformat()
    note = ctx.field("note", required=False, kind=str)
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        if e["status"] != "active":
            raise conflict("Only active employees can be promoted, transferred or confirmed")
        change: dict = {}
        frm, to = None, None
        if kind in ("promotion", "title_change", "demotion"):
            pos = ctx.field("position", kind=str)
            change["position"], frm, to = pos, e["position"], pos
        if kind == "transfer":
            dept = ctx.field("department", kind=str)
            if dept not in DEPARTMENTS:
                raise bad_request("Unknown department")
            change["department"], frm, to = dept, e["department"], dept
            if ctx.field("position", required=False, kind=str):
                change["position"] = ctx.field("position", kind=str)
                to += f" ({change['position']})"
        if kind == "confirmation":
            change["probation_end_date"] = eff
            frm, to = "On probation", "Confirmed"
        if ctx.field("basic_salary", required=False) not in (None, ""):
            new = to_minor(ctx.field("basic_salary"), "basic_salary")
            if new <= 0:
                raise bad_request("basic_salary must be positive")
            if kind == "salary_change":
                frm, to = f"{e['basic_salary'] / 100:,.2f}", f"{new / 100:,.2f}"
            else:
                to = f"{to} · basic {new / 100:,.2f}"
            change["basic_salary"] = new
        elif kind == "salary_change":
            raise bad_request("basic_salary is required for a pay change")
        if ctx.field("line_manager_id", required=False):
            lm = int(ctx.field("line_manager_id"))
            if lm == e["id"] or not c.one("SELECT id FROM employees WHERE id = ? AND hotel_id = ?", [lm, e["hotel_id"]]):
                raise bad_request("Invalid line manager")
            change["line_manager_id"] = lm
        hid_ = c.insert("employee_history", {"employee_id": e["id"], "kind": kind, "effective_date": eff, "from_value": frm, "to_value": to,
                                              "note": note, "created_by": ctx.user_id, "created_at": now_iso()})
        if change:
            c.update("employees", e["id"], change)
        _notify_employee(c, e, f"{kind.replace('_', ' ').title()} recorded", f"HR recorded your {kind.replace('_', ' ')} effective {eff}.", "employee", e["id"])
        audit(c, ctx, f"hr.{kind}", "employee", e["id"], e["employee_no"], old={k: e.get(k) for k in change}, new={**change, "effective": eff}, hotel_id=e["hotel_id"])
    return {"id": hid_, "_created": True}


# ------------------------------------------------------------------ training & certifications
@route("POST", "/api/employees/{employee_id:int}/trainings", perm="hr.manage", tag="hr",
       summary="Record training, a certification or licence (kind, title, provider, completed_on, expires_on, notes)")
def add_training(ctx: Ctx):
    kind = ctx.field("kind", required=False, kind=str) or "training"
    if kind not in TRAINING_KINDS:
        raise bad_request(f"kind must be one of {', '.join(TRAINING_KINDS)}")
    done = ctx.field("completed_on", required=False)
    exp = ctx.field("expires_on", required=False)
    done_d = parse_date(done, "completed_on").isoformat() if done else None
    exp_d = parse_date(exp, "expires_on").isoformat() if exp else None
    if done_d and exp_d and exp_d < done_d:
        raise bad_request("A certificate cannot expire before it was obtained")
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        tid = c.insert("trainings", {"employee_id": e["id"], "kind": kind, "title": ctx.field("title", kind=str)[:200], "provider": ctx.field("provider", required=False, kind=str),
                                     "completed_on": done_d, "expires_on": exp_d, "notes": ctx.field("notes", required=False, kind=str), "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "hr.training_added", "training", tid, e["employee_no"], hotel_id=e["hotel_id"])
    return {"id": tid, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/hr/trainings", perm="hr.view", tag="hr", summary="Training and certification register (?expiring=days)")
def training_register(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        sql = ("SELECT tr.*, e.first_name || ' ' || e.last_name AS employee, e.department FROM trainings tr JOIN employees e ON e.id = tr.employee_id "
               "WHERE e.hotel_id = ? AND e.status = 'active'")
        params: list = [hid]
        if ctx.q("expiring"):
            sql += " AND tr.expires_on IS NOT NULL AND tr.expires_on <= ?"
            params.append((business_date(get_hotel(c, hid)) + dt.timedelta(days=int(ctx.q("expiring")))).isoformat())
        return {"items": c.all(sql + " ORDER BY COALESCE(tr.expires_on, '9999-12-31'), tr.id DESC LIMIT 500", params)}


# ------------------------------------------------------------------ appraisals
def _criteria(raw) -> tuple[str, int]:
    if not isinstance(raw, list) or not raw:
        raise bad_request("Add at least one criterion with a rating")
    clean = []
    for x in raw:
        name = str((x or {}).get("name") or "").strip()[:80]
        r = int((x or {}).get("rating") or 0)
        if not name or not 1 <= r <= 5:
            raise bad_request("Each criterion needs a name and a rating from 1 to 5")
        clean.append({"name": name, "rating": r, "comment": str((x or {}).get("comment") or "")[:300]})
    return json.dumps(clean), round(sum(x["rating"] for x in clean) / len(clean))


@route("POST", "/api/employees/{employee_id:int}/appraisals", perm="hr.performance", tag="hr",
       summary="Start an appraisal (period, criteria[{name, rating 1-5, comment}], strengths, improvements, goals) as a draft")
def create_appraisal(ctx: Ctx):
    crit, overall = _criteria(ctx.field("criteria"))
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        if e["user_id"] == ctx.user_id:
            raise forbidden("You cannot appraise yourself")
        aid = c.insert("appraisals", {"employee_id": e["id"], "period": ctx.field("period", kind=str)[:30], "reviewer_id": ctx.user_id, "status": "draft", "criteria": crit,
                                      "overall_rating": overall, "strengths": ctx.field("strengths", required=False, kind=str),
                                      "improvements": ctx.field("improvements", required=False, kind=str), "goals": ctx.field("goals", required=False, kind=str),
                                      "created_at": now_iso()})
        audit(c, ctx, "hr.appraisal_created", "appraisal", aid, e["employee_no"], hotel_id=e["hotel_id"])
    return {"id": aid, "overall_rating": overall, "_created": True}


def _appraisal(c, ctx: Ctx, aid) -> tuple[dict, dict]:
    a = c.one("SELECT * FROM appraisals WHERE id = ?", [int(aid)])
    if not a:
        raise not_found("Appraisal")
    return a, _employee(c, ctx, a["employee_id"])


@route("PATCH", "/api/appraisals/{appraisal_id:int}", perm="hr.performance", tag="hr", summary="Edit a draft appraisal")
def update_appraisal(ctx: Ctx):
    b = ctx.body or {}
    with get_db().tx() as c:
        a, e = _appraisal(c, ctx, ctx.path["appraisal_id"])
        if a["status"] != "draft":
            raise conflict("A shared appraisal can no longer be edited")
        ch = {k: b[k] for k in ("period", "strengths", "improvements", "goals") if k in b}
        if "criteria" in b:
            ch["criteria"], ch["overall_rating"] = _criteria(b["criteria"])
        if not ch:
            raise bad_request("Nothing to change")
        c.update("appraisals", a["id"], ch)
    return {"ok": True}


@route("POST", "/api/appraisals/{appraisal_id:int}/share", perm="hr.performance", tag="hr", summary="Share a draft appraisal with the employee for acknowledgement")
def share_appraisal(ctx: Ctx):
    with get_db().tx() as c:
        a, e = _appraisal(c, ctx, ctx.path["appraisal_id"])
        if a["status"] != "draft":
            raise conflict("Already shared")
        c.update("appraisals", a["id"], {"status": "shared", "shared_at": now_iso()})
        _notify_employee(c, e, "Your appraisal is ready", f"Your {a['period']} appraisal is ready to read and acknowledge in My HR.", "appraisal", a["id"])
        audit(c, ctx, "hr.appraisal_shared", "appraisal", a["id"], e["employee_no"], hotel_id=e["hotel_id"])
    return {"status": "shared"}


@route("GET", "/api/hotels/{hotel_id:int}/hr/appraisals", perm="hr.performance", tag="hr", summary="Appraisals (?status, ?period)")
def list_appraisals(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        sql = ("SELECT a.*, e.first_name || ' ' || e.last_name AS employee, e.department, e.position, u.full_name AS reviewer FROM appraisals a "
               "JOIN employees e ON e.id = a.employee_id JOIN users u ON u.id = a.reviewer_id WHERE e.hotel_id = ?")
        params: list = [hid]
        for k in ("status", "period"):
            if ctx.q(k):
                sql += f" AND a.{k} = ?"
                params.append(ctx.q(k))
        rows = c.all(sql + " ORDER BY a.id DESC LIMIT 300", params)
        for r in rows:
            r["criteria"] = json.loads(r["criteria"] or "[]")
        active = c.scalar("SELECT COUNT(*) FROM employees WHERE hotel_id = ? AND status = 'active'", [hid])
    return {"items": rows, "active_employees": active}


@route("POST", "/api/me/appraisals/{appraisal_id:int}/acknowledge", tag="hr", summary="Acknowledge my appraisal with an optional comment")
def acknowledge(ctx: Ctx):
    with get_db().tx() as c:
        me = _me(c, ctx)
        a = c.one("SELECT * FROM appraisals WHERE id = ? AND employee_id = ?", [ctx.path["appraisal_id"], me["id"]])
        if not a or a["status"] == "draft":
            raise not_found("Appraisal")
        if a["status"] == "acknowledged":
            raise conflict("Already acknowledged")
        c.update("appraisals", a["id"], {"status": "acknowledged", "acknowledged_at": now_iso(), "employee_comment": ctx.field("comment", required=False, kind=str)})
        queue_notification(c, me["hotel_id"], "in_app", str(a["reviewer_id"]), "Appraisal acknowledged", f"{_name(me)} acknowledged the {a['period']} appraisal.", "appraisal", a["id"])
    return {"status": "acknowledged"}


# ------------------------------------------------------------------ staff requests
def _request_view(r: dict) -> dict:
    out = dict(r)
    out["data"] = json.loads(r["data"]) if r.get("data") else None
    return out


@route("POST", "/api/me/requests", tag="hr",
       summary="Make an HR request: kind salary_advance|loan|letter|data_change|shift_swap|grievance|other, subject, details, amount, months, data")
def create_request(ctx: Ctx):
    kind = ctx.field("kind", kind=str)
    if kind not in REQUEST_KINDS:
        raise bad_request(f"kind must be one of {', '.join(REQUEST_KINDS)}")
    subject = ctx.field("subject", required=False, kind=str) or kind.replace("_", " ").capitalize()
    details = ctx.field("details", required=kind in ("grievance", "other"), kind=str)
    amount = months = None
    data = None
    if kind in ("salary_advance", "loan"):
        amount = to_minor(ctx.field("amount"), "amount")
        if amount <= 0:
            raise bad_request("amount must be positive")
        months = int(ctx.field("months", required=False) or (1 if kind == "salary_advance" else 6))
        if not 1 <= months <= 24:
            raise bad_request("Repayment must be over 1 to 24 months")
    if kind == "data_change":
        raw = ctx.field("data")
        if not isinstance(raw, dict) or not raw:
            raise bad_request("Say which details to change")
        bad = [k for k in raw if k not in SELF_EDITABLE]
        if bad:
            raise bad_request(f"These details can only be changed by HR: {', '.join(bad)}")
        data = {k: str(v).strip()[:200] for k, v in raw.items()}
    with get_db().tx() as c:
        e = _me(c, ctx)
        if kind == "shift_swap":
            d = parse_date(ctx.field("date", kind=str), "date").isoformat()
            other = c.one("SELECT * FROM employees WHERE id = ? AND hotel_id = ? AND status = 'active'", [ctx.field("with_employee_id", kind=int), e["hotel_id"]])
            if not other or other["id"] == e["id"]:
                raise bad_request("Choose the colleague to swap with")
            data = {"date": d, "with_employee_id": other["id"], "with_name": _name(other)}
        if kind in ("salary_advance", "loan") and e["basic_salary"] and amount > (e["basic_salary"] * (1 if kind == "salary_advance" else 6)):
            raise conflict("The amount is above the limit (one month's basic pay for an advance, six months' for a loan)")
        number = next_number(c, e["hotel_id"], "staff_request", "REQ", 5)
        rid = c.insert("staff_requests", {"employee_id": e["id"], "number": number, "kind": kind, "subject": subject[:200], "details": details, "amount": amount,
                                          "months": months, "data": json.dumps(data) if data else None, "confidential": 1 if kind == "grievance" else 0,
                                          "status": "submitted", "created_by": ctx.user_id, "created_at": now_iso()})
        _notify_perm(c, e["hotel_id"], "hr.requests.approve", f"New HR request {number}",
                     f"{_name(e)}: {'grievance (confidential)' if kind == 'grievance' else subject}", "staff_request", rid)
        audit(c, ctx, "hr.request_submitted", "staff_request", rid, number, new={"kind": kind}, hotel_id=e["hotel_id"])
    return {"id": rid, "number": number, "_created": True}


@route("GET", "/api/me/requests", tag="hr", summary="My HR requests")
def my_requests(ctx: Ctx):
    with get_db().tx() as c:
        e = c.one("SELECT * FROM employees WHERE user_id = ?", [ctx.user_id])
        if not e:
            return {"items": [], "linked": False}
        return {"items": [_request_view(r) for r in c.all("SELECT r.*, u.full_name AS decided_by_name FROM staff_requests r LEFT JOIN users u ON u.id = r.decided_by "
                                                          "WHERE r.employee_id = ? ORDER BY r.id DESC", [e["id"]])]}


@route("POST", "/api/me/requests/{request_id:int}/cancel", tag="hr", summary="Withdraw one of my requests that has not been decided")
def cancel_request(ctx: Ctx):
    with get_db().tx() as c:
        e = _me(c, ctx)
        r = c.one("SELECT * FROM staff_requests WHERE id = ? AND employee_id = ?", [ctx.path["request_id"], e["id"]])
        if not r:
            raise not_found("Request")
        if r["status"] != "submitted":
            raise conflict("Only requests that have not been decided can be withdrawn")
        c.update("staff_requests", r["id"], {"status": "cancelled"})
    return {"status": "cancelled"}


@route("GET", "/api/hotels/{hotel_id:int}/hr/requests", perm="hr.view", tag="hr", summary="Staff requests (?status, ?kind); grievances need hr.records")
def list_requests(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        sql = ("SELECT r.*, e.first_name || ' ' || e.last_name AS employee, e.department, e.position, e.user_id, u.full_name AS decided_by_name FROM staff_requests r "
               "JOIN employees e ON e.id = r.employee_id LEFT JOIN users u ON u.id = r.decided_by WHERE e.hotel_id = ?")
        params: list = [hid]
        if not ctx.can("hr.records"):
            sql += " AND r.confidential = 0"
        for k in ("status", "kind"):
            if ctx.q(k):
                sql += f" AND r.{k} = ?"
                params.append(ctx.q(k))
        return {"items": [_request_view(r) for r in c.all(sql + " ORDER BY CASE r.status WHEN 'submitted' THEN 0 ELSE 1 END, r.id DESC LIMIT 300", params)]}


@route("POST", "/api/hr/requests/{request_id:int}/decide", perm="hr.requests.approve", tag="hr",
       summary="Approve or reject a staff request ({decision, note}); approval applies detail changes and shift swaps, issues letters, and sends advances/loans to payroll")
def decide_request(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    note = ctx.field("note", required=decision == "reject", kind=str)
    with get_db().tx() as c:
        r = c.lock("staff_requests", int(ctx.path["request_id"]))
        if not r:
            raise not_found("Request")
        e = _employee(c, ctx, r["employee_id"])
        if r["confidential"] and not ctx.can("hr.records"):
            raise forbidden("Grievances are handled by staff with access to confidential HR records")
        if r["status"] != "submitted":
            raise conflict(f"This request is already {r['status']}")
        if e["user_id"] == ctx.user_id or r["created_by"] == ctx.user_id:
            raise forbidden("You cannot decide your own request")
        status = "rejected"
        if decision == "approve":
            data = json.loads(r["data"]) if r["data"] else {}
            status = "completed"
            if r["kind"] == "data_change":
                c.update("employees", e["id"], {k: (v or None) for k, v in data.items() if k in ("phone", "email", "address", "next_of_kin", "emergency_contact",
                                                                                                  "bank_name", "bank_account_number", "qualifications")})
            elif r["kind"] == "shift_swap":
                mine = c.one("SELECT * FROM shift_assignments WHERE employee_id = ? AND work_date = ?", [e["id"], data["date"]])
                theirs = c.one("SELECT * FROM shift_assignments WHERE employee_id = ? AND work_date = ?", [data["with_employee_id"], data["date"]])
                if mine and theirs:
                    c.update("shift_assignments", mine["id"], {"shift_id": theirs["shift_id"]})
                    c.update("shift_assignments", theirs["id"], {"shift_id": mine["shift_id"]})
                elif mine:
                    c.update("shift_assignments", mine["id"], {"employee_id": data["with_employee_id"]})
                elif theirs:
                    c.update("shift_assignments", theirs["id"], {"employee_id": e["id"]})
            elif r["kind"] in ("salary_advance", "loan"):
                status = "approved"   # payroll disburses it and marks it completed
                _notify_perm(c, e["hotel_id"], "payroll.pay", f"Approved {r['kind'].replace('_', ' ')} {r['number']}",
                             f"Pay {r['amount'] / 100:,.2f} to {_name(e)}, recovered over {r['months']} month(s): Payroll → employee → Staff loan.", "staff_request", r["id"])
        c.update("staff_requests", r["id"], {"status": status, "decided_by": ctx.user_id, "decision_note": note, "decided_at": now_iso()})
        _notify_employee(c, e, f"Request {r['number']} {'approved' if decision == 'approve' else 'rejected'}",
                         f"Your request “{r['subject']}” was {'approved' if decision == 'approve' else 'rejected'}" + (f": {note}" if note else "."), "staff_request", r["id"])
        audit(c, ctx, f"hr.request_{decision}d", "staff_request", r["id"], r["number"], new={"status": status, "note": note}, hotel_id=e["hotel_id"])
    return {"status": status}


@route("POST", "/api/hr/requests/{request_id:int}/complete", perm="payroll.pay", tag="hr", summary="Mark an approved advance or loan as paid out")
def complete_request(ctx: Ctx):
    with get_db().tx() as c:
        r = c.one("SELECT * FROM staff_requests WHERE id = ?", [ctx.path["request_id"]])
        if not r:
            raise not_found("Request")
        e = _employee(c, ctx, r["employee_id"])
        if r["status"] != "approved":
            raise conflict("Only approved requests can be completed")
        c.update("staff_requests", r["id"], {"status": "completed"})
        audit(c, ctx, "hr.request_completed", "staff_request", r["id"], r["number"], hotel_id=e["hotel_id"])
    return {"status": "completed"}


@route("GET", "/api/hr/requests/{request_id:int}/letter.pdf", tag="hr", summary="Employment confirmation letter for an approved letter request (the employee, or HR)")
def letter_pdf(ctx: Ctx):
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    with get_db().tx() as c:
        r = c.one("SELECT * FROM staff_requests WHERE id = ?", [ctx.path["request_id"]])
        if not r or r["kind"] != "letter":
            raise not_found("Letter")
        e = c.one("SELECT * FROM employees WHERE id = ?", [r["employee_id"]])
        if e["user_id"] != ctx.user_id:
            ctx.require("hr.view")
            ctx.check_hotel(e["hotel_id"])
        if r["status"] != "completed":
            raise conflict("The letter is issued once HR approves the request")
        hotel = get_hotel(c, e["hotel_id"])
        signer = c.one("SELECT full_name FROM users WHERE id = ?", [r["decided_by"]])
    buf = io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFont("Helvetica-Bold", 16)
    cv.drawString(60, 790, hotel["name"])
    cv.setFont("Helvetica", 9)
    cv.drawString(60, 776, " · ".join(x for x in [hotel.get("address"), hotel.get("phone"), hotel.get("email")] if x))
    cv.setFont("Helvetica", 11)
    cv.drawString(60, 740, f"Ref: {r['number']}")
    cv.drawString(60, 724, f"Date: {str(r['decided_at'])[:10]}")
    cv.setFont("Helvetica-Bold", 12)
    cv.drawString(60, 690, "TO WHOM IT MAY CONCERN — CONFIRMATION OF EMPLOYMENT")
    cv.setFont("Helvetica", 11)
    status = "is employed" if e["status"] == "active" else f"was employed until {str(e['exit_date'] or '')[:10]}"
    lines = [f"This is to confirm that {e['first_name']} {e['last_name']} (staff number {e['employee_no']}) {status} by",
             f"{hotel['name']} as {e['position']} in the {e['department'].replace('_', ' ')} department,",
             f"on a {e['employment_type'].replace('_', ' ')} basis, since {str(e['hire_date'])[:10]}.", "",
             f"This letter is issued at the employee's request for: {r['subject']}.", "",
             "For further confirmation, please contact the Human Resources department.", "", "Yours faithfully,", "", "",
             f"{signer['full_name'] if signer else 'Human Resources'}", "Human Resources"]
    for i, ln in enumerate(lines):
        cv.drawString(60, 660 - i * 18, ln)
    cv.showPage()
    cv.save()
    return Response(buf.getvalue(), media_type="application/pdf", headers={"Content-Disposition": f'inline; filename="{r["number"]}.pdf"'})


# ------------------------------------------------------------------ leave: cancel, calendar, balances, adjustments, holidays
def _cancel_leave(c, ctx: Ctx, l: dict, e: dict, reason: str, today: dt.date) -> None:
    if l["status"] == "approved":
        c.execute("DELETE FROM attendance WHERE employee_id = ? AND work_date >= ? AND work_date <= ? AND status = 'leave' AND note = ?",
                  [e["id"], max(today, dt.date.fromisoformat(l["start_date"])).isoformat(), l["end_date"], f"Leave #{l['id']}"])
    c.update("leave_requests", l["id"], {"status": "cancelled", "cancelled_at": now_iso(), "cancel_reason": reason[:300] if reason else None})
    audit(c, ctx, "hr.leave_cancelled", "leave_request", l["id"], e["employee_no"], new={"reason": reason}, hotel_id=e["hotel_id"])


@route("POST", "/api/me/leave/{leave_id:int}/cancel", tag="hr", summary="Cancel my pending leave, or approved leave that has not started")
def my_cancel_leave(ctx: Ctx):
    with get_db().tx() as c:
        e = _me(c, ctx)
        l = c.one("SELECT * FROM leave_requests WHERE id = ? AND employee_id = ?", [ctx.path["leave_id"], e["id"]])
        if not l:
            raise not_found("Leave request")
        today = business_date(get_hotel(c, e["hotel_id"]))
        if l["status"] not in ("pending", "approved"):
            raise conflict(f"This request is {l['status']}")
        if l["status"] == "approved" and l["start_date"] <= today.isoformat():
            raise conflict("This leave has already started; ask HR to end it early")
        _cancel_leave(c, ctx, l, e, ctx.field("reason", required=False, kind=str) or "Cancelled by employee", today)
        if l["status"] == "approved":
            _notify_perm(c, e["hotel_id"], "hr.leave.approve", "Approved leave cancelled", f"{_name(e)} cancelled leave {l['start_date']} – {l['end_date']}.", "leave_request", l["id"])
    return {"status": "cancelled"}


@route("POST", "/api/leave/{leave_id:int}/cancel", perm="hr.leave.approve", tag="hr", summary="Cancel or end an approved leave early ({reason}); future leave days are returned")
def hr_cancel_leave(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        l = c.one("SELECT * FROM leave_requests WHERE id = ?", [ctx.path["leave_id"]])
        if not l:
            raise not_found("Leave request")
        e = _employee(c, ctx, l["employee_id"])
        if l["status"] not in ("pending", "approved"):
            raise conflict(f"This request is {l['status']}")
        today = business_date(get_hotel(c, e["hotel_id"]))
        if l["status"] == "approved" and l["start_date"] < today.isoformat() <= l["end_date"]:
            # end early: keep the days already taken as a new shorter approved request
            from .hr import working_days
            taken_end = today - dt.timedelta(days=1)
            days = working_days(dt.date.fromisoformat(l["start_date"]), taken_end, holidays(c, e["hotel_id"]))
            c.execute("DELETE FROM attendance WHERE employee_id = ? AND work_date >= ? AND work_date <= ? AND status = 'leave' AND note = ?",
                      [e["id"], today.isoformat(), l["end_date"], f"Leave #{l['id']}"])
            c.update("leave_requests", l["id"], {"end_date": taken_end.isoformat(), "days": max(days, 1), "cancel_reason": f"Ended early: {reason}"[:300]})
            audit(c, ctx, "hr.leave_ended_early", "leave_request", l["id"], e["employee_no"], new={"end": taken_end.isoformat(), "reason": reason}, hotel_id=e["hotel_id"])
            _notify_employee(c, e, "Leave ended early", f"HR ended your leave on {taken_end}: {reason}", "leave_request", l["id"])
            return {"status": "approved", "end_date": taken_end.isoformat()}
        _cancel_leave(c, ctx, l, e, reason, today)
        _notify_employee(c, e, "Leave cancelled", f"HR cancelled your leave {l['start_date']} – {l['end_date']}: {reason}", "leave_request", l["id"])
    return {"status": "cancelled"}


@route("GET", "/api/hotels/{hotel_id:int}/hr/leave-calendar", perm="hr.view", tag="hr", summary="Who is on (or has asked for) leave between two dates (?from&to, ?department)")
def leave_calendar(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        f = parse_date(ctx.q("from", today.replace(day=1).isoformat()), "from")
        t = parse_date(ctx.q("to", (f + dt.timedelta(days=41)).isoformat()), "to")
        if (t - f).days > 120 or t < f:
            raise bad_request("Choose a range of up to 120 days")
        sql = ("SELECT l.id, l.start_date, l.end_date, l.days, l.status, t.name AS leave_type, t.code, e.id AS employee_id, e.first_name || ' ' || e.last_name AS employee, "
               "e.department FROM leave_requests l JOIN employees e ON e.id = l.employee_id JOIN leave_types t ON t.id = l.leave_type_id WHERE e.hotel_id = ? "
               "AND l.status IN ('approved','pending') AND l.start_date <= ? AND l.end_date >= ?")
        params: list = [hid, t.isoformat(), f.isoformat()]
        if ctx.q("department"):
            sql += " AND e.department = ?"
            params.append(ctx.q("department"))
        rows = c.all(sql + " ORDER BY e.department, employee, l.start_date", params)
        hol = c.all("SELECT * FROM public_holidays WHERE hotel_id = ? AND holiday_date >= ? AND holiday_date <= ? ORDER BY holiday_date", [hid, f.isoformat(), t.isoformat()])
    days = [(f + dt.timedelta(days=i)).isoformat() for i in range((t - f).days + 1)]
    off_per_day = {d: sum(1 for r in rows if r["status"] == "approved" and r["start_date"] <= d <= r["end_date"]) for d in days}
    return {"from": f.isoformat(), "to": t.isoformat(), "days": days, "items": rows, "holidays": hol, "off_per_day": off_per_day}


@route("GET", "/api/hotels/{hotel_id:int}/hr/leave-balances", perm="hr.view", tag="hr", summary="Leave balances of every active employee (?year)")
def all_balances(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        year = int(ctx.q("year", business_date(get_hotel(c, hid)).year))
        rows = []
        for e in c.all("SELECT * FROM employees WHERE hotel_id = ? AND status = 'active' ORDER BY department, first_name", [hid]):
            rows.append({"employee_id": e["id"], "employee": _name(e), "department": e["department"], "balances": leave_balances(c, e, year)})
        types = c.all("SELECT id, code, name FROM leave_types WHERE hotel_id = ? AND active = 1 ORDER BY id", [hid])
    return {"year": year, "types": types, "items": rows}


@route("POST", "/api/employees/{employee_id:int}/leave-adjustments", perm="hr.manage", tag="hr",
       summary="Add or remove leave days for a year (leave_type_id, days ±, year, reason), e.g. carry-over or long-service days")
def leave_adjustment(ctx: Ctx):
    days = ctx.field("days", kind=int)
    if days == 0 or abs(days) > 60:
        raise bad_request("days must be between -60 and 60 and not zero")
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        t = c.one("SELECT * FROM leave_types WHERE id = ? AND hotel_id = ?", [ctx.field("leave_type_id", kind=int), e["hotel_id"]])
        if not t:
            raise bad_request("Unknown leave type")
        year = int(ctx.field("year", required=False) or business_date(get_hotel(c, e["hotel_id"])).year)
        aid = c.insert("leave_adjustments", {"employee_id": e["id"], "leave_type_id": t["id"], "year": year, "days": days, "reason": reason[:300],
                                              "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "hr.leave_adjusted", "employee", e["id"], e["employee_no"], new={"type": t["code"], "days": days, "year": year, "reason": reason}, hotel_id=e["hotel_id"])
        _notify_employee(c, e, "Leave balance adjusted", f"{t['name']} {year}: {days:+d} day(s) — {reason}", "employee", e["id"])
    return {"id": aid, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/holidays", perm="hr.view", tag="hr", summary="Public holidays (?year)")
def list_holidays(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        year = str(ctx.q("year", business_date(get_hotel(c, hid)).year))
        return {"items": c.all("SELECT * FROM public_holidays WHERE hotel_id = ? AND holiday_date >= ? AND holiday_date <= ? ORDER BY holiday_date",
                               [hid, f"{year}-01-01", f"{year}-12-31"])}


@route("POST", "/api/hotels/{hotel_id:int}/holidays", perm="hr.manage", tag="hr", summary="Add a public holiday (holiday_date, name); it is not counted as a leave day")
def add_holiday(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    d = parse_date(ctx.field("holiday_date", kind=str), "holiday_date").isoformat()
    with get_db().tx() as c:
        if c.one("SELECT id FROM public_holidays WHERE hotel_id = ? AND holiday_date = ?", [hid, d]):
            raise conflict("There is already a holiday on that date")
        pid = c.insert("public_holidays", {"hotel_id": hid, "holiday_date": d, "name": ctx.field("name", kind=str)[:100]})
        audit(c, ctx, "hr.holiday_added", "public_holiday", pid, d, hotel_id=hid)
    return {"id": pid, "_created": True}


@route("DELETE", "/api/holidays/{holiday_id:int}", perm="hr.manage", tag="hr", summary="Remove a public holiday")
def remove_holiday(ctx: Ctx):
    with get_db().tx() as c:
        h = c.one("SELECT * FROM public_holidays WHERE id = ?", [ctx.path["holiday_id"]])
        if not h:
            raise not_found("Holiday")
        ctx.check_hotel(h["hotel_id"])
        c.execute("DELETE FROM public_holidays WHERE id = ?", [h["id"]])
        audit(c, ctx, "hr.holiday_removed", "public_holiday", h["id"], str(h["holiday_date"]), hotel_id=h["hotel_id"])
    return {"ok": True}


# ------------------------------------------------------------------ staff logins created by HR
ADMIN_PERMS = ("admin.users.manage", "admin.roles.manage", "admin.settings.manage", "admin.sessions.manage", "property.manage")


@route("GET", "/api/hr/assignable-roles", perm="hr.accounts", tag="hr", summary="Roles HR may give to staff logins (no administrator roles)")
def assignable_roles(ctx: Ctx):
    with get_db().tx() as c:
        rows = c.all("SELECT r.id, r.code, r.name FROM roles r WHERE r.organisation_id = ? ORDER BY r.name", [ctx.org_id])
        out = []
        for r in rows:
            perms = {p["permission_code"] for p in c.all("SELECT permission_code FROM role_permissions WHERE role_id = ?", [r["id"]])}
            if not perms & set(ADMIN_PERMS) and r["code"] not in ("guest",):
                out.append(r)
    return {"items": out}


@route("POST", "/api/employees/{employee_id:int}/account", perm="hr.accounts", tag="hr",
       summary="Give an employee a system login (email, role_id); administrator roles are excluded; returns a temporary password")
def create_account(ctx: Ctx):
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        if e["user_id"]:
            raise conflict("This employee already has a login")
        if e["status"] != "active":
            raise conflict("Only active employees can be given a login")
        email = (ctx.field("email", required=False, kind=str) or e["email"] or "").strip().lower()
        if "@" not in email:
            raise bad_request("A valid email is required")
        if c.one("SELECT id FROM users WHERE lower(email) = ?", [email]):
            raise conflict("A login with this email already exists; link it from the employee's Edit form instead")
        role = c.one("SELECT * FROM roles WHERE id = ? AND organisation_id = ?", [ctx.field("role_id", kind=int), ctx.org_id])
        if not role:
            raise bad_request("Choose a role")
        perms = {p["permission_code"] for p in c.all("SELECT permission_code FROM role_permissions WHERE role_id = ?", [role["id"]])}
        if perms & set(ADMIN_PERMS):
            raise forbidden("Administrator roles are given by system administrators, not HR")
        temp = "Tmp-" + secrets.token_urlsafe(9) + "9a"
        uid = c.insert("users", {"organisation_id": ctx.org_id, "email": email, "full_name": _name(e), "phone": e["phone"],
                                 "password_hash": security.hash_password(temp), "status": "active", "all_hotels": 0, "must_change_password": 1,
                                 "created_at": now_iso(), "password_changed_at": now_iso()})
        c.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", [uid, role["id"]])
        c.execute("INSERT INTO user_hotels (user_id, hotel_id) VALUES (?, ?)", [uid, e["hotel_id"]])
        c.update("employees", e["id"], {"user_id": uid, "email": email})
        audit(c, ctx, "hr.login_created", "user", uid, email, new={"employee": e["employee_no"], "role": role["code"]}, hotel_id=e["hotel_id"])
    return {"user_id": uid, "email": email, "temporary_password": temp, "role": role["name"], "_created": True}


# ------------------------------------------------------------------ self-service profile
@route("GET", "/api/me/hr", tag="hr", summary="My full HR file: profile, line manager, leave, requests, appraisals, training, roster this week, holidays")
def my_hr(ctx: Ctx):
    with get_db().tx() as c:
        e = c.one("SELECT * FROM employees WHERE user_id = ?", [ctx.user_id])
        if not e:
            return {"linked": False}
        today = business_date(get_hotel(c, e["hotel_id"]))
        monday = today - dt.timedelta(days=today.weekday())
        roster = c.all("SELECT a.work_date, s.name, s.start_time, s.end_time FROM shift_assignments a JOIN shift_templates s ON s.id = a.shift_id "
                       "WHERE a.employee_id = ? AND a.work_date >= ? AND a.work_date <= ? ORDER BY a.work_date",
                       [e["id"], monday.isoformat(), (monday + dt.timedelta(days=13)).isoformat()])
        lm = c.one("SELECT first_name, last_name, position FROM employees WHERE id = ?", [e["line_manager_id"]]) if e["line_manager_id"] else None
        apps = c.all("SELECT a.*, u.full_name AS reviewer FROM appraisals a JOIN users u ON u.id = a.reviewer_id WHERE a.employee_id = ? AND a.status <> 'draft' "
                     "ORDER BY a.id DESC", [e["id"]])
        for a in apps:
            a["criteria"] = json.loads(a["criteria"] or "[]")
        colleagues = c.all("SELECT id, first_name, last_name, department FROM employees WHERE hotel_id = ? AND status = 'active' AND id <> ? ORDER BY first_name", [e["hotel_id"], e["id"]])
        profile = {k: e[k] for k in ("id", "employee_no", "first_name", "last_name", "department", "position", "employment_type", "hire_date", "probation_end_date",
                                     "contract_end_date", "phone", "email", "address", "next_of_kin", "emergency_contact", "qualifications", "bank_name", "date_of_birth")}
        profile["bank_account_number"] = ("•" * 6 + e["bank_account_number"][-4:]) if e["bank_account_number"] else None
        return {"linked": True, "profile": profile, "line_manager": lm, "roster": roster,
                "appraisals": apps, "trainings": c.all("SELECT * FROM trainings WHERE employee_id = ? ORDER BY id DESC", [e["id"]]),
                "history": c.all("SELECT kind, effective_date, from_value, to_value FROM employee_history WHERE employee_id = ? ORDER BY effective_date DESC", [e["id"]]),
                "holidays": c.all("SELECT * FROM public_holidays WHERE hotel_id = ? AND holiday_date >= ? ORDER BY holiday_date LIMIT 8", [e["hotel_id"], today.isoformat()]),
                "colleagues": colleagues, "self_editable": list(SELF_EDITABLE)}


# ------------------------------------------------------------------ worker: HR alerts
def hr_alerts(c, hotel: dict) -> int:
    """Daily: tell HR about probation and contracts ending soon and certificates about to expire (each once)."""
    from ..worker import _once
    today = business_date(hotel)
    n = 0
    for e in c.all("SELECT * FROM employees WHERE hotel_id = ? AND status = 'active'", [hotel["id"]]):
        for field, days, label in (("probation_end_date", 14, "Probation ends"), ("contract_end_date", 30, "Contract ends")):
            d = e[field]
            if d and today.isoformat() <= str(d)[:10] <= (today + dt.timedelta(days=days)).isoformat() and _once(c, f"hr_{field}", f"{e['id']}:{d}"):
                _notify_perm(c, hotel["id"], "hr.manage", f"{label} soon", f"{_name(e)} — {label.lower()} on {d}. Review and record the decision.", "employee", e["id"])
                n += 1
    for t in c.all("SELECT tr.*, e.first_name, e.last_name FROM trainings tr JOIN employees e ON e.id = tr.employee_id WHERE e.hotel_id = ? AND e.status = 'active' "
                   "AND tr.expires_on IS NOT NULL AND tr.expires_on <= ?", [hotel["id"], (today + dt.timedelta(days=30)).isoformat()]):
        if _once(c, "hr_cert_expiry", f"{t['id']}:{t['expires_on']}"):
            _notify_perm(c, hotel["id"], "hr.manage", "Certificate expiring", f"{t['first_name']} {t['last_name']}: {t['title']} expires {t['expires_on']}.", "employee", t["employee_id"])
            n += 1
    return n


# ------------------------------------------------------------------ staff welfare (release 1.2)
WELFARE_KINDS = ("medical", "bereavement", "wedding", "childbirth", "hardship", "wellbeing", "other")


@route("POST", "/api/employees/{employee_id:int}/welfare", perm="hr.records", tag="hr",
       summary="Record welfare support given to an employee: kind, support_date, amount (optional), description (confidential)")
def add_welfare(ctx: Ctx):
    kind = ctx.field("kind", kind=str)
    if kind not in WELFARE_KINDS:
        raise bad_request(f"kind must be one of {', '.join(WELFARE_KINDS)}")
    amount = to_minor(ctx.field("amount", required=False, default=0) or 0)
    if amount < 0:
        raise bad_request("Amount cannot be negative")
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        d = parse_date(ctx.field("support_date", required=False, kind=str) or business_date(get_hotel(c, e["hotel_id"])).isoformat(), "support_date")
        wid = c.insert("welfare_records", {"employee_id": e["id"], "kind": kind, "support_date": d.isoformat(), "amount": amount,
                                           "description": str(ctx.field("description", kind=str))[:300], "confidential": 1,
                                           "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "hr.welfare_recorded", "employee", e["id"], e["employee_no"], new={"kind": kind, "amount": amount}, hotel_id=e["hotel_id"])
    return {"id": wid, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/hr/welfare", perm="hr.records", tag="hr", summary="Welfare register (?year)")
def list_welfare(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        year = int(ctx.q("year") or business_date(get_hotel(c, hid)).year)
        rows = c.all("SELECT w.*, e.first_name, e.last_name, e.employee_no, e.department, u.full_name AS recorded_by FROM welfare_records w "
                     "JOIN employees e ON e.id = w.employee_id JOIN users u ON u.id = w.created_by WHERE e.hotel_id = ? AND w.support_date >= ? AND w.support_date <= ? "
                     "ORDER BY w.support_date DESC, w.id DESC", [hid, f"{year}-01-01", f"{year}-12-31"])
    return {"year": year, "items": rows, "total_amount": sum(r["amount"] for r in rows), "kinds": WELFARE_KINDS}
