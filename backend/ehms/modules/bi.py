"""Business intelligence (FR-BI-001..005, FR-PMS-003, FR-HR-005): role-filtered analytics with filters by
property, period, granularity and department, period-over-period comparison, occupancy history by room
category and room, HR analytics, and scheduled reports delivered through the document store.

Financial figures (revenue by department, expenses, gross operating profit) come only from posted journal
entries — the approved accounting records — and need reports.financial; operational figures (occupancy, ADR,
RevPAR, bookings) come from reservations and folios."""
from __future__ import annotations

import calendar
import datetime as dt
import json
from collections import defaultdict

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, parse_date

GRANULARITIES = ("day", "week", "month", "quarter", "year")


def bucket(d: dt.date, gran: str) -> str:
    if gran == "day":
        return d.isoformat()
    if gran == "week":
        return (d - dt.timedelta(days=d.weekday())).isoformat()
    if gran == "month":
        return d.strftime("%Y-%m")
    if gran == "quarter":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    return str(d.year)


def _shift_year(d: dt.date, years: int) -> dt.date:
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        return d.replace(year=d.year + years, day=28)


def _days(a: dt.date, b: dt.date):
    while a <= b:
        yield a
        a += dt.timedelta(days=1)


def _pct(cur, prev):
    if prev in (None, 0):
        return None
    return round((cur - prev) * 100 / abs(prev), 1)


def resolve_hotels(c, ctx: Ctx) -> list[dict]:
    raw = ctx.q("hotel_ids") or ctx.q("hotel_id")
    rows = c.all("SELECT * FROM hotels WHERE organisation_id = ? AND active = 1 ORDER BY id", [ctx.org_id])
    allowed = [h for h in rows if ctx.hotel_ids is None or h["id"] in ctx.hotel_ids]
    if raw:
        want = set()
        for x in str(raw).split(","):
            if x.strip():
                want.add(ctx.check_hotel(int(x)))
        allowed = [h for h in allowed if h["id"] in want]
        if not allowed:
            raise forbidden("None of the requested hotels are accessible")
    if not allowed:
        raise forbidden("You are not assigned to any hotel")
    return allowed


