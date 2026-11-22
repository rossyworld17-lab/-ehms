"""Management assistant (FR-AI-001, FR-AI-005..007).

Answers questions about hotel data through a fixed set of *tools*. Each tool declares the permissions it
needs; a tool is offered and executed only if the signed-in user holds them, and only for hotels the user is
assigned to (tenant boundary). When a question needs data the user may not see, the answer says so.

Two engines share the same tools:
* rule-based (default, no external service): keyword intent matching and template answers;
* Claude (optional): set EHMS_AI_PROVIDER=anthropic and ANTHROPIC_API_KEY, and install the `anthropic`
  package. Claude only sees the tools the user may use and the aggregated figures they return (no guest
  names, contact details or identity data). Sending data to an external AI provider is a data-protection
  decision for the hotel; it is off unless configured.

The assistant never changes data. Requests to approve, refund, cancel, pay, delete, dismiss staff and so on
are answered with where to do it in the normal (approval-controlled) workflow (FR-AI-007).
Every question is logged in ai_interactions with the tools used and any permission refusals."""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import re
import statistics

from ..db import get_db, now_iso
from ..http import Ctx, bad_request, route
from ..services import business_date, get_hotel

log = logging.getLogger("ehms.assistant")
MODEL = os.environ.get("EHMS_AI_MODEL", "claude-opus-5-5")


def fm(v: int | None, cur: str) -> str:
    return f"{cur} {((v or 0) / 100):,.2f}"


def parse_period(text: str, today: dt.date) -> tuple[dt.date, dt.date, str]:
    t = text.lower()
    if "yesterday" in t:
        d = today - dt.timedelta(days=1)
        return d, d, "yesterday"
    if "last month" in t:
        end = today.replace(day=1) - dt.timedelta(days=1)
        return end.replace(day=1), end, "last month"
    if "last week" in t or "past week" in t or "last 7 days" in t:
        return today - dt.timedelta(days=7), today - dt.timedelta(days=1), "the last 7 days"
    if "last 30 days" in t or "past month" in t:
        return today - dt.timedelta(days=30), today - dt.timedelta(days=1), "the last 30 days"
    if "this year" in t or "ytd" in t or "year to date" in t:
        return today.replace(month=1, day=1), today, "this year to date"
    if "this month" in t or "mtd" in t or "month to date" in t or "month" in t:
        return today.replace(day=1), today, "this month to date"
    if "this week" in t or "week" in t:
        return today - dt.timedelta(days=today.weekday()), today, "this week to date"
    return today, today, "today"


# ------------------------------------------------------------------ tools
class Tool:
    def __init__(self, name, description, perms, fn, params=None, keywords=(), any_of=False):
        self.name, self.description, self.perms, self.fn, self.params, self.keywords, self.any_of = name, description, perms, fn, params or {}, keywords, any_of

    def allowed(self, ctx: Ctx) -> bool:
        return (any if self.any_of else all)(ctx.can(p) for p in self.perms)

    def schema(self) -> dict:
        return {"name": self.name, "description": self.description,
                "input_schema": {"type": "object", "properties": self.params, "required": [], "additionalProperties": False}}


def t_occupancy(c, ctx, hotel, args):
    from .dashboard import kpis_for
    today = business_date(hotel)
    k = kpis_for(c, hotel["id"], today)
    arr = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND arrival = ? AND status IN ('confirmed','tentative')", [hotel["id"], today.isoformat()])
    dep = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND departure <= ? AND status = 'checked_in'", [hotel["id"], today.isoformat()])
    inh = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status = 'checked_in'", [hotel["id"]])
    return {"summary": f"Tonight ({today}) {k['rooms_sold']} of {k['sellable_rooms']} sellable rooms are occupied ({k['occupancy_pct']}%). "
                       f"{arr} arrival(s) still expected, {dep} departure(s) still to check out, {inh} reservation(s) in house; "
                       f"{k['out_of_service']} room(s) out of service.",
            "data": {"date": today.isoformat(), "occupancy_pct": k["occupancy_pct"], "rooms_sold": k["rooms_sold"], "sellable_rooms": k["sellable_rooms"],
                     "arrivals_pending": arr, "departures_pending": dep, "in_house_reservations": inh, "out_of_service": k["out_of_service"]}}


