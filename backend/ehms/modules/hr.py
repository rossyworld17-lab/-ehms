"""Human resources: employee register, duty rosters, attendance, leave with balances and approval, HR records
(training, appraisal, disciplinary…) with restricted access, and staff self-service. (FR-HR-001..005)"""
from __future__ import annotations

import datetime as dt

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, next_number, parse_date, to_minor

DEPARTMENTS = ("front_office", "housekeeping", "fnb", "kitchen", "laundry", "maintenance", "security", "finance", "hr", "sales", "admin", "it", "spa", "other")
EMPLOYMENT_TYPES = ("full_time", "part_time", "contract", "casual", "intern")
RECORD_KINDS = ("training", "appraisal", "disciplinary", "commendation", "transfer", "promotion", "onboarding", "exit", "document")
SALARY_FIELDS = ("basic_salary", "housing_allowance", "transport_allowance", "other_allowance", "annual_rent")
SENSITIVE = ("bank_account_number", "tax_id", "pension_pin", "nhf_number")
DEFAULT_LEAVE = [("ANNUAL", "Annual leave", 15, 1), ("SICK", "Sick leave", 12, 1), ("MATERNITY", "Maternity leave", 84, 1),
                 ("PATERNITY", "Paternity leave", 14, 1), ("COMPASSION", "Compassionate leave", 5, 1), ("UNPAID", "Unpaid leave", 30, 0)]


def ensure_leave_types(c, hid: int) -> None:
    if not c.one("SELECT id FROM leave_types WHERE hotel_id = ?", [hid]):
        for code, name, days, paid in DEFAULT_LEAVE:
            c.insert("leave_types", {"hotel_id": hid, "code": code, "name": name, "days_per_year": days, "paid": paid, "active": 1})


def _mask(v: str | None) -> str | None:
    return None if not v else "•" * max(0, len(v) - 4) + v[-4:]


def present(ctx: Ctx, e: dict) -> dict:
    """Hide pay and identity fields from users without payroll/HR management rights."""
    e = dict(e)
    if not (ctx.can("hr.manage") or ctx.can("payroll.view")):
        for k in SALARY_FIELDS:
            e.pop(k, None)
    if not (ctx.can("hr.manage") or ctx.can("payroll.pay")):
        for k in SENSITIVE:
            e[k] = _mask(e.get(k))
    return e


def _employee(c, ctx: Ctx, eid) -> dict:
    e = c.one("SELECT * FROM employees WHERE id = ?", [int(eid)])
    if not e:
        raise not_found("Employee")
    ctx.check_hotel(e["hotel_id"])
    return e


def _payload(ctx: Ctx, partial: bool) -> dict:
    b = ctx.body or {}
    data: dict = {}
    for k in ("first_name", "last_name", "position"):
        if k in b or not partial:
            data[k] = ctx.field(k, kind=str)
    if "department" in b or not partial:
        data["department"] = ctx.field("department", kind=str)
        if data["department"] not in DEPARTMENTS:
            raise bad_request(f"department must be one of {', '.join(DEPARTMENTS)}")
    if "employment_type" in b:
        data["employment_type"] = ctx.field("employment_type", kind=str)
        if data["employment_type"] not in EMPLOYMENT_TYPES:
            raise bad_request("Unknown employment type")
    for k in ("hire_date", "date_of_birth"):
        if k in b or (k == "hire_date" and not partial):
            v = ctx.field(k, required=k == "hire_date" and not partial)
            data[k] = parse_date(v, k).isoformat() if v else None
    for k in ("gender", "phone", "email", "address", "bank_name", "bank_account_number", "tax_id", "pension_pfa", "pension_pin", "nhf_number",
              "next_of_kin", "emergency_contact", "qualifications"):
        if k in b:
            v = b[k]
            data[k] = str(v).strip() if v not in (None, "") else None
    for k in SALARY_FIELDS:
        if k in b:
            data[k] = to_minor(b[k] or 0, k)
            if data[k] < 0:
                raise bad_request(f"{k} cannot be negative")
    return data