def period_metrics(c, hotels: list[dict], d_from: dt.date, d_to: dt.date, gran: str, dept: str | None, financial: bool) -> dict:
    from .pos import _prorate
    hids = [h["id"] for h in hotels]
    ph = ",".join("?" * len(hids))
    f, t = d_from.isoformat(), d_to.isoformat()
    ndays = (d_to - d_from).days + 1
    series: dict[str, dict] = {}
    for d in _days(d_from, d_to):
        series.setdefault(bucket(d, gran), {"period": bucket(d, gran), "available": 0, "sold": 0, "room_revenue": 0, "revenue": 0, "expenses": 0})
    per_hotel = {}
    total = {"available": 0, "sold": 0, "room_revenue": 0}
    for h in hotels:
        rooms = c.scalar("SELECT COUNT(*) FROM rooms WHERE hotel_id = ? AND active = 1", [h["id"]]) or 0
        bdate = business_date(h)
        sold_by_day: dict[str, int] = defaultdict(int)
        for r in c.all("SELECT arrival, departure, status FROM reservations WHERE hotel_id = ? AND arrival <= ? AND departure > ? "
                       "AND status IN ('checked_in','checked_out','confirmed','tentative')", [h["id"], t, f]):
            a = max(dt.date.fromisoformat(r["arrival"]), d_from)
            b = min(dt.date.fromisoformat(r["departure"]) - dt.timedelta(days=1), d_to)
            for d in _days(a, b):
                # past nights count only actual stays; today and later include business on the books
                if d < bdate and r["status"] not in ("checked_in", "checked_out"):
                    continue
                sold_by_day[d.isoformat()] += 1
        rev_by_day = {r["business_date"]: r["v"] for r in c.all(
            "SELECT fl.business_date, COALESCE(SUM(fl.net_amount),0) AS v FROM folio_lines fl JOIN folios fo ON fo.id = fl.folio_id WHERE fo.hotel_id = ? "
            "AND fl.department = 'room' AND fl.kind IN ('charge','adjustment') AND fl.business_date >= ? AND fl.business_date <= ? GROUP BY fl.business_date",
            [h["id"], f, t])}
        hs = {"available": rooms * ndays, "sold": sum(sold_by_day.values()), "room_revenue": sum(rev_by_day.values())}
        for d in _days(d_from, d_to):
            s = series[bucket(d, gran)]
            s["available"] += rooms
            s["sold"] += sold_by_day.get(d.isoformat(), 0)
            s["room_revenue"] += rev_by_day.get(d.isoformat(), 0)
        for k in total:
            total[k] += hs[k]
        hs.update({"hotel_id": h["id"], "hotel": h["name"], "occupancy_pct": round(hs["sold"] * 100 / hs["available"], 1) if hs["available"] else 0.0,
                   "adr": hs["room_revenue"] // hs["sold"] if hs["sold"] else 0, "revpar": hs["room_revenue"] // hs["available"] if hs["available"] else 0})
        per_hotel[h["id"]] = hs
    # bookings / channel / cancellations (by date made or cancelled)
    made = c.all(f"SELECT source, booking_type, status, arrival, departure, created_at FROM reservations WHERE hotel_id IN ({ph}) "
                 "AND created_at >= ? AND created_at <= ? AND status <> 'enquiry'", hids + [f, t + "T23:59:59Z"])
    cancelled = c.scalar(f"SELECT COUNT(*) FROM reservations WHERE hotel_id IN ({ph}) AND status = 'cancelled' AND cancelled_at >= ? AND cancelled_at <= ?",
                         hids + [f, t + "T23:59:59Z"]) or 0
    no_shows = c.scalar(f"SELECT COUNT(*) FROM reservations WHERE hotel_id IN ({ph}) AND status = 'no_show' AND arrival >= ? AND arrival <= ?", hids + [f, t]) or 0
    by_source: dict[str, int] = defaultdict(int)
    by_type: dict[str, int] = defaultdict(int)
    lead, los = [], []
    for r in made:
        by_source[r["source"]] += 1
        by_type[r["booking_type"]] += 1
        a, b = dt.date.fromisoformat(r["arrival"]), dt.date.fromisoformat(r["departure"])
        lead.append(max(0, (a - dt.date.fromisoformat(r["created_at"][:10])).days))
        los.append((b - a).days)
    out = {
        "from": f, "to": t, "days": ndays,
        "kpis": {"available_room_nights": total["available"], "room_nights_sold": total["sold"],
                 "occupancy_pct": round(total["sold"] * 100 / total["available"], 1) if total["available"] else 0.0,
                 "room_revenue": total["room_revenue"], "adr": total["room_revenue"] // total["sold"] if total["sold"] else 0,
                 "revpar": total["room_revenue"] // total["available"] if total["available"] else 0,
                 "bookings_made": len(made), "cancellations": cancelled, "no_shows": no_shows,
                 "cancellation_rate_pct": round(cancelled * 100 / (len(made) + cancelled), 1) if (len(made) + cancelled) else 0.0,
                 "avg_lead_time_days": round(sum(lead) / len(lead), 1) if lead else 0, "avg_length_of_stay": round(sum(los) / len(los), 2) if los else 0},
        "by_source": sorted([{"source": k, "bookings": v} for k, v in by_source.items()], key=lambda x: -x["bookings"]),
        "by_booking_type": sorted([{"type": k, "bookings": v} for k, v in by_type.items()], key=lambda x: -x["bookings"]),
        "by_hotel": list(per_hotel.values()),
    }
    if financial:
        # approved accounting records only: posted (append-only) journal lines
        sql = (f"SELECT je.entry_date, a.code, a.name, a.type, jl.department, SUM(jl.debit) AS dr, SUM(jl.credit) AS cr FROM journal_lines jl "
               f"JOIN journal_entries je ON je.id = jl.entry_id JOIN accounts a ON a.id = jl.account_id WHERE je.hotel_id IN ({ph}) "
               "AND je.entry_date >= ? AND je.entry_date <= ? AND a.type IN ('revenue','expense')")
        params = hids + [f, t]
        if dept:
            sql += " AND jl.department = ?"
            params.append(dept)
        rows = c.all(sql + " GROUP BY je.entry_date, a.code, a.name, a.type, jl.department", params)
        rev_acc: dict[tuple, int] = defaultdict(int)
        exp_acc: dict[tuple, int] = defaultdict(int)
        rev_dept: dict[str, int] = defaultdict(int)
        for r in rows:
            d = dt.date.fromisoformat(str(r["entry_date"])[:10])
            if r["type"] == "revenue":
                v = r["cr"] - r["dr"]
                rev_acc[(r["code"], r["name"])] += v
                rev_dept[r["department"] or "other"] += v
                series[bucket(d, gran)]["revenue"] += v
            else:
                v = r["dr"] - r["cr"]
                exp_acc[(r["code"], r["name"])] += v
                series[bucket(d, gran)]["expenses"] += v
        revenue, expenses = sum(rev_acc.values()), sum(exp_acc.values())
        out["financial"] = {
            "source": "posted journal entries (general ledger)", "revenue": revenue, "expenses": expenses, "gross_operating_profit": revenue - expenses,
            "gop_margin_pct": round((revenue - expenses) * 100 / revenue, 1) if revenue else None,
            "revenue_by_department": sorted([{"department": k, "amount": v} for k, v in rev_dept.items()], key=lambda x: -x["amount"]),
            "revenue_by_account": sorted([{"code": k[0], "name": k[1], "amount": v} for k, v in rev_acc.items()], key=lambda x: x["code"]),
            "expenses_by_account": sorted([{"code": k[0], "name": k[1], "amount": v} for k, v in exp_acc.items()], key=lambda x: -x["amount"]),
        }
    for s in series.values():
        s["occupancy_pct"] = round(s["sold"] * 100 / s["available"], 1) if s["available"] else 0.0
        s["adr"] = s["room_revenue"] // s["sold"] if s["sold"] else 0
        s["revpar"] = s["room_revenue"] // s["available"] if s["available"] else 0
        if not financial:
            s.pop("revenue")
            s.pop("expenses")
    out["series"] = list(series.values())
    return out


@route("GET", "/api/bi/analytics", perm="bi.view", tag="bi",
       summary="Analytics (?hotel_ids=1,2&from&to&granularity=day|week|month|quarter|year&compare=previous_period|previous_year|none&department)")
def analytics(ctx: Ctx):
    gran = ctx.q("granularity", "day")
    if gran not in GRANULARITIES:
        raise bad_request(f"granularity must be one of {', '.join(GRANULARITIES)}")
    compare = ctx.q("compare", "previous_period")
    if compare not in ("previous_period", "previous_year", "none"):
        raise bad_request("compare must be previous_period, previous_year or none")
    dept = ctx.q("department")
    financial = ctx.can("reports.financial")
    with get_db().tx() as c:
        hotels = resolve_hotels(c, ctx)
        bdate = business_date(hotels[0])
        d_to = parse_date(ctx.q("to", (bdate - dt.timedelta(days=1)).isoformat()), "to")
        d_from = parse_date(ctx.q("from", (d_to - dt.timedelta(days=29)).isoformat()), "from")
        if d_from > d_to:
            raise bad_request("'from' must be on or before 'to'")
        if (d_to - d_from).days > 731:
            raise bad_request("Maximum range is two years")
        cur = period_metrics(c, hotels, d_from, d_to, gran, dept, financial)
        prev = None
        if compare == "previous_period":
            n = (d_to - d_from).days + 1
            prev = period_metrics(c, hotels, d_from - dt.timedelta(days=n), d_from - dt.timedelta(days=1), gran, dept, financial)
        elif compare == "previous_year":
            prev = period_metrics(c, hotels, _shift_year(d_from, -1), _shift_year(d_to, -1), gran, dept, financial)
    out = {"hotels": [{"id": h["id"], "name": h["name"], "currency": h["currency"]} for h in hotels], "granularity": gran, "department": dept,
           "financial_access": financial, "current": cur, "comparison": None}
    if prev:
        delta = {k: _pct(v, prev["kpis"].get(k)) for k, v in cur["kpis"].items() if isinstance(v, (int, float))}
        if financial:
            for k in ("revenue", "expenses", "gross_operating_profit"):
                delta[k] = _pct(cur["financial"][k], prev["financial"][k])
        out["comparison"] = {"mode": compare, "from": prev["from"], "to": prev["to"], "kpis": prev["kpis"],
                             "financial": prev.get("financial"), "series": prev["series"], "change_pct": delta}
    if not financial:
        out["note"] = "Financial figures (revenue by department, expenses, profit) need the reports.financial permission."
    return out


@route("GET", "/api/hotels/{hotel_id:int}/bi/occupancy-history", perm="bi.view", tag="bi",
       summary="Occupancy history by room category per day and nights/revenue per room (?from&to)")
def occupancy_history(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        bdate = business_date(hotel)
        d_to = parse_date(ctx.q("to", (bdate - dt.timedelta(days=1)).isoformat()), "to")
        d_from = parse_date(ctx.q("from", (d_to - dt.timedelta(days=29)).isoformat()), "from")
        if (d_to - d_from).days > 366 or d_from > d_to:
            raise bad_request("Choose a range of up to one year")
        types = c.all("SELECT rt.id, rt.name, COUNT(r.id) AS rooms FROM room_types rt LEFT JOIN rooms r ON r.room_type_id = rt.id AND r.active = 1 "
                      "WHERE rt.hotel_id = ? GROUP BY rt.id, rt.name ORDER BY rt.name", [hid])
        res = c.all("SELECT room_type_id, room_id, arrival, departure FROM reservations WHERE hotel_id = ? AND status IN ('checked_in','checked_out') "
                    "AND arrival <= ? AND departure > ?", [hid, d_to.isoformat(), d_from.isoformat()])
        grid: dict[tuple, int] = defaultdict(int)
        room_nights: dict[int, int] = defaultdict(int)
        for r in res:
            a = max(dt.date.fromisoformat(r["arrival"]), d_from)
            b = min(dt.date.fromisoformat(r["departure"]) - dt.timedelta(days=1), d_to)
            for d in _days(a, b):
                grid[(r["room_type_id"], d.isoformat())] += 1
                if r["room_id"]:
                    room_nights[r["room_id"]] += 1
        room_rev = {r["room_id"]: r["v"] for r in c.all(
            "SELECT res.room_id, COALESCE(SUM(fl.net_amount),0) AS v FROM folio_lines fl JOIN folios fo ON fo.id = fl.folio_id JOIN reservations res ON res.id = fo.reservation_id "
            "WHERE fo.hotel_id = ? AND fl.department = 'room' AND fl.kind IN ('charge','adjustment') AND fl.business_date >= ? AND fl.business_date <= ? GROUP BY res.room_id",
            [hid, d_from.isoformat(), d_to.isoformat()])}
        rooms = c.all("SELECT r.id, r.number, rt.name AS room_type FROM rooms r JOIN room_types rt ON rt.id = r.room_type_id WHERE r.hotel_id = ? AND r.active = 1 ORDER BY r.number", [hid])
        ooo = c.all("SELECT room_id, COUNT(*) AS n FROM work_orders WHERE hotel_id = ? AND blocks_room = 1 AND created_at >= ? AND created_at <= ? GROUP BY room_id",
                    [hid, d_from.isoformat(), d_to.isoformat() + "T23:59:59Z"])
    days = [d.isoformat() for d in _days(d_from, d_to)]
    ndays = len(days)
    oooc = {r["room_id"]: r["n"] for r in ooo}
    return {"from": d_from.isoformat(), "to": d_to.isoformat(), "dates": days,
            "categories": [{"id": t["id"], "name": t["name"], "rooms": t["rooms"],
                            "sold": [grid.get((t["id"], d), 0) for d in days],
                            "occupancy_pct": [round(grid.get((t["id"], d), 0) * 100 / t["rooms"], 1) if t["rooms"] else 0 for d in days]} for t in types],
            "rooms": [{"id": r["id"], "number": r["number"], "room_type": r["room_type"], "nights_sold": room_nights.get(r["id"], 0),
                       "occupancy_pct": round(room_nights.get(r["id"], 0) * 100 / ndays, 1), "room_revenue": room_rev.get(r["id"], 0),
                       "blocking_work_orders": oooc.get(r["id"], 0)} for r in rooms]}


@route("GET", "/api/hotels/{hotel_id:int}/bi/hr", perm="bi.view", tag="bi",
       summary="HR analytics: headcount, joiners/leavers, turnover, attendance, lateness, overtime, leave and payroll cost (?from&to)")
def hr_analytics(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    ctx.require("hr.view")
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        bdate = business_date(hotel)
        d_to = parse_date(ctx.q("to", bdate.isoformat()), "to")
        d_from = parse_date(ctx.q("from", (d_to - dt.timedelta(days=89)).isoformat()), "from")
        f, t = d_from.isoformat(), d_to.isoformat()
        emps = c.all("SELECT id, department, status, hire_date, exit_date, gender, employment_type FROM employees WHERE hotel_id = ?", [hid])
        active_end = [e for e in emps if e["hire_date"] <= t and (not e["exit_date"] or e["exit_date"] > t)]
        active_start = [e for e in emps if e["hire_date"] <= f and (not e["exit_date"] or e["exit_date"] > f)]
        joiners = [e for e in emps if f <= e["hire_date"] <= t]
        leavers = [e for e in emps if e["exit_date"] and f <= e["exit_date"] <= t]
        avg_head = (len(active_start) + len(active_end)) / 2 or 1
        att = c.all("SELECT e.department, a.status, a.overtime_minutes FROM attendance a JOIN employees e ON e.id = a.employee_id WHERE e.hotel_id = ? "
                    "AND a.work_date >= ? AND a.work_date <= ?", [hid, f, t])
        dep: dict[str, dict] = defaultdict(lambda: {"headcount": 0, "present": 0, "late": 0, "absent": 0, "leave": 0, "overtime_hours": 0.0})
        for e in active_end:
            dep[e["department"]]["headcount"] += 1
        for a in att:
            d = dep[a["department"]]
            if a["status"] in ("present", "late", "absent", "leave"):
                d[a["status"]] += 1
            d["overtime_hours"] += (a["overtime_minutes"] or 0) / 60
        for d in dep.values():
            worked = d["present"] + d["late"] + d["absent"]
            d["attendance_rate_pct"] = round((d["present"] + d["late"]) * 100 / worked, 1) if worked else None
            d["lateness_rate_pct"] = round(d["late"] * 100 / (d["present"] + d["late"]), 1) if (d["present"] + d["late"]) else None
            d["overtime_hours"] = round(d["overtime_hours"], 1)
        leave = c.all("SELECT lt.name, COUNT(*) AS requests, COALESCE(SUM(l.days),0) AS days FROM leave_requests l JOIN leave_types lt ON lt.id = l.leave_type_id "
                      "JOIN employees e ON e.id = l.employee_id WHERE e.hotel_id = ? AND l.status = 'approved' AND l.start_date <= ? AND l.end_date >= ? GROUP BY lt.name",
                      [hid, t, f])
        payroll = []
        if ctx.can("payroll.view"):
            payroll = [dict(r) for r in c.all("SELECT period, status, employees, gross, net, paye, employer_cost FROM payroll_runs WHERE hotel_id = ? "
                                              "AND period >= ? AND period <= ? ORDER BY period", [hid, f[:7], t[:7]])]
    tot = {k: sum(d[k] for d in dep.values()) for k in ("present", "late", "absent")}
    worked = sum(tot.values())
    return {"from": f, "to": t,
            "summary": {"headcount": len(active_end), "joiners": len(joiners), "leavers": len(leavers),
                        "turnover_pct": round(len(leavers) * 100 / avg_head, 1),
                        "attendance_rate_pct": round((tot["present"] + tot["late"]) * 100 / worked, 1) if worked else None,
                        "overtime_hours": round(sum(d["overtime_hours"] for d in dep.values()), 1)},
            "by_department": sorted([{"department": k, **v} for k, v in dep.items()], key=lambda x: x["department"]),
            "by_gender": [{"gender": g or "not recorded", "count": sum(1 for e in active_end if e["gender"] == g)} for g in sorted({e["gender"] for e in active_end}, key=lambda x: x or "")],
            "by_employment_type": [{"type": k, "count": sum(1 for e in active_end if e["employment_type"] == k)} for k in sorted({e["employment_type"] for e in active_end})],
            "leave": [dict(r) for r in leave], "payroll": payroll,
            "payroll_note": None if ctx.can("payroll.view") else "Payroll cost needs payroll.view"}


# ------------------------------------------------------------------ scheduled reports
def _user_ctx(c, user_id: int) -> Ctx | None:
    u = c.one("SELECT * FROM users WHERE id = ?", [user_id])
    if not u or u["status"] != "active":
        return None
    perms = {r["permission_code"] for r in c.all("SELECT DISTINCT rp.permission_code FROM user_roles ur JOIN role_permissions rp ON rp.role_id = ur.role_id "
                                                 "WHERE ur.user_id = ?", [user_id])}
    hotels = None if u["all_hotels"] else {r["hotel_id"] for r in c.all("SELECT hotel_id FROM user_hotels WHERE user_id = ?", [user_id])}
    return Ctx(request=None, user=u, permissions=perms, hotel_ids=hotels)


def _may_receive(uctx: Ctx | None, hid: int, code: str) -> bool:
    from .reports import REPORT_PERMS
    if not uctx or not uctx.can("reports.view") or not uctx.can("documents.view"):
        return False
    if uctx.hotel_ids is not None and hid not in uctx.hotel_ids:
        return False
    p = REPORT_PERMS.get(code)
    return not p or uctx.can(p)


def _period_params(code: str, freq: str, today: dt.date, base: dict) -> tuple[dict, str]:
    """Reports cover the period just ended: yesterday, last 7 days or last calendar month."""
    if freq == "daily":
        a = b = today - dt.timedelta(days=1)
    elif freq == "weekly":
        b = today - dt.timedelta(days=1)
        a = b - dt.timedelta(days=6)
    else:
        b = today.replace(day=1) - dt.timedelta(days=1)
        a = b.replace(day=1)
    p = dict(base)
    if code in ("arrivals", "departures", "in_house", "daily_revenue"):
        p.setdefault("date", (today if code in ("arrivals", "in_house") else b).isoformat())
        label = p["date"]
    else:
        p.setdefault("from", a.isoformat())
        p.setdefault("to", b.isoformat())
        label = f"{p['from']} to {p['to']}"
    return p, label


def is_due(s: dict, today: dt.date) -> bool:
    if not s["active"] or (s["last_run_on"] and str(s["last_run_on"])[:10] >= today.isoformat()):
        return False
    if s["frequency"] == "daily":
        return True
    if s["frequency"] == "weekly":
        return today.weekday() == (s["weekday"] or 0)
    last = calendar.monthrange(today.year, today.month)[1]
    return today.day == min(s["month_day"] or 1, last)


def run_schedule(c, s: dict, hotel: dict, today: dt.date) -> dict:
    """Generate one scheduled report as its creator (permissions checked now, not when it was scheduled)."""
    from .documents import store_document
    from .messaging import notify_template
    from .reports import REPORTS, _report_rows, render_report
    creator = _user_ctx(c, s["created_by"])
    status, err, doc_id, sent, skipped = "ok", None, None, 0, 0
    if not creator or not creator.can("bi.schedule") or not _may_receive(creator, hotel["id"], s["report_code"]):
        status, err = "suspended", "The person who scheduled this report no longer has the required permissions"
        c.update("report_schedules", s["id"], {"active": 0, "last_run_on": today.isoformat(), "last_status": status, "last_error": err})
        return {"status": status}
    params, label = _period_params(s["report_code"], s["frequency"], today, json.loads(s["params"] or "{}"))
    creator.query = {k: str(v) for k, v in params.items()}
    try:
        title, cols, rows = _report_rows(c, creator, hotel["id"], s["report_code"])
        data, _, ext = render_report(s["format"], s["report_code"], title, cols, rows, hotel["name"])
        doc_id = store_document(c, org_id=hotel["organisation_id"], hotel_id=hotel["id"], entity_type="report", entity_id=s["id"], category="report",
                                title=f"{s['name']} — {label}", filename=f"{s['report_code']}-{today.isoformat()}.{ext}", data=data,
                                confidentiality="confidential" if s["report_code"] in ("daily_revenue", "outstanding_balances", "outlet_sales", "payables") else "internal",
                                user_id=creator.user_id, notes=f"Generated automatically by schedule #{s['id']}")
        import os
        base = (os.environ.get("EHMS_PUBLIC_URL") or "").rstrip("/")
        for uid in json.loads(s["recipients"] or "[]"):
            u = _user_ctx(c, int(uid))
            if not _may_receive(u, hotel["id"], s["report_code"]):
                skipped += 1
                continue
            notify_template(c, hotel, "scheduled_report", {"user_id": u.user_id, "email": u.user["email"]},
                            {"report": s["name"] or REPORTS.get(s["report_code"]), "period": label, "link": f"{base}/staff#/documents/{doc_id}"}, "document", doc_id)
            sent += 1
    except Exception as e:  # report parameter errors are recorded on the schedule, not raised in the worker
        status, err = "failed", getattr(e, "message", str(e))[:300]
    c.update("report_schedules", s["id"], {"last_run_on": today.isoformat(), "last_status": status if status != "ok" else f"ok: {sent} sent, {skipped} skipped",
                                           "last_error": err})
    return {"status": status, "document_id": doc_id, "sent": sent, "skipped": skipped}


def run_due_schedules(c, hotel: dict) -> int:
    today = business_date(hotel)
    n = 0
    from ..worker import _once
    for s in c.all("SELECT * FROM report_schedules WHERE hotel_id = ? AND active = 1", [hotel["id"]]):
        # _once: with several app processes each running the worker, a schedule is still generated once per day
        if is_due(s, today) and _once(c, "report_schedule", f"{s['id']}:{today}"):
            run_schedule(c, s, hotel, today)
            n += 1
    return n


def _sched_view(s: dict, users: dict) -> dict:
    out = dict(s)
    out["params"] = json.loads(s["params"] or "{}")
    out["recipients"] = [{"id": int(u), "name": users.get(int(u), "?")} for u in json.loads(s["recipients"] or "[]")]
    out["created_by_name"] = users.get(s["created_by"])
    return out


@route("GET", "/api/hotels/{hotel_id:int}/report-schedules", perm="bi.schedule", tag="bi", summary="Scheduled reports and eligible recipients")
def list_schedules(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    from .reports import REPORTS, REPORT_PERMS
    with get_db().tx() as c:
        rows = c.all("SELECT * FROM report_schedules WHERE hotel_id = ? ORDER BY id DESC", [hid])
        users = {u["id"]: u["full_name"] for u in c.all("SELECT id, full_name FROM users WHERE organisation_id = ?", [ctx.org_id])}
        staff = c.all("SELECT u.id, u.full_name, u.email FROM users u LEFT JOIN user_hotels uh ON uh.user_id = u.id AND uh.hotel_id = ? "
                      "WHERE u.organisation_id = ? AND u.status = 'active' AND (u.all_hotels = 1 OR uh.hotel_id IS NOT NULL) ORDER BY u.full_name", [hid, ctx.org_id])
        eligible = []
        for u in staff:
            uc = _user_ctx(c, u["id"])
            if uc and uc.can("reports.view") and uc.can("documents.view"):
                eligible.append({"id": u["id"], "name": u["full_name"], "reports": [k for k in REPORTS if not REPORT_PERMS.get(k) or uc.can(REPORT_PERMS[k])]})
    return {"items": [_sched_view(s, users) for s in rows], "recipients": eligible,
            "reports": [{"code": k, "name": v} for k, v in REPORTS.items() if not REPORT_PERMS.get(k) or ctx.can(REPORT_PERMS[k])]}


@route("POST", "/api/hotels/{hotel_id:int}/report-schedules", perm="bi.schedule", tag="bi",
       summary="Schedule a report (name, report_code, frequency daily|weekly|monthly, weekday 0-6, month_day 1-31, format, recipients [user ids], params)")
def create_schedule(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    from .reports import REPORTS, REPORT_PERMS
    code = ctx.field("report_code", kind=str)
    if code not in REPORTS:
        raise bad_request("Unknown report")
    if REPORT_PERMS.get(code) and not ctx.can(REPORT_PERMS[code]):
        raise forbidden(f"Scheduling this report requires {REPORT_PERMS[code]}")
    freq = ctx.field("frequency", kind=str)
    if freq not in ("daily", "weekly", "monthly"):
        raise bad_request("frequency must be daily, weekly or monthly")
    weekday = ctx.field("weekday", required=freq == "weekly", kind=int)
    month_day = ctx.field("month_day", required=freq == "monthly", kind=int)
    if weekday is not None and not 0 <= weekday <= 6:
        raise bad_request("weekday must be 0 (Monday) to 6 (Sunday)")
    if month_day is not None and not 1 <= month_day <= 31:
        raise bad_request("month_day must be 1 to 31")
    fmt = ctx.field("format", required=False, kind=str) or "pdf"
    if fmt not in ("pdf", "xlsx", "csv"):
        raise bad_request("format must be pdf, xlsx or csv")
    recipients = ctx.field("recipients")
    if not isinstance(recipients, list) or not recipients:
        raise bad_request("Choose at least one recipient")
    params = ctx.field("params", required=False) or {}
    if not isinstance(params, dict):
        raise bad_request("params must be an object")
    with get_db().tx() as c:
        refused = []
        for uid in recipients:
            u = _user_ctx(c, int(uid))
            if not u or u.org_id != ctx.org_id or not _may_receive(u, hid, code):
                refused.append(u.user["full_name"] if u else str(uid))
        if refused:
            raise forbidden(f"These recipients are not allowed to see this report: {', '.join(refused)}")
        sid = c.insert("report_schedules", {"hotel_id": hid, "name": (ctx.field("name", required=False, kind=str) or REPORTS[code])[:150], "report_code": code,
                                            "params": json.dumps(params), "frequency": freq, "weekday": weekday, "month_day": month_day, "format": fmt,
                                            "recipients": json.dumps([int(x) for x in recipients]), "active": 1, "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "report_schedule.created", "report_schedule", sid, code, new={"frequency": freq, "recipients": recipients}, hotel_id=hid)
    return {"id": sid, "_created": True}


@route("PATCH", "/api/report-schedules/{schedule_id:int}", perm="bi.schedule", tag="bi", summary="Pause or resume a schedule ({active})")
def toggle_schedule(ctx: Ctx):
    active = bool(ctx.field("active", kind=bool))
    with get_db().tx() as c:
        s = c.one("SELECT * FROM report_schedules WHERE id = ?", [ctx.path["schedule_id"]])
        if not s:
            raise not_found("Schedule")
        ctx.check_hotel(s["hotel_id"])
        c.update("report_schedules", s["id"], {"active": 1 if active else 0, "last_error": None if active else s["last_error"]})
        audit(c, ctx, "report_schedule.resumed" if active else "report_schedule.paused", "report_schedule", s["id"], s["report_code"], hotel_id=s["hotel_id"])
    return {"ok": True}


@route("POST", "/api/report-schedules/{schedule_id:int}/run", perm="bi.schedule", tag="bi", summary="Run a schedule now (does not change its next due date)")
def run_now(ctx: Ctx):
    with get_db().tx() as c:
        s = c.one("SELECT * FROM report_schedules WHERE id = ?", [ctx.path["schedule_id"]])
        if not s:
            raise not_found("Schedule")
        ctx.check_hotel(s["hotel_id"])
        if not s["active"]:
            raise conflict("Resume the schedule first")
        hotel = get_hotel(c, s["hotel_id"])
        last = s["last_run_on"]
        out = run_schedule(c, s, hotel, business_date(hotel))
        c.update("report_schedules", s["id"], {"last_run_on": last})
    if out["status"] == "failed":
        raise bad_request("The report could not be generated; see the schedule's last error")
    return out