def t_revenue(c, ctx, hotel, args):
    today = business_date(hotel)
    if args.get("from") and args.get("to"):
        a, b, label = dt.date.fromisoformat(args["from"]), dt.date.fromisoformat(args["to"]), f"{args['from']} to {args['to']}"
    else:
        a, b, label = parse_period(args.get("period", "today"), today)
    cur = hotel["currency"]
    rows = c.all("SELECT COALESCE(jl.department,'other') AS dept, SUM(jl.credit) - SUM(jl.debit) AS amt FROM journal_lines jl JOIN journal_entries je ON je.id = jl.entry_id "
                 "JOIN accounts ac ON ac.id = jl.account_id WHERE je.hotel_id = ? AND ac.type = 'revenue' AND je.entry_date >= ? AND je.entry_date <= ? "
                 "GROUP BY COALESCE(jl.department,'other')", [hotel["id"], a.isoformat(), b.isoformat()])
    total = sum(r["amt"] for r in rows)
    room = sum(r["amt"] for r in rows if r["dept"] == "room")
    nights = c.scalar("SELECT COUNT(*) FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? AND fl.department = 'room' AND fl.kind = 'charge' "
                      "AND fl.reference LIKE ? AND fl.business_date >= ? AND fl.business_date <= ?", [hotel["id"], "ROOM:%", a.isoformat(), b.isoformat()]) or 0
    parts = ", ".join(f"{r['dept']} {fm(r['amt'], cur)}" for r in sorted(rows, key=lambda r: -r["amt"]) if r["amt"])
    return {"summary": f"Revenue for {label} ({a} to {b}), from the general ledger: {fm(total, cur)}" + (f" — {parts}." if parts else ".")
                       + (f" Room revenue {fm(room, cur)} over {nights} room night(s), ADR {fm(room // nights if nights else 0, cur)}." if nights else ""),
            "data": {"from": a.isoformat(), "to": b.isoformat(), "total": fm(total, cur), "by_department": {r["dept"]: fm(r["amt"], cur) for r in rows},
                     "room_nights_posted": nights, "adr": fm(room // nights if nights else 0, cur), "source": "posted journal entries"}}


def t_forecast(c, ctx, hotel, args):
    from .insights import forecast
    days = max(1, min(60, int(args.get("days") or 7)))
    f = forecast(c, hotel, days)
    avg = statistics.mean(d["expected_occupancy_pct"] for d in f["days"]) if f["days"] else 0
    peak = max(f["days"], key=lambda d: d["expected_occupancy_pct"]) if f["days"] else None
    s = (f"Forecast for the next {days} day(s): average expected occupancy {avg:.1f}% ({f['totals']['on_books']} room nights already booked, "
         f"{f['totals']['expected_room_nights']} expected).")
    if peak:
        s += f" Busiest night {peak['date']} at about {peak['expected_occupancy_pct']}% (range {peak['low']}–{peak['high']} rooms)."
    s += f" Method: {f['explanation']}"
    data = {"method": f["method"], "days": [{k: d[k] for k in ("date", "on_books", "expected_rooms", "low", "high", "expected_occupancy_pct")} for d in f["days"]],
            "limitations": f["limitations"]}
    return {"summary": s, "data": data}


def t_balances(c, ctx, hotel, args):
    cur = hotel["currency"]
    rows = c.all("SELECT f.number, f.status, SUM(CASE WHEN fl.kind IN ('charge','adjustment','refund') THEN fl.total_amount ELSE -fl.total_amount END) AS bal "
                 "FROM folios f JOIN folio_lines fl ON fl.folio_id = f.id WHERE f.hotel_id = ? AND f.status = 'open' GROUP BY f.number, f.status", [hotel["id"]])
    rows = [r for r in rows if r["bal"] > 0]
    total = sum(r["bal"] for r in rows)
    ap = c.one("SELECT COUNT(*) AS n, COALESCE(SUM(amount - amount_paid),0) AS v FROM supplier_invoices WHERE hotel_id = ? AND status IN ('approved','part_paid')", [hotel["id"]])
    top = sorted(rows, key=lambda r: -r["bal"])[:5]
    return {"summary": f"{len(rows)} open folio(s) owe {fm(total, cur)} in total" + (f"; largest: " + ", ".join(f"{r['number']} {fm(r['bal'], cur)}" for r in top) if top else "")
                       + f". Supplier payables: {ap['n']} invoice(s), {fm(ap['v'], cur)} outstanding.",
            "data": {"guest_receivables": fm(total, cur), "open_folios_owing": len(rows), "largest": [{"folio": r["number"], "balance": fm(r["bal"], cur)} for r in top],
                     "supplier_payables": fm(ap["v"], cur), "supplier_invoices_open": ap["n"]}}


def t_stock(c, ctx, hotel, args):
    from .insights import reorder_recommendations
    recs = reorder_recommendations(c, hotel)
    urgent = [r for r in recs if r["urgency"] == "high"]
    s = f"{len(recs)} item(s) should be reordered" + (f", {len(urgent)} urgently" if urgent else "") + "."
    if recs:
        s += " " + "; ".join(f"{r['name']}: {r['on_hand']:g} {r['unit']} on hand, suggest {r['suggested_qty']:g}" + (f" ({r['days_cover']} days' cover)" if r["days_cover"] is not None else "") for r in recs[:6])
        s += ". You can create a requisition from Insights → Recommendations; it follows the normal approval."
    return {"summary": s, "data": {"items": recs[:15]}}


def t_approvals(c, ctx, hotel, args):
    hid = hotel["id"]
    counts = {
        "refunds/adjustments": c.scalar("SELECT COUNT(*) FROM approvals WHERE hotel_id = ? AND status = 'pending'", [hid]),
        "purchase requisitions": c.scalar("SELECT COUNT(*) FROM purchase_requisitions WHERE hotel_id = ? AND status = 'submitted'", [hid]),
        "purchase orders": c.scalar("SELECT COUNT(*) FROM purchase_orders WHERE hotel_id = ? AND status = 'pending_approval'", [hid]),
        "supplier invoices": c.scalar("SELECT COUNT(*) FROM supplier_invoices WHERE hotel_id = ? AND status = 'pending_approval'", [hid]),
        "expense claims": c.scalar("SELECT COUNT(*) FROM expense_claims WHERE hotel_id = ? AND status = 'submitted'", [hid]),
        "leave requests": c.scalar("SELECT COUNT(*) FROM leave_requests l JOIN employees e ON e.id = l.employee_id WHERE e.hotel_id = ? AND l.status = 'pending'", [hid]),
        "pricing rules": c.scalar("SELECT COUNT(*) FROM rate_rules WHERE hotel_id = ? AND status = 'pending_approval'", [hid]),
    }
    waiting = {k: v for k, v in counts.items() if v}
    return {"summary": ("Waiting for approval: " + ", ".join(f"{v} {k}" for k, v in waiting.items()) + ". Open the Approvals page (or the module) to decide."
                        if waiting else "Nothing is waiting for approval."), "data": counts}


def t_complaints(c, ctx, hotel, args):
    hid = hotel["id"]
    rows = c.all("SELECT category, severity, status, due_at FROM complaints WHERE hotel_id = ? AND status NOT IN ('resolved','closed')", [hid])
    now = now_iso()
    overdue = sum(1 for r in rows if r["due_at"] and r["due_at"] < now)
    cats: dict[str, int] = {}
    for r in rows:
        cats[r["category"]] = cats.get(r["category"], 0) + 1
    return {"summary": f"{len(rows)} open complaint(s), {overdue} past their deadline" + (". By category: " + ", ".join(f"{k} {v}" for k, v in sorted(cats.items(), key=lambda x: -x[1])) if cats else "") + ".",
            "data": {"open": len(rows), "overdue": overdue, "by_category": cats}}


def t_feedback(c, ctx, hotel, args):
    since = (business_date(hotel) - dt.timedelta(days=int(args.get("days") or 90))).isoformat()
    fb = c.all("SELECT overall, nps, sentiment, themes, comments FROM feedback WHERE hotel_id = ? AND submitted_at >= ?", [hotel["id"], since])
    if not fb:
        return {"summary": "No guest feedback was received in that period.", "data": {}}
    themes: dict[str, list[int]] = {}
    for f in fb:
        for name in [x.strip() for x in (f["themes"] or "").split(",") if x.strip()]:
            themes.setdefault(name, []).append(1 if f["sentiment"] == "negative" else 0)
    issues = sorted(((k, sum(v), len(v)) for k, v in themes.items()), key=lambda x: (-x[1], -x[2]))
    ratings = [f["overall"] for f in fb if f["overall"]]
    npsv = [f["nps"] for f in fb if f["nps"] is not None]
    nps = round((sum(1 for n in npsv if n >= 9) - sum(1 for n in npsv if n <= 6)) * 100 / len(npsv)) if npsv else None
    neg = [f["comments"] for f in fb if f["sentiment"] == "negative" and f["comments"]][:3]
    s = f"{len(fb)} response(s) in the last {args.get('days') or 90} days, average rating {statistics.mean(ratings):.1f}/5" if ratings else f"{len(fb)} response(s)"
    s += f", NPS {nps}." if nps is not None else "."
    if issues and issues[0][1]:
        s += " Recurring issues: " + ", ".join(f"{k} ({n} negative of {t})" for k, n, t in issues[:4] if n) + "."
    if neg:
        s += " Example comments: " + " | ".join(f"“{x[:140]}”" for x in neg)
    return {"summary": s, "data": {"responses": len(fb), "nps": nps, "themes": [{"theme": k, "negative": n, "mentions": t} for k, n, t in issues],
                                    "note": "Themes come from keyword analysis of comments; read comments before acting."}}


def t_staff(c, ctx, hotel, args):
    today = business_date(hotel).isoformat()
    leave = c.all("SELECT e.department, COUNT(*) AS n FROM leave_requests l JOIN employees e ON e.id = l.employee_id WHERE e.hotel_id = ? AND l.status = 'approved' "
                  "AND l.start_date <= ? AND l.end_date >= ? GROUP BY e.department", [hotel["id"], today, today])
    att = {r["status"]: r["n"] for r in c.all("SELECT a.status, COUNT(*) AS n FROM attendance a JOIN employees e ON e.id = a.employee_id WHERE e.hotel_id = ? "
                                              "AND a.work_date = ? GROUP BY a.status", [hotel["id"], today])}
    head = c.scalar("SELECT COUNT(*) FROM employees WHERE hotel_id = ? AND status = 'active'", [hotel["id"]])
    on_leave = sum(r["n"] for r in leave)
    return {"summary": f"{head} active employee(s); {on_leave} on approved leave today" + (" (" + ", ".join(f"{r['department']} {r['n']}" for r in leave) + ")" if leave else "")
                       + f". Attendance recorded today: {att.get('present', 0)} present, {att.get('late', 0)} late, {att.get('absent', 0)} absent.",
            "data": {"headcount": head, "on_leave_today": on_leave, "attendance_today": att}}


def t_menu(c, ctx, hotel, args):
    today = business_date(hotel)
    a, b, label = parse_period(args.get("period", "this month"), today)
    rows = c.all("SELECT i.name, SUM(i.quantity) AS qty, SUM(i.quantity * i.unit_price) AS gross FROM pos_order_items i JOIN pos_orders o ON o.id = i.order_id "
                 "WHERE o.hotel_id = ? AND o.status = 'settled' AND i.kitchen_status <> 'void' AND o.business_date >= ? AND o.business_date <= ? "
                 "GROUP BY i.name ORDER BY gross DESC", [hotel["id"], a.isoformat(), b.isoformat()])
    cur = hotel["currency"]
    return {"summary": (f"Best sellers for {label}: " + ", ".join(f"{r['name']} ({int(r['qty'])} sold, {fm(r['gross'], cur)})" for r in rows[:5]) + "."
                        if rows else f"No settled restaurant or bar sales for {label}."),
            "data": {"items": [{"name": r["name"], "quantity": int(r["qty"]), "gross": fm(r["gross"], cur)} for r in rows[:10]]}}


def t_anomalies(c, ctx, hotel, args):
    rows = c.all("SELECT title, severity FROM anomaly_flags WHERE hotel_id = ? AND status IN ('open','reviewing') ORDER BY id DESC", [hotel["id"]])
    high = sum(1 for r in rows if r["severity"] == "high")
    return {"summary": (f"{len(rows)} unusual transaction(s) are waiting for review ({high} high priority): " + "; ".join(r["title"] for r in rows[:5])
                        + ". These are prompts for a human check, not findings." if rows else "No unusual transactions are waiting for review."),
            "data": {"open": len(rows), "high": high, "latest": [r["title"] for r in rows[:10]]}}


def t_rates(c, ctx, hotel, args):
    from .insights import rate_recommendations
    recs = rate_recommendations(c, hotel)
    if not recs:
        return {"summary": "No rate changes are suggested for the next three weeks; expected demand is in the normal range.", "data": {}}
    return {"summary": f"{len(recs)} night(s) have a suggested rate change: " + "; ".join(f"{r['date']} {r['suggested_change_pct']:+d}% ({r['reason']})" for r in recs[:5])
                       + ". These are suggestions; a pricing rule needs approval by a second person, and booked guests keep their price.",
            "data": {"items": recs}}


def t_housekeeping(c, ctx, hotel, args):
    rooms = c.all("SELECT occupancy, hk_status, service_status FROM rooms WHERE hotel_id = ? AND active = 1", [hotel["id"]])
    dirty = sum(1 for r in rooms if r["hk_status"] in ("dirty", "in_progress"))
    insp = sum(1 for r in rooms if r["hk_status"] == "clean")
    ready = sum(1 for r in rooms if r["occupancy"] == "vacant" and r["hk_status"] == "inspected" and r["service_status"] in ("in_service", "vip_hold"))
    return {"summary": f"{ready} vacant room(s) ready to sell, {dirty} dirty or being cleaned, {insp} cleaned and awaiting inspection.",
            "data": {"vacant_ready": ready, "dirty": dirty, "awaiting_inspection": insp}}


def t_maintenance(c, ctx, hotel, args):
    rows = c.all("SELECT priority, status, blocks_room FROM work_orders WHERE hotel_id = ? AND status NOT IN ('verified','cancelled')", [hotel["id"]])
    urgent = sum(1 for r in rows if r["priority"] in ("urgent", "high"))
    blocked = sum(1 for r in rows if r["blocks_room"])
    return {"summary": f"{len(rows)} open work order(s), {urgent} urgent/high priority, {blocked} keeping a room out of sale.",
            "data": {"open": len(rows), "urgent_or_high": urgent, "blocking_rooms": blocked}}


PERIOD = {"period": {"type": "string", "description": "today, yesterday, this week, last week, this month, last month, this year"},
          "from": {"type": "string", "description": "YYYY-MM-DD (optional, with 'to')"}, "to": {"type": "string", "description": "YYYY-MM-DD"}}
TOOLS = [
    Tool("occupancy_today", "Tonight's occupancy, pending arrivals/departures and rooms out of service.", ["dashboard.view"], t_occupancy, {},
         ("occupan", "arrival", "departure", "in house", "in-house", "how full", "tonight", "rooms sold", "how busy")),
    Tool("revenue_summary", "Revenue by department from the general ledger for a period, with room nights and ADR.", ["reports.financial"], t_revenue, PERIOD,
         ("revenue", "income", "sales", "earn", "takings", "adr", "made")),
    Tool("occupancy_forecast", "Forecast occupancy for the next N days with method and range.", ["bi.view"], t_forecast,
         {"days": {"type": "integer", "description": "1-60, default 7"}}, ("forecast", "next week", "next month", "coming", "expect", "predict", "upcoming", "outlook")),
    Tool("outstanding_balances", "Guest balances owed on open folios and supplier payables.", ["reports.financial"], t_balances, {},
         ("outstanding", "owe", "balance", "debtor", "receivable", "payable", "unpaid")),
    Tool("stock_reorder", "Items that should be reordered, with usage, cover and suggested quantities.", ["inventory.view"], t_stock, {},
         ("stock", "inventory", "reorder", "running out", "low on", "store")),
    Tool("pending_approvals", "Items waiting for approval across modules.", ["approvals.view"], t_approvals, {}, ("approv", "pending", "waiting for", "sign off")),
    Tool("complaints_summary", "Open complaints, overdue ones and categories.", ["crm.view"], t_complaints, {}, ("complain", "escalat")),
    Tool("feedback_summary", "Guest ratings, NPS and recurring service issues from feedback.", ["crm.view"], t_feedback,
         {"days": {"type": "integer", "description": "look-back in days, default 90"}}, ("feedback", "review", "rating", "satisf", "nps", "guests say", "recurring", "issues")),
    Tool("staff_today", "Headcount, staff on leave and attendance today.", ["hr.view"], t_staff, {}, ("staff", "leave", "attendance", "absent", "employee", "on duty")),
    Tool("menu_best_sellers", "Best-selling restaurant and bar items for a period.", ["pos.view", "reports.view"], t_menu, {"period": PERIOD["period"]},
         ("menu", "best sell", "best-sell", "dish", "food", "drink", "restaurant", "bar")),
    Tool("anomalies_summary", "Unusual transactions waiting for human review.", ["ai.anomalies.view"], t_anomalies, {}, ("unusual", "anomal", "fraud", "suspicious", "irregular")),
    Tool("rate_suggestions", "Suggested room-rate changes from forecast demand and competitor rates.", ["sales.view"], t_rates, {}, ("rate", "price", "pricing", "competitor")),
    Tool("housekeeping_status", "Rooms ready, dirty and awaiting inspection.", ["housekeeping.view"], t_housekeeping, {}, ("housekeep", "dirty", "clean", "inspect", "ready")),
    Tool("maintenance_open", "Open maintenance work orders and rooms out of order.", ["maintenance.view"], t_maintenance, {}, ("maintenance", "repair", "work order", "broken", "fault")),
]
BY_NAME = {t.name: t for t in TOOLS}

ACTIONS = re.compile(r"\b(approve|reject|refund|cancel|void|delete|remove|pay|transfer|terminate|dismiss|fire|sack|suspend|change (the )?rate|set (the )?rate|"
                     r"discount|write[- ]?off|post (a )?journal|adjust|book (a )?room|check (him|her|them|guest)? ?(in|out))\b", re.I)
ACTION_HELP = ("I can't make changes — I only read data you are allowed to see. Decisions such as approvals, refunds, cancellations, payments, rate "
               "changes and staff matters need a person to act in the relevant screen, where the usual approval rules (maker-checker) apply. ")


def run_tool(c, ctx: Ctx, hotel: dict, name: str, args: dict) -> dict:
    t = BY_NAME.get(name)
    if not t:
        return {"error": f"unknown tool {name}"}
    if not t.allowed(ctx):
        return {"error": f"permission denied: needs {' or '.join(t.perms) if t.any_of else ', '.join(t.perms)}"}
    try:
        return t.fn(c, ctx, hotel, args or {})
    except (ValueError, TypeError) as e:
        return {"error": f"invalid arguments: {e}"}


def rule_based(c, ctx: Ctx, hotel: dict, question: str) -> dict:
    q = question.lower()
    matched = [t for t in TOOLS if any(k in q for k in t.keywords)]
    # prefer the forecast over today's occupancy when the question looks ahead
    if any(t.name == "occupancy_forecast" for t in matched):
        matched = [t for t in matched if t.name != "occupancy_today"]
    used, denied, parts = [], [], []
    if ACTIONS.search(q):
        parts.append(ACTION_HELP)
    for t in matched[:3]:
        if not t.allowed(ctx):
            denied.append({"topic": t.description, "needs": t.perms})
            continue
        args = {"period": question}
        if t.name in ("occupancy_forecast",):
            m = re.search(r"(\d+)\s*day", q)
            args = {"days": int(m.group(1)) if m else (30 if "month" in q else 7)}
        res = t.fn(c, ctx, hotel, args)
        used.append(t.name)
        parts.append(res["summary"])
    for d in denied:
        parts.append(f"I can't answer about “{d['topic'].rstrip('.')}” — your role does not include {', '.join(d['needs'])}.")
    if not parts:
        topics = [t.description.rstrip(".") for t in TOOLS if t.allowed(ctx)]
        parts.append("I didn't recognise that question. You can ask me about: " + "; ".join(topics) + "." if topics
                     else "Your role does not give access to any of the data I can report on.")
    return {"answer": "\n\n".join(parts), "tools": used, "denied": denied}


def _claude_client():  # pragma: no cover - replaced in tests
    import anthropic
    return anthropic.Anthropic()


def claude_enabled() -> bool:
    if os.environ.get("EHMS_AI_PROVIDER", "").lower() != "anthropic" or not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
        return True
    except ImportError:
        return False


def claude_answer(c, ctx: Ctx, hotel: dict, question: str, client_factory=None) -> dict:
    """Tool-use loop. Only tools the user may use are offered; each call is re-checked when executed."""
    allowed = [t for t in TOOLS if t.allowed(ctx)]
    hidden = [t.description.rstrip(".") for t in TOOLS if not t.allowed(ctx)]
    system = (f"You are the management assistant of {hotel['name']} (hotel management system EHMS). Today's business date is {business_date(hotel)}; "
              f"amounts are in {hotel['currency']}. Answer only from the results of your tools; if they do not contain the answer, say so. "
              "Be concise and concrete. You cannot change anything: if asked to approve, refund, cancel, pay, change rates, discipline staff or make any other "
              "decision, explain that a person must do it in the relevant screen under the normal approval rules. When you give a forecast or "
              "recommendation, state the method and its limitations briefly. "
              + (f"The user's role does not give access to: {'; '.join(hidden)}. If asked about these, say that their role does not include that data." if hidden else ""))
    client = (client_factory or _claude_client)()
    messages = [{"role": "user", "content": question}]
    used: list[str] = []
    for _ in range(6):
        resp = client.beta.messages.create(model=MODEL, max_tokens=4000, system=system, tools=[t.schema() for t in allowed], messages=messages,
                                           betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        if resp.stop_reason == "refusal":
            raise RuntimeError("model declined")
        if resp.stop_reason != "tool_use":
            text = "".join(b.text for b in resp.content if b.type == "text").strip()
            return {"answer": text or "I could not produce an answer.", "tools": used, "denied": []}
        messages.append({"role": "assistant", "content": resp.content})
        results = []
        for b in resp.content:
            if b.type == "tool_use":
                used.append(b.name)
                out = run_tool(c, ctx, hotel, b.name, b.input if isinstance(b.input, dict) else {})
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": json.dumps(out.get("data", out), default=str)[:20000],
                                **({"is_error": True} if "error" in out else {})})
        messages.append({"role": "user", "content": results})
    return {"answer": "I needed too many steps to answer that; please ask a narrower question.", "tools": used, "denied": []}


@route("GET", "/api/assistant/status", perm="ai.assistant", tag="ai", summary="Which engine answers and what the user may ask about")
def status(ctx: Ctx):
    return {"engine": "claude" if claude_enabled() else "rules", "model": MODEL if claude_enabled() else None,
            "topics": [{"name": t.name, "description": t.description} for t in TOOLS if t.allowed(ctx)],
            "unavailable": [{"description": t.description, "needs": t.perms} for t in TOOLS if not t.allowed(ctx)],
            "examples": ["How full are we tonight?", "What was revenue yesterday?", "Forecast for the next 14 days", "What do guests complain about?",
                         "What needs reordering?", "What is waiting for my approval?"]}


@route("POST", "/api/assistant/ask", perm="ai.assistant", tag="ai", summary="Ask a question ({question, hotel_id}); answers use only data you are permitted to see")
def ask(ctx: Ctx):
    question = ctx.field("question", kind=str)
    if len(question) > 1000:
        raise bad_request("Please keep questions under 1,000 characters")
    hid = ctx.check_hotel(ctx.field("hotel_id", kind=int))
    engine = "rules"
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        result = None
        if claude_enabled():
            try:
                result = claude_answer(c, ctx, hotel, question)
                engine = "claude"
            except Exception:
                log.exception("assistant: AI provider failed; using rule-based answer")
        if result is None:
            result = rule_based(c, ctx, hotel, question)
            if claude_enabled():
                result["answer"] += "\n\n(The AI service was unavailable, so this is the built-in answer.)"
        c.insert("ai_interactions", {"hotel_id": hid, "user_id": ctx.user_id, "question": question, "intents": json.dumps(result["tools"]), "engine": engine,
                                     "denied": json.dumps(result["denied"]) if result["denied"] else None, "answer": result["answer"][:4000], "created_at": now_iso()})
    return {"answer": result["answer"], "engine": engine, "tools_used": result["tools"], "denied": result["denied"],
            "disclaimer": "Generated from EHMS data you are permitted to see. Check figures in the source reports before acting on them."}


@route("GET", "/api/hotels/{hotel_id:int}/assistant/log", perm="admin.audit.view", tag="ai", summary="Assistant questions asked (audit)")
def interaction_log(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        rows = c.all("SELECT a.created_at, u.full_name, a.question, a.intents, a.engine, a.denied FROM ai_interactions a JOIN users u ON u.id = a.user_id "
                     "WHERE a.hotel_id = ? ORDER BY a.id DESC LIMIT 200", [hid])
    return {"items": [dict(r) for r in rows]}