@route("GET", "/api/hotels/{hotel_id:int}/employees", perm="hr.view", tag="hr", summary="Employees (?status, ?department, ?q)")
def list_employees(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql, params = "SELECT e.*, u.email AS user_email FROM employees e LEFT JOIN users u ON u.id = e.user_id WHERE e.hotel_id = ?", [hid]
    st = ctx.q("status", "active")
    if st != "all":
        sql += " AND e.status = ?"
        params.append(st)
    if ctx.q("department"):
        sql += " AND e.department = ?"
        params.append(ctx.q("department"))
    if ctx.q("q"):
        q = f"%{ctx.q('q').lower()}%"
        sql += " AND (LOWER(e.first_name) LIKE ? OR LOWER(e.last_name) LIKE ? OR LOWER(e.employee_no) LIKE ?)"
        params += [q, q, q]
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY e.department, e.last_name", params)
        heads = c.all("SELECT department, COUNT(*) AS n FROM employees WHERE hotel_id = ? AND status = 'active' GROUP BY department ORDER BY department", [hid])
    return {"items": [present(ctx, r) for r in rows], "headcount": heads, "departments": DEPARTMENTS, "employment_types": EMPLOYMENT_TYPES}


@route("POST", "/api/hotels/{hotel_id:int}/employees", perm="hr.manage", tag="hr", summary="Register an employee (employee number generated)")
def create_employee(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    data = _payload(ctx, partial=False)
    with get_db().tx() as c:
        uid = ctx.field("user_id", required=False)
        if uid:
            if not c.one("SELECT id FROM users WHERE id = ? AND organisation_id = ?", [int(uid), ctx.org_id]):
                raise bad_request("User account not found")
            if c.one("SELECT id FROM employees WHERE user_id = ?", [int(uid)]):
                raise conflict("That user account is already linked to an employee")
        number = next_number(c, hid, "employee", "EMP", 4)
        eid = c.insert("employees", {"hotel_id": hid, "employee_no": number, "user_id": int(uid) if uid else None, "status": "active",
                                     "created_at": now_iso(), **data})
        c.insert("hr_records", {"employee_id": eid, "kind": "onboarding", "record_date": data["hire_date"], "title": f"Joined as {data['position']}",
                                "details": None, "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "hr.employee_created", "employee", eid, number, new={k: v for k, v in data.items() if k not in SENSITIVE}, hotel_id=hid)
    return {"id": eid, "employee_no": number, "_created": True}


@route("GET", "/api/employees/{employee_id:int}", perm="hr.view", tag="hr", summary="Employee profile with leave balances, records (if permitted) and payslips")
def get_employee(ctx: Ctx):
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        out = present(ctx, e)
        out["leave_balances"] = leave_balances(c, e)
        out["leave_requests"] = c.all("SELECT l.*, t.name AS leave_type FROM leave_requests l JOIN leave_types t ON t.id = l.leave_type_id WHERE l.employee_id = ? "
                                      "ORDER BY l.id DESC LIMIT 50", [e["id"]])
        out["records"] = c.all("SELECT r.*, u.full_name AS created_by_name FROM hr_records r JOIN users u ON u.id = r.created_by WHERE r.employee_id = ? "
                               "ORDER BY r.record_date DESC, r.id DESC", [e["id"]]) if ctx.can("hr.records") else None
        out["payslips"] = c.all("SELECT p.id, r.period, r.status, p.gross, p.net FROM payslips p JOIN payroll_runs r ON r.id = p.run_id WHERE p.employee_id = ? "
                                "ORDER BY r.period DESC", [e["id"]]) if ctx.can("payroll.view") else None
        out["loans"] = c.all("SELECT * FROM employee_loans WHERE employee_id = ? ORDER BY id DESC", [e["id"]]) if ctx.can("payroll.view") else None
    return out


@route("PATCH", "/api/employees/{employee_id:int}", perm="hr.manage", tag="hr", summary="Edit an employee; status changes (resigned, terminated…) record an exit")
def update_employee(ctx: Ctx):
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        data = _payload(ctx, partial=True)
        b = ctx.body or {}
        if "status" in b and b["status"] != e["status"]:
            st = b["status"]
            if st not in ("active", "suspended", "terminated", "resigned", "retired"):
                raise bad_request("Unknown status")
            data["status"] = st
            if st in ("terminated", "resigned", "retired"):
                data["exit_date"] = parse_date(ctx.field("exit_date", required=False) or business_date(get_hotel(c, e["hotel_id"])).isoformat(), "exit_date").isoformat()
                data["exit_reason"] = ctx.field("exit_reason", kind=str)
                c.insert("hr_records", {"employee_id": e["id"], "kind": "exit", "record_date": data["exit_date"], "title": st.title(),
                                        "details": data["exit_reason"], "created_by": ctx.user_id, "created_at": now_iso()})
        if "user_id" in b:
            uid = b["user_id"]
            if uid and c.one("SELECT id FROM employees WHERE user_id = ? AND id <> ?", [int(uid), e["id"]]):
                raise conflict("That user account is already linked to another employee")
            data["user_id"] = int(uid) if uid else None
        for k in SALARY_FIELDS:
            if k in data and data[k] != e[k]:
                c.insert("hr_records", {"employee_id": e["id"], "kind": "promotion" if k == "basic_salary" and data[k] > e[k] else "document",
                                        "record_date": business_date(get_hotel(c, e["hotel_id"])).isoformat(),
                                        "title": f"{k.replace('_', ' ').title()} changed", "details": f"{e[k] / 100:,.2f} → {data[k] / 100:,.2f}",
                                        "created_by": ctx.user_id, "created_at": now_iso()})
        c.update("employees", e["id"], data)
        audit(c, ctx, "hr.employee_updated", "employee", e["id"], e["employee_no"],
              old={k: e.get(k) for k in data if k not in SENSITIVE}, new={k: v for k, v in data.items() if k not in SENSITIVE}, hotel_id=e["hotel_id"])
    return {"ok": True}


# ------------------------------------------------------------------ HR records (restricted)
@route("POST", "/api/employees/{employee_id:int}/records", perm="hr.records", tag="hr",
       summary="Add a training, appraisal, disciplinary, commendation, transfer or promotion record")
def add_record(ctx: Ctx):
    kind = ctx.field("kind", kind=str)
    if kind not in RECORD_KINDS:
        raise bad_request(f"kind must be one of {', '.join(RECORD_KINDS)}")
    rating = ctx.field("rating", required=False, kind=int)
    if rating is not None and not 1 <= rating <= 5:
        raise bad_request("rating must be 1–5")
    with get_db().tx() as c:
        e = _employee(c, ctx, ctx.path["employee_id"])
        rid = c.insert("hr_records", {"employee_id": e["id"], "kind": kind, "record_date": parse_date(ctx.field("record_date"), "record_date").isoformat(),
                                      "title": ctx.field("title", kind=str)[:200], "details": ctx.field("details", required=False, kind=str), "rating": rating,
                                      "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, f"hr.record_{kind}", "hr_record", rid, e["employee_no"], hotel_id=e["hotel_id"])
    return {"id": rid, "_created": True}


# ------------------------------------------------------------------ rosters & attendance
@route("GET", "/api/hotels/{hotel_id:int}/roster", perm="hr.view", tag="hr", summary="Weekly roster (?start=YYYY-MM-DD, Monday) and shift templates")
def roster(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid))
        start = parse_date(ctx.q("start", (today - dt.timedelta(days=today.weekday())).isoformat()), "start")
        days = [(start + dt.timedelta(days=i)).isoformat() for i in range(7)]
        shifts = c.all("SELECT * FROM shift_templates WHERE hotel_id = ? ORDER BY start_time", [hid])
        emps = c.all("SELECT id, employee_no, first_name, last_name, department, position FROM employees WHERE hotel_id = ? AND status = 'active' "
                     + ("AND department = ? " if ctx.q("department") else "") + "ORDER BY department, last_name", [hid] + ([ctx.q("department")] if ctx.q("department") else []))
        assign = c.all("SELECT a.* FROM shift_assignments a JOIN employees e ON e.id = a.employee_id WHERE e.hotel_id = ? AND a.work_date >= ? AND a.work_date <= ?",
                       [hid, days[0], days[-1]])
    grid = {(a["employee_id"], a["work_date"]): a["shift_id"] for a in assign}
    return {"start": days[0], "days": days, "shifts": shifts,
            "rows": [{**e, "shifts": [grid.get((e["id"], d)) for d in days]} for e in emps]}


@route("POST", "/api/hotels/{hotel_id:int}/shift-templates", perm="hr.attendance", tag="hr", summary="Create a shift template (name, start_time, end_time HH:MM)")
def create_shift(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    st, en = ctx.field("start_time", kind=str), ctx.field("end_time", kind=str)
    for t in (st, en):
        try:
            dt.time.fromisoformat(t)
        except ValueError:
            raise bad_request("Times must be HH:MM")
    with get_db().tx() as c:
        sid = c.insert("shift_templates", {"hotel_id": hid, "name": ctx.field("name", kind=str), "start_time": st, "end_time": en})
    return {"id": sid, "_created": True}


@route("PUT", "/api/hotels/{hotel_id:int}/roster", perm="hr.attendance", tag="hr",
       summary="Save roster cells: assignments[{employee_id, date, shift_id|null}]")
def save_roster(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        n = 0
        for a in ctx.field("assignments") or []:
            e = c.one("SELECT id FROM employees WHERE id = ? AND hotel_id = ?", [int(a.get("employee_id") or 0), hid])
            if not e:
                raise bad_request("Employee not found")
            d = parse_date(a.get("date"), "date").isoformat()
            c.execute("DELETE FROM shift_assignments WHERE employee_id = ? AND work_date = ?", [e["id"], d])
            if a.get("shift_id"):
                if not c.one("SELECT id FROM shift_templates WHERE id = ? AND hotel_id = ?", [int(a["shift_id"]), hid]):
                    raise bad_request("Shift not found")
                c.insert("shift_assignments", {"employee_id": e["id"], "work_date": d, "shift_id": int(a["shift_id"])})
            n += 1
        audit(c, ctx, "hr.roster_saved", "roster", None, None, new={"cells": n}, hotel_id=hid)
    return {"saved": n}


def _upsert_attendance(c, employee_id: int, d: str, data: dict, user_id) -> None:
    row = c.one("SELECT id FROM attendance WHERE employee_id = ? AND work_date = ?", [employee_id, d])
    if row:
        c.update("attendance", row["id"], {**data, "recorded_by": user_id, "recorded_at": now_iso()})
    else:
        c.insert("attendance", {"employee_id": employee_id, "work_date": d, "recorded_by": user_id, "recorded_at": now_iso(), **data})


@route("GET", "/api/hotels/{hotel_id:int}/attendance", perm="hr.view", tag="hr", summary="Attendance sheet for a date (?date) with rostered shift")
def attendance_sheet(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        d = parse_date(ctx.q("date", business_date(get_hotel(c, hid)).isoformat()), "date").isoformat()
        rows = c.all("SELECT e.id AS employee_id, e.employee_no, e.first_name, e.last_name, e.department, s.name AS shift, s.start_time, s.end_time, "
                     "a.status, a.clock_in, a.clock_out, a.overtime_minutes, a.note FROM employees e "
                     "LEFT JOIN shift_assignments sa ON sa.employee_id = e.id AND sa.work_date = ? LEFT JOIN shift_templates s ON s.id = sa.shift_id "
                     "LEFT JOIN attendance a ON a.employee_id = e.id AND a.work_date = ? WHERE e.hotel_id = ? AND e.status = 'active' ORDER BY e.department, e.last_name",
                     [d, d, hid])
    summary: dict[str, int] = {}
    for r in rows:
        summary[r["status"] or "not_recorded"] = summary.get(r["status"] or "not_recorded", 0) + 1
    return {"date": d, "items": rows, "summary": summary}


@route("PUT", "/api/hotels/{hotel_id:int}/attendance", perm="hr.attendance", tag="hr",
       summary="Record attendance: date, rows[{employee_id, status, clock_in, clock_out, overtime_minutes, note}]")
def save_attendance(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    d = parse_date(ctx.field("date"), "date").isoformat()
    with get_db().tx() as c:
        for r in ctx.field("rows") or []:
            e = c.one("SELECT id FROM employees WHERE id = ? AND hotel_id = ?", [int(r.get("employee_id") or 0), hid])
            if not e:
                raise bad_request("Employee not found")
            st = r.get("status")
            if st not in ("present", "late", "absent", "leave", "off"):
                raise bad_request("status must be present, late, absent, leave or off")
            ot = int(r.get("overtime_minutes") or 0)
            if not 0 <= ot <= 960:
                raise bad_request("Overtime must be between 0 and 960 minutes")
            _upsert_attendance(c, e["id"], d, {"status": st, "clock_in": r.get("clock_in") or None, "clock_out": r.get("clock_out") or None,
                                               "overtime_minutes": ot, "note": (r.get("note") or "")[:200] or None}, ctx.user_id)
        audit(c, ctx, "hr.attendance_saved", "attendance", d, d, new={"rows": len(ctx.field("rows") or [])}, hotel_id=hid)
    return {"ok": True}


# ------------------------------------------------------------------ leave
def leave_balances(c, e: dict, year: int | None = None) -> list[dict]:
    ensure_leave_types(c, e["hotel_id"])
    year = year or business_date(get_hotel(c, e["hotel_id"])).year
    used = {r["leave_type_id"]: r["d"] for r in c.all("SELECT leave_type_id, COALESCE(SUM(days),0) AS d FROM leave_requests WHERE employee_id = ? AND status = 'approved' "
                                                       "AND start_date >= ? AND start_date <= ? GROUP BY leave_type_id", [e["id"], f"{year}-01-01", f"{year}-12-31"])}
    pending = {r["leave_type_id"]: r["d"] for r in c.all("SELECT leave_type_id, COALESCE(SUM(days),0) AS d FROM leave_requests WHERE employee_id = ? AND status = 'pending' "
                                                          "GROUP BY leave_type_id", [e["id"]])}
    return [{"leave_type_id": t["id"], "code": t["code"], "name": t["name"], "entitlement": t["days_per_year"], "paid": bool(t["paid"]),
             "used": used.get(t["id"], 0), "pending": pending.get(t["id"], 0), "remaining": t["days_per_year"] - used.get(t["id"], 0)}
            for t in c.all("SELECT * FROM leave_types WHERE hotel_id = ? AND active = 1 ORDER BY id", [e["hotel_id"]])]


def working_days(a: dt.date, b: dt.date) -> int:
    return sum(1 for i in range((b - a).days + 1) if (a + dt.timedelta(days=i)).weekday() < 6)   # Mon–Sat (hotel week)


def _create_leave(c, ctx: Ctx, e: dict, body: dict) -> dict:
    ensure_leave_types(c, e["hotel_id"])
    t = c.one("SELECT * FROM leave_types WHERE id = ? AND hotel_id = ? AND active = 1", [int(body.get("leave_type_id") or 0), e["hotel_id"]])
    if not t:
        raise bad_request("Choose a leave type")
    a, b = parse_date(body.get("start_date"), "start_date"), parse_date(body.get("end_date"), "end_date")
    if b < a:
        raise bad_request("The end date must be on or after the start date")
    days = working_days(a, b)
    if days <= 0:
        raise bad_request("The selected dates contain no working days")
    if c.one("SELECT id FROM leave_requests WHERE employee_id = ? AND status IN ('pending','approved') AND start_date <= ? AND end_date >= ?",
             [e["id"], b.isoformat(), a.isoformat()]):
        raise conflict("This overlaps another leave request")
    bal = next(x for x in leave_balances(c, e, a.year) if x["leave_type_id"] == t["id"])
    if days > bal["remaining"] - bal["pending"]:
        raise conflict(f"Not enough {t['name']} left: {bal['remaining'] - bal['pending']} day(s) available, {days} requested")
    lid = c.insert("leave_requests", {"employee_id": e["id"], "leave_type_id": t["id"], "start_date": a.isoformat(), "end_date": b.isoformat(), "days": days,
                                      "reason": (body.get("reason") or "")[:300] or None, "status": "pending", "requested_by": ctx.user_id, "created_at": now_iso()})
    audit(c, ctx, "hr.leave_requested", "leave_request", lid, e["employee_no"], new={"type": t["code"], "days": days}, hotel_id=e["hotel_id"])
    return {"id": lid, "days": days, "_created": True}


@route("GET", "/api/hotels/{hotel_id:int}/leave", perm="hr.view", tag="hr", summary="Leave requests (?status) and leave types")
def list_leave(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        ensure_leave_types(c, hid)
        sql = ("SELECT l.*, t.name AS leave_type, e.first_name || ' ' || e.last_name AS employee, e.department, e.user_id, d.full_name AS decided_by_name "
               "FROM leave_requests l JOIN leave_types t ON t.id = l.leave_type_id JOIN employees e ON e.id = l.employee_id LEFT JOIN users d ON d.id = l.decided_by "
               "WHERE e.hotel_id = ?")
        params: list = [hid]
        if ctx.q("status"):
            sql += " AND l.status = ?"
            params.append(ctx.q("status"))
        return {"items": c.all(sql + " ORDER BY l.id DESC LIMIT 300", params), "types": c.all("SELECT * FROM leave_types WHERE hotel_id = ? ORDER BY id", [hid])}


@route("POST", "/api/employees/{employee_id:int}/leave", perm="hr.manage", tag="hr", summary="Record a leave request on behalf of an employee")
def leave_for(ctx: Ctx):
    with get_db().tx() as c:
        return _create_leave(c, ctx, _employee(c, ctx, ctx.path["employee_id"]), ctx.body or {})


@route("POST", "/api/leave/{leave_id:int}/decide", perm="hr.leave.approve", tag="hr",
       summary="Approve or reject a leave request (not your own); approval marks attendance as leave")
def decide_leave(ctx: Ctx):
    decision = ctx.field("decision", kind=str)
    if decision not in ("approve", "reject"):
        raise bad_request("decision must be approve or reject")
    with get_db().tx() as c:
        l = c.lock("leave_requests", int(ctx.path["leave_id"]))
        if not l:
            raise not_found("Leave request")
        e = _employee(c, ctx, l["employee_id"])
        if l["status"] != "pending":
            raise conflict(f"This request is already {l['status']}")
        if e["user_id"] == ctx.user_id or l["requested_by"] == ctx.user_id:
            raise forbidden("You cannot decide your own leave request")
        note = ctx.field("note", required=decision == "reject", kind=str)
        if decision == "approve":
            a, b = dt.date.fromisoformat(l["start_date"]), dt.date.fromisoformat(l["end_date"])
            for i in range((b - a).days + 1):
                d = a + dt.timedelta(days=i)
                if d.weekday() < 6:
                    _upsert_attendance(c, e["id"], d.isoformat(), {"status": "leave", "clock_in": None, "clock_out": None, "overtime_minutes": 0,
                                                                   "note": f"Leave #{l['id']}"}, ctx.user_id)
        c.update("leave_requests", l["id"], {"status": "approved" if decision == "approve" else "rejected", "decided_by": ctx.user_id,
                                             "decision_note": note, "decided_at": now_iso()})
        if e["user_id"]:
            from ..services import queue_notification
            queue_notification(c, e["hotel_id"], "in_app", str(e["user_id"]), f"Leave {decision}d",
                               f"Your leave from {l['start_date']} to {l['end_date']} was {decision}d" + (f": {note}" if note else "."), "leave_request", l["id"])
        audit(c, ctx, f"hr.leave_{decision}d", "leave_request", l["id"], e["employee_no"], new={"note": note}, hotel_id=e["hotel_id"])
    return {"status": "approved" if decision == "approve" else "rejected"}


@route("POST", "/api/hotels/{hotel_id:int}/leave-types", perm="hr.manage", tag="hr", summary="Add or update a leave type (code, name, days_per_year, paid)")
def save_leave_type(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    code = ctx.field("code", kind=str).upper()
    data = {"name": ctx.field("name", kind=str), "days_per_year": ctx.field("days_per_year", kind=int),
            "paid": 1 if ctx.field("paid", required=False, default=True) else 0, "active": 1 if ctx.field("active", required=False, default=True) else 0}
    if not 0 <= data["days_per_year"] <= 366:
        raise bad_request("days_per_year must be 0–366")
    with get_db().tx() as c:
        ensure_leave_types(c, hid)
        row = c.one("SELECT id FROM leave_types WHERE hotel_id = ? AND code = ?", [hid, code])
        if row:
            c.update("leave_types", row["id"], data)
        else:
            c.insert("leave_types", {"hotel_id": hid, "code": code, **data})
        audit(c, ctx, "hr.leave_type_saved", "leave_type", code, code, new=data, hotel_id=hid)
    return {"ok": True}


# ------------------------------------------------------------------ self-service (any signed-in staff member linked to an employee)
def _me(c, ctx: Ctx) -> dict:
    e = c.one("SELECT * FROM employees WHERE user_id = ?", [ctx.user_id])
    if not e:
        raise not_found("Your account is not linked to an employee record; ask HR")
    return e


@route("GET", "/api/me/employee", tag="hr", summary="My employee profile, leave balances, requests, attendance this month and payslips")
def my_employee(ctx: Ctx):
    with get_db().tx() as c:
        e = c.one("SELECT * FROM employees WHERE user_id = ?", [ctx.user_id])
        if not e:
            return {"linked": False}
        today = business_date(get_hotel(c, e["hotel_id"]))
        return {"linked": True, "employee": {k: e[k] for k in ("id", "employee_no", "first_name", "last_name", "department", "position", "hire_date", "employment_type")},
                "leave_balances": leave_balances(c, e),
                "leave_requests": c.all("SELECT l.*, t.name AS leave_type FROM leave_requests l JOIN leave_types t ON t.id = l.leave_type_id WHERE l.employee_id = ? "
                                        "ORDER BY l.id DESC LIMIT 20", [e["id"]]),
                "attendance": c.all("SELECT * FROM attendance WHERE employee_id = ? AND work_date >= ? ORDER BY work_date DESC", [e["id"], today.replace(day=1).isoformat()]),
                "today": c.one("SELECT * FROM attendance WHERE employee_id = ? AND work_date = ?", [e["id"], today.isoformat()]),
                "shift_today": c.one("SELECT s.* FROM shift_assignments a JOIN shift_templates s ON s.id = a.shift_id WHERE a.employee_id = ? AND a.work_date = ?",
                                     [e["id"], today.isoformat()]),
                "payslips": c.all("SELECT p.id, r.period, p.gross, p.net FROM payslips p JOIN payroll_runs r ON r.id = p.run_id WHERE p.employee_id = ? "
                                  "AND r.status IN ('approved','paid') ORDER BY r.period DESC", [e["id"]])}


@route("POST", "/api/me/leave", tag="hr", summary="Request leave for myself")
def my_leave(ctx: Ctx):
    with get_db().tx() as c:
        return _create_leave(c, ctx, _me(c, ctx), ctx.body or {})


@route("POST", "/api/me/clock", tag="hr", summary="Clock in or out (action=in|out); late if more than 15 minutes after the rostered start")
def my_clock(ctx: Ctx):
    action = ctx.field("action", kind=str)
    if action not in ("in", "out"):
        raise bad_request("action must be in or out")
    with get_db().tx() as c:
        e = _me(c, ctx)
        hotel = get_hotel(c, e["hotel_id"])
        from ..services import hotel_today
        try:
            from zoneinfo import ZoneInfo
            now = dt.datetime.now(ZoneInfo(hotel["timezone"]))
        except Exception:
            now = dt.datetime.now()
        d = hotel_today(hotel).isoformat()
        hhmm = now.strftime("%H:%M")
        row = c.one("SELECT * FROM attendance WHERE employee_id = ? AND work_date = ?", [e["id"], d])
        if action == "in":
            if row and row["clock_in"]:
                raise conflict(f"You already clocked in at {row['clock_in']}")
            shift = c.one("SELECT s.* FROM shift_assignments a JOIN shift_templates s ON s.id = a.shift_id WHERE a.employee_id = ? AND a.work_date = ?", [e["id"], d])
            late = False
            if shift:
                start = dt.datetime.combine(now.date(), dt.time.fromisoformat(shift["start_time"]))
                late = now.replace(tzinfo=None) > start + dt.timedelta(minutes=15)
            _upsert_attendance(c, e["id"], d, {"status": "late" if late else "present", "clock_in": hhmm, "note": "Self clock-in"}, ctx.user_id)
            return {"clocked": "in", "time": hhmm, "status": "late" if late else "present"}
        if not row or not row["clock_in"]:
            raise conflict("Clock in first")
        if row["clock_out"]:
            raise conflict(f"You already clocked out at {row['clock_out']}")
        c.update("attendance", row["id"], {"clock_out": hhmm, "recorded_at": now_iso()})
        return {"clocked": "out", "time": hhmm}
