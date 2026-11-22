"""Explainable analytics (FR-AI-002..007): demand forecasting, unusual-transaction detection for human review,
and rate / reorder recommendations.

Every result states its method, the data it used and its limitations (FR-AI-006). Nothing here changes data
on its own (FR-AI-007): anomalies are flags that a person reviews; a rate recommendation can be turned into a
*proposed* pricing rule that still needs a second person's approval; a reorder recommendation only pre-fills
a purchase requisition, which goes through the normal procurement approval."""
from __future__ import annotations

import datetime as dt
import json
import math
import statistics
from collections import defaultdict

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import business_date, get_hotel, hotel_setting

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None


def _d(s) -> dt.date:
    return dt.date.fromisoformat(str(s)[:10])


# ------------------------------------------------------------------ forecasting
def forecast(c, hotel: dict, days: int = 30) -> dict:
    """On-the-books plus expected pickup by lead time, learned from the last 120 days of booking history.
    Falls back to same-weekday average occupancy when there is too little history."""
    hid = hotel["id"]
    today = business_date(hotel)
    rooms = c.scalar("SELECT COUNT(*) FROM rooms WHERE hotel_id = ? AND active = 1", [hid]) or 0
    hist_from = today - dt.timedelta(days=120)
    res = c.all("SELECT arrival, departure, status, created_at, cancelled_at, nightly_rate FROM reservations WHERE hotel_id = ? AND departure > ? "
                "AND status NOT IN ('enquiry','waitlisted')", [hid, hist_from.isoformat()])

    def on_books(day: dt.date, as_of: dt.date) -> int:
        n = 0
        for r in res:
            if not (_d(r["arrival"]) <= day < _d(r["departure"])):
                continue
            if _d(r["created_at"]) > as_of:
                continue
            if r["cancelled_at"] and _d(r["cancelled_at"]) <= as_of:
                continue
            if r["status"] == "no_show" and day < today:
                continue
            n += 1
        return n

    def actual(day: dt.date) -> int:
        return sum(1 for r in res if r["status"] in ("checked_in", "checked_out") and _d(r["arrival"]) <= day < _d(r["departure"]))

    hist_days = [today - dt.timedelta(days=i) for i in range(1, 121)]
    finals = {h: actual(h) for h in hist_days}
    usable = [h for h in hist_days if finals[h] > 0]
    pickup: dict[int, list[int]] = defaultdict(list)
    for h in usable:
        for k in (0, 1, 3, 7, 14, 21, 30, 45, 60):
            pickup[k].append(finals[h] - on_books(h, h - dt.timedelta(days=k)))
    dow: dict[int, list[float]] = defaultdict(list)
    for h in hist_days[:56]:
        if rooms:
            dow[h.weekday()].append(finals[h] * 100 / rooms)
    method = "pickup" if len(usable) >= 21 else "weekday_average"
    trailing = c.one("SELECT COALESCE(SUM(fl.net_amount),0) AS rev FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? "
                     "AND fl.department = 'room' AND fl.kind IN ('charge','adjustment') AND fl.business_date >= ? AND fl.business_date < ?",
                     [hid, (today - dt.timedelta(days=30)).isoformat(), today.isoformat()])["rev"]
    trailing_nights = sum(finals[h] for h in hist_days[:30])
    trailing_adr = trailing // trailing_nights if trailing_nights else 0

    def lead_bucket(k: int) -> int:
        return max(b for b in (0, 1, 3, 7, 14, 21, 30, 45, 60) if b <= k) if k >= 0 else 0

    out = []
    for i in range(days):
        day = today + dt.timedelta(days=i)
        ob = on_books(day, today)
        if method == "pickup":
            samples = pickup.get(lead_bucket(i), [])
            mean = statistics.mean(samples) if samples else 0
            sd = statistics.pstdev(samples) if len(samples) > 1 else 0
            exp = ob + max(0.0, mean)
        else:
            vals = dow.get(day.weekday(), [])
            avg = statistics.mean(vals) * rooms / 100 if vals else 0
            sd = statistics.pstdev(vals) * rooms / 100 if len(vals) > 1 else 0
            exp = max(ob, avg)
        exp = min(float(rooms), exp)
        low = max(ob, int(math.floor(exp - sd)))
        high = min(rooms, int(math.ceil(exp + sd)))
        books_adr = [r["nightly_rate"] for r in res if r["status"] in ("confirmed", "tentative", "checked_in") and _d(r["arrival"]) <= day < _d(r["departure"])]
        adr = int(statistics.mean(books_adr)) if books_adr else trailing_adr
        out.append({"date": day.isoformat(), "on_books": ob, "expected_rooms": round(exp, 1), "low": low, "high": high,
                    "expected_occupancy_pct": round(exp * 100 / rooms, 1) if rooms else 0.0, "expected_room_revenue": int(round(exp)) * adr, "adr_used": adr})
    return {
        "hotel_id": hid, "generated_for": today.isoformat(), "rooms": rooms, "method": method,
        "explanation": ("Rooms already booked for each night plus the extra bookings this hotel usually receives between that many days "
                        "before arrival and the night itself (average over the last 120 days; the range is ± one standard deviation)."
                        if method == "pickup" else
                        "Not enough booking history yet for a pickup model, so each night uses the higher of rooms already booked and the "
                        "average occupancy for the same weekday over the last 8 weeks."),
        "limitations": ["Events, holidays and promotions that did not happen in the history window are not anticipated.",
                        "Revenue uses the average rate on the books for that night, or the last 30 days' ADR.",
                        f"History used: {len(usable)} nights with stays in the last 120 days."],
        "days": out,
        "totals": {"expected_room_nights": round(sum(d["expected_rooms"] for d in out), 1), "on_books": sum(d["on_books"] for d in out),
                   "expected_room_revenue": sum(d["expected_room_revenue"] for d in out)},
    }


@route("GET", "/api/hotels/{hotel_id:int}/insights/forecast", perm="bi.view", tag="ai", summary="Explainable occupancy and room-revenue forecast (?days=30, max 90)")
def forecast_ep(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    days = min(90, max(1, int(ctx.q("days", 30))))
    with get_db().tx() as c:
        out = forecast(c, get_hotel(c, hid), days)
    if not ctx.can("reports.financial"):
        for d in out["days"]:
            d.pop("expected_room_revenue")
            d.pop("adr_used")
        out["totals"].pop("expected_room_revenue")
    return out


# ------------------------------------------------------------------ anomaly detection
def _flag(c, hid: int, rule: str, severity: str, title: str, explanation: str, fingerprint: str, *, entity_type=None, entity_id=None,
          business_date=None, amount=None, user_id=None) -> bool:
    if c.one("SELECT id FROM anomaly_flags WHERE hotel_id = ? AND fingerprint = ?", [hid, fingerprint]):
        return False
    c.insert("anomaly_flags", {"hotel_id": hid, "rule": rule, "severity": severity, "title": title[:250], "explanation": explanation,
                               "fingerprint": fingerprint[:120], "entity_type": entity_type, "entity_id": entity_id, "business_date": business_date,
                               "amount": amount, "user_id": user_id, "created_at": now_iso()})
    return True


def _local_hour(ts: str, tz: str) -> int:
    t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if ZoneInfo:
        try:
            t = t.astimezone(ZoneInfo(tz))
        except Exception:  # pragma: no cover
            pass
    return t.hour


RULES = {
    "large_refund": "Refund far larger than usual for this hotel",
    "refund_ratio": "Refunds by one person well above their colleagues",
    "after_hours_cash": "Cash payment or refund recorded between midnight and 5 a.m.",
    "pos_void_rate": "POS items voided by one person far more often than by colleagues",
    "pos_discount": "POS discount above 25 % of the bill",
    "folio_allowance": "Large folio allowance (credit) relative to the folio",
    "rate_override_pattern": "Repeated manual room-rate overrides by one person",
    "duplicate_supplier_invoice": "Supplier invoices with the same amount close together",
    "manual_cash_journal": "Manual journal entry moving cash or bank",
}


def scan(c, hotel: dict, days: int = 7) -> list[int]:
    """Run every rule over the last `days` business days; returns the ids of new flags (existing ones are not repeated)."""
    hid, cur, tz = hotel["id"], hotel["currency"], hotel.get("timezone") or "Africa/Lagos"
    today = business_date(hotel)
    since = (today - dt.timedelta(days=days)).isoformat()
    base_from = (today - dt.timedelta(days=90)).isoformat()
    before = c.scalar("SELECT COALESCE(MAX(id),0) FROM anomaly_flags WHERE hotel_id = ?", [hid])
    money = lambda v: f"{cur} {v / 100:,.2f}"  # noqa: E731
    names = {u["id"]: u["full_name"] for u in c.all("SELECT id, full_name FROM users WHERE organisation_id = ?", [hotel["organisation_id"]])}

    # 1. refunds much larger than the usual payment size
    pays = [r["amount"] for r in c.all("SELECT amount FROM payments WHERE hotel_id = ? AND kind = 'payment' AND status = 'completed' AND created_at >= ?", [hid, base_from])]
    threshold = max(5_000_000, int(statistics.mean(pays) + 3 * statistics.pstdev(pays))) if len(pays) >= 5 else 5_000_000
    for r in c.all("SELECT p.*, f.number FROM payments p JOIN folios f ON f.id = p.folio_id WHERE p.hotel_id = ? AND p.kind = 'refund' AND p.status = 'completed' "
                   "AND p.created_at >= ?", [hid, since]):
        if r["amount"] >= threshold:
            _flag(c, hid, "large_refund", "high", f"Refund of {money(r['amount'])} on {r['number']}",
                  f"The refund is above the review threshold of {money(threshold)} (the larger of {money(5_000_000)} and the average payment of the last "
                  f"90 days plus three standard deviations). Check the approval and the reason.", f"large_refund:{r['id']}",
                  entity_type="folio", entity_id=r["folio_id"], business_date=str(r["created_at"])[:10], amount=r["amount"], user_id=r["received_by"])
        if r["method_id"] and _local_hour(r["created_at"], tz) < 5:
            m = c.one("SELECT kind FROM payment_methods WHERE id = ?", [r["method_id"]])
            if m and m["kind"] == "cash":
                _flag(c, hid, "after_hours_cash", "medium", f"Cash refund at night on {r['number']} ({money(r['amount'])})",
                      "A cash refund was recorded between midnight and 5 a.m. hotel time, when fewer staff are on duty.", f"after_hours_cash:{r['id']}",
                      entity_type="folio", entity_id=r["folio_id"], amount=r["amount"], user_id=r["received_by"])
    # 2. refund share per user vs colleagues
    by_user = c.all("SELECT received_by, SUM(CASE WHEN kind = 'refund' THEN amount ELSE 0 END) AS refunds, SUM(CASE WHEN kind = 'payment' THEN amount ELSE 0 END) AS paid "
                    "FROM payments WHERE hotel_id = ? AND status = 'completed' AND created_at >= ? AND received_by IS NOT NULL GROUP BY received_by", [hid, since])
    ratios = {r["received_by"]: r["refunds"] / r["paid"] for r in by_user if r["paid"]}
    if len(ratios) >= 3:
        mu, sd = statistics.mean(ratios.values()), statistics.pstdev(ratios.values())
        for uid, ratio in ratios.items():
            if ratio > 0.1 and sd and ratio > mu + 2 * sd:
                _flag(c, hid, "refund_ratio", "medium", f"High refund share by {names.get(uid, uid)} ({ratio:.0%})",
                      f"Refunds equal {ratio:.0%} of the payments this person took in the last {days} days; colleagues average {mu:.0%}.",
                      f"refund_ratio:{uid}:{today.isocalendar()[0]}-{today.isocalendar()[1]}", entity_type="user", entity_id=uid, user_id=uid)
    # 3. after-hours cash payments
    for r in c.all("SELECT p.*, f.number FROM payments p JOIN folios f ON f.id = p.folio_id JOIN payment_methods m ON m.id = p.method_id WHERE p.hotel_id = ? "
                   "AND p.kind = 'payment' AND m.kind = 'cash' AND p.status = 'completed' AND p.created_at >= ?", [hid, since]):
        if _local_hour(r["created_at"], tz) < 5 and r["amount"] >= 2_000_000:
            _flag(c, hid, "after_hours_cash", "low", f"Cash payment at night on {r['number']} ({money(r['amount'])})",
                  "A cash payment of ₦20,000 or more was recorded between midnight and 5 a.m. hotel time; confirm it was banked.", f"after_hours_cash:{r['id']}",
                  entity_type="folio", entity_id=r["folio_id"], amount=r["amount"], user_id=r["received_by"])
    # 4. POS void rate per person
    stats = c.all("SELECT i.added_by AS uid, COUNT(*) AS n, SUM(CASE WHEN i.kitchen_status = 'void' THEN 1 ELSE 0 END) AS voids FROM pos_order_items i "
                  "JOIN pos_orders o ON o.id = i.order_id WHERE o.hotel_id = ? AND o.business_date >= ? AND i.added_by IS NOT NULL GROUP BY i.added_by", [hid, since])
    rates = {s["uid"]: s["voids"] / s["n"] for s in stats if s["n"] >= 5}
    if len(rates) >= 2:
        mu = statistics.mean(rates.values())
        for uid, rate in rates.items():
            if rate >= 0.15 and rate > 2 * mu:
                _flag(c, hid, "pos_void_rate", "medium", f"High void rate for {names.get(uid, uid)} ({rate:.0%} of items)",
                      f"{rate:.0%} of the items this person entered in the last {days} days were voided; the average is {mu:.0%}. Voids after "
                      "preparation can hide unrecorded sales.", f"pos_void_rate:{uid}:{today.isocalendar()[0]}-{today.isocalendar()[1]}", entity_type="user", entity_id=uid, user_id=uid)
    # 5. large POS discounts
    for o in c.all("SELECT * FROM pos_orders WHERE hotel_id = ? AND status = 'settled' AND discount_amount > 0 AND business_date >= ?", [hid, since]):
        gross = (o["net_amount"] or 0) + o["discount_amount"]
        if gross and o["discount_amount"] * 4 > gross:
            _flag(c, hid, "pos_discount", "medium", f"Discount of {o['discount_amount'] * 100 // gross}% on POS order {o['number']}",
                  f"{money(o['discount_amount'])} off a {money(gross)} bill. Reason given: {o['discount_reason'] or 'none'}.", f"pos_discount:{o['id']}",
                  entity_type="pos_order", entity_id=o["id"], business_date=str(o["business_date"]), amount=o["discount_amount"], user_id=o["discount_by"])
    # 6. large folio allowances
    for a in c.all("SELECT fl.*, f.number FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? AND fl.kind = 'adjustment' "
                   "AND fl.total_amount < 0 AND fl.business_date >= ? AND fl.reverses_line_id IS NULL", [hid, since]):
        charges = c.scalar("SELECT COALESCE(SUM(total_amount),0) FROM folio_lines WHERE folio_id = ? AND kind = 'charge'", [a["folio_id"]]) or 0
        if -a["total_amount"] >= 2_500_000 or (charges and -a["total_amount"] * 3 > charges):
            _flag(c, hid, "folio_allowance", "medium", f"Allowance of {money(-a['total_amount'])} on {a['number']}",
                  f"Credit of {money(-a['total_amount'])} against charges of {money(charges)} ({a['description']}).", f"folio_allowance:{a['id']}",
                  entity_type="folio", entity_id=a["folio_id"], business_date=str(a["business_date"]), amount=-a["total_amount"], user_id=a["posted_by"])
    # 7. repeated rate overrides
    for r in c.all("SELECT created_by, COUNT(*) AS n FROM reservations WHERE hotel_id = ? AND rate_overridden = 1 AND created_at >= ? AND created_by IS NOT NULL "
                   "GROUP BY created_by", [hid, since]):
        if r["n"] >= 5:
            _flag(c, hid, "rate_override_pattern", "low", f"{r['n']} manual rate overrides by {names.get(r['created_by'], r['created_by'])}",
                  f"This person overrode the system rate on {r['n']} bookings in the last {days} days. Overrides are permitted but should be explained.",
                  f"rate_override:{r['created_by']}:{today.isocalendar()[0]}-{today.isocalendar()[1]}", entity_type="user", entity_id=r["created_by"], user_id=r["created_by"])
    # 8. duplicate supplier invoices
    inv = c.all("SELECT id, supplier_id, number, invoice_no, invoice_date, amount, created_by FROM supplier_invoices WHERE hotel_id = ? AND invoice_date >= ? "
                "AND status <> 'rejected' ORDER BY supplier_id, amount, invoice_date", [hid, (today - dt.timedelta(days=60)).isoformat()])
    for a, b in zip(inv, inv[1:]):
        if a["supplier_id"] == b["supplier_id"] and a["amount"] == b["amount"] and abs((_d(b["invoice_date"]) - _d(a["invoice_date"])).days) <= 30:
            _flag(c, hid, "duplicate_supplier_invoice", "high", f"Possible duplicate supplier invoice {b['number']} / {a['number']}",
                  f"Same supplier and the same amount ({money(a['amount'])}) within 30 days, supplier references {a['invoice_no']} and {b['invoice_no']}.",
                  f"dup_invoice:{min(a['id'], b['id'])}:{max(a['id'], b['id'])}", entity_type="supplier_invoice", entity_id=b["id"], amount=b["amount"], user_id=b["created_by"])
    # 9. manual journals touching cash / bank
    for j in c.all("SELECT je.id, je.number, je.entry_date, je.description, je.created_by, SUM(jl.debit + jl.credit) AS moved FROM journal_entries je "
                   "JOIN journal_lines jl ON jl.entry_id = je.id JOIN accounts a ON a.id = jl.account_id WHERE je.hotel_id = ? AND je.source = 'manual' "
                   "AND je.entry_date >= ? AND a.system_key IN ('cash','bank') GROUP BY je.id, je.number, je.entry_date, je.description, je.created_by", [hid, since]):
        _flag(c, hid, "manual_cash_journal", "medium", f"Manual journal {j['number']} moves cash/bank ({money(j['moved'])})",
              f"Cash and bank normally move only through payments, refunds and banking. Manual entry: {j['description']}.", f"manual_cash:{j['id']}",
              entity_type="journal_entry", entity_id=j["id"], business_date=str(j["entry_date"]), amount=j["moved"], user_id=j["created_by"])
    return [r["id"] for r in c.all("SELECT id FROM anomaly_flags WHERE hotel_id = ? AND id > ? ORDER BY id", [hid, before])]


def scan_and_notify(c, hotel: dict) -> int:
    from .messaging import notify_template
    from ..worker import _users_with
    ids = scan(c, hotel)
    if ids:
        titles = [r["title"] for r in c.all(f"SELECT title FROM anomaly_flags WHERE id IN ({','.join('?' * len(ids))})", ids)]
        for uid in _users_with(c, hotel["id"], "ai.review"):
            notify_template(c, hotel, "anomaly_digest", {"user_id": uid}, {"count": len(ids), "titles": "; ".join(titles[:5])}, "anomaly", ids[0])
    return len(ids)


@route("GET", "/api/hotels/{hotel_id:int}/insights/anomalies", perm="ai.anomalies.view", tag="ai", summary="Unusual-transaction flags (?status=open|reviewing|confirmed|dismissed)")
def list_anomalies(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        sql = ("SELECT a.*, u.full_name AS user_name, r.full_name AS reviewer_name FROM anomaly_flags a LEFT JOIN users u ON u.id = a.user_id "
               "LEFT JOIN users r ON r.id = a.reviewed_by WHERE a.hotel_id = ?")
        params: list = [hid]
        if ctx.q("status"):
            sql += " AND a.status = ?"
            params.append(ctx.q("status"))
        rows = c.all(sql + " ORDER BY CASE a.status WHEN 'open' THEN 0 WHEN 'reviewing' THEN 1 ELSE 2 END, a.id DESC LIMIT 300", params)
        counts = {r["status"]: r["n"] for r in c.all("SELECT status, COUNT(*) AS n FROM anomaly_flags WHERE hotel_id = ? GROUP BY status", [hid])}
    return {"items": [dict(r) for r in rows], "counts": counts, "rules": RULES,
            "note": "Flags are prompts for a human check, not findings of wrongdoing. Most will have an ordinary explanation."}


@route("POST", "/api/hotels/{hotel_id:int}/insights/anomalies/scan", perm="ai.review", tag="ai", summary="Run the unusual-transaction scan now (?days=7, max 90)")
def scan_now(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    days = min(90, max(1, int(ctx.q("days", 7))))
    with get_db().tx() as c:
        ids = scan(c, get_hotel(c, hid), days)
        audit(c, ctx, "anomaly.scan", "hotel", hid, None, new={"days": days, "new_flags": len(ids)}, hotel_id=hid)
    return {"new_flags": len(ids)}


@route("POST", "/api/anomalies/{flag_id:int}/review", perm="ai.review", tag="ai",
       summary="Record the outcome of a review ({status: reviewing|confirmed|dismissed, note}); you cannot review a flag about yourself")
def review_anomaly(ctx: Ctx):
    status = ctx.field("status", kind=str)
    if status not in ("reviewing", "confirmed", "dismissed"):
        raise bad_request("status must be reviewing, confirmed or dismissed")
    note = ctx.field("note", required=status != "reviewing", kind=str)
    with get_db().tx() as c:
        a = c.one("SELECT * FROM anomaly_flags WHERE id = ?", [ctx.path["flag_id"]])
        if not a:
            raise not_found("Flag")
        ctx.check_hotel(a["hotel_id"])
        if a["user_id"] == ctx.user_id:
            raise conflict("A flag about your own transactions must be reviewed by someone else")
        if a["status"] in ("confirmed", "dismissed"):
            raise conflict("This flag has already been closed")
        c.update("anomaly_flags", a["id"], {"status": status, "reviewed_by": ctx.user_id, "reviewed_at": now_iso(), "review_note": note})
        audit(c, ctx, f"anomaly.{status}", "anomaly_flag", a["id"], a["title"], old={"status": a["status"]}, new={"status": status, "note": note}, hotel_id=a["hotel_id"])
    return {"ok": True}


# ------------------------------------------------------------------ recommendations
def rate_recommendations(c, hotel: dict, days: int = 21) -> list[dict]:
    fc = forecast(c, hotel, days)
    comp = defaultdict(list)
    for r in c.all("SELECT stay_date, rate FROM competitor_rates WHERE hotel_id = ? AND stay_date >= ? AND stay_date <= ?",
                   [hotel["id"], fc["days"][0]["date"], fc["days"][-1]["date"]]):
        comp[str(r["stay_date"])[:10]].append(r["rate"])
    base = c.scalar("SELECT MIN(base_rate) FROM room_types WHERE hotel_id = ? AND active = 1", [hotel["id"]]) or 0
    out = []
    for d in fc["days"]:
        occ = d["expected_occupancy_pct"]
        cavg = int(statistics.mean(comp[d["date"]])) if comp.get(d["date"]) else None
        if occ >= 85:
            adj, why = 15, f"Expected occupancy {occ}% — demand is strong; a higher rate is likely to hold."
        elif occ >= 70:
            adj, why = 8, f"Expected occupancy {occ}% — healthy demand."
        elif occ < 35:
            adj, why = -10, f"Expected occupancy only {occ}% — a lower rate or targeted offer may win bookings."
        else:
            continue
        if cavg and base:
            if adj > 0 and base > cavg * 1.15:
                adj, why = 0, why + f" But your lowest rate is already more than 15% above competitors (avg {cavg / 100:,.0f}); hold the rate."
            elif adj < 0 and base < cavg * 0.85:
                adj, why = 0, why + " Your rate is already well below competitors; consider promotion rather than price."
            else:
                why += f" Competitor average {cavg / 100:,.0f}."
        if adj:
            out.append({"date": d["date"], "expected_occupancy_pct": occ, "on_books": d["on_books"], "suggested_change_pct": adj, "reason": why})
    return out


def _weekly_rule_candidates(recs: list[dict]) -> list[dict]:
    """Group daily suggestions into occupancy-band rules a revenue manager can propose."""
    ups = [r for r in recs if r["suggested_change_pct"] > 0]
    downs = [r for r in recs if r["suggested_change_pct"] < 0]
    out = []
    if ups:
        out.append({"name": "High-demand uplift (suggested)", "min_occupancy_pct": 80, "max_occupancy_pct": 100, "adjustment_bp": 1000,
                    "nights_affected": len(ups)})
    if downs:
        out.append({"name": "Low-demand offer (suggested)", "min_occupancy_pct": 0, "max_occupancy_pct": 35, "adjustment_bp": -1000,
                    "nights_affected": len(downs)})
    return out


def reorder_recommendations(c, hotel: dict) -> list[dict]:
    hid = hotel["id"]
    today = business_date(hotel)
    lead = int(hotel_setting(c, hid, "inventory.lead_time_days", "7") or 7)
    since = (today - dt.timedelta(days=30)).isoformat()
    use = {r["item_id"]: -r["q"] for r in c.all(
        "SELECT item_id, SUM(quantity_milli) AS q FROM stock_movements WHERE hotel_id = ? AND business_date >= ? "
        "AND movement_type IN ('issue','consumption','wastage') GROUP BY item_id", [hid, since])}
    items = c.all("SELECT i.id, i.code, i.name, i.unit, i.last_cost, i.reorder_level_milli, i.reorder_qty_milli, COALESCE(SUM(l.quantity_milli),0) AS on_hand "
                  "FROM inventory_items i LEFT JOIN stock_levels l ON l.item_id = i.id WHERE i.hotel_id = ? AND i.active = 1 "
                  "GROUP BY i.id, i.code, i.name, i.unit, i.last_cost, i.reorder_level_milli, i.reorder_qty_milli", [hid])
    out = []
    for it in items:
        daily = max(0, use.get(it["id"], 0)) / 30
        cover = it["on_hand"] / daily if daily else None
        below_level = it["reorder_level_milli"] and it["on_hand"] <= it["reorder_level_milli"]
        short = cover is not None and cover < lead + 3
        if not (below_level or short):
            continue
        target = daily * (lead + 3 + 14)
        qty = max(it["reorder_qty_milli"] or 0, int(math.ceil(max(0, target - it["on_hand"]))))
        if qty <= 0:
            continue
        reason = []
        if daily:
            reason.append(f"uses about {daily / 1000:.2f} {it['unit']}/day (last 30 days), stock covers {cover:.1f} days" if cover is not None else "")
        if below_level:
            reason.append("at or below its reorder level")
        reason.append(f"supplier lead time assumed {lead} days + 3 days safety, ordering for 14 days' use")
        out.append({"item_id": it["id"], "code": it["code"], "name": it["name"], "unit": it["unit"], "on_hand": it["on_hand"] / 1000,
                    "daily_use": round(daily / 1000, 3), "days_cover": round(cover, 1) if cover is not None else None,
                    "suggested_qty": round(qty / 1000, 3), "estimated_cost": qty * it["last_cost"] // 1000,
                    "urgency": "high" if cover is not None and cover < lead else "normal", "reason": "; ".join(r for r in reason if r)})
    return sorted(out, key=lambda x: (x["urgency"] != "high", x["days_cover"] if x["days_cover"] is not None else 999))


@route("GET", "/api/hotels/{hotel_id:int}/insights/recommendations", perm="ai.assistant", tag="ai",
       summary="Rate recommendations (needs sales.view) and reorder recommendations (needs inventory.view), each with its reasoning")
def recommendations(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    out: dict = {"denied": []}
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        if ctx.can("sales.view"):
            recs = rate_recommendations(c, hotel)
            out["rates"] = {"items": recs, "rule_candidates": _weekly_rule_candidates(recs),
                            "method": "Uses the demand forecast (see Forecast) and recorded competitor rates. Suggestions only: a rule you propose "
                                      "takes effect after a second person approves it, and booked guests keep their quoted price."}
        else:
            out["denied"].append("rate recommendations need sales.view")
        if ctx.can("inventory.view"):
            out["reorder"] = {"items": reorder_recommendations(c, hotel),
                              "method": "Average daily usage over 30 days against stock on hand and an assumed supplier lead time (setting "
                                        "inventory.lead_time_days). Creating a requisition sends it for normal approval."}
        else:
            out["denied"].append("reorder recommendations need inventory.view")
    return out


@route("POST", "/api/hotels/{hotel_id:int}/insights/recommendations/propose-rule", perm="sales.pricing", tag="ai",
       summary="Turn a suggested rule into a pricing rule awaiting approval ({name, min_occupancy_pct, max_occupancy_pct, adjustment_bp})")
def propose_rule(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    lo, hi, bp = ctx.field("min_occupancy_pct", kind=int), ctx.field("max_occupancy_pct", kind=int), ctx.field("adjustment_bp", kind=int)
    if not (0 <= lo < hi <= 100) or not -5000 <= bp <= 5000 or bp == 0:
        raise bad_request("Occupancy band must be 0–100 and the adjustment between −50 % and +50 %")
    with get_db().tx() as c:
        rid = c.insert("rate_rules", {"hotel_id": hid, "name": ctx.field("name", kind=str)[:150], "min_occupancy_pct": lo, "max_occupancy_pct": hi,
                                      "adjustment_bp": bp, "status": "pending_approval", "created_by": ctx.user_id, "created_at": now_iso()})
        audit(c, ctx, "rate_rule.proposed_from_recommendation", "rate_rule", rid, None, new={"band": [lo, hi], "bp": bp}, hotel_id=hid)
    return {"id": rid, "status": "pending_approval", "_created": True}


@route("POST", "/api/hotels/{hotel_id:int}/insights/recommendations/requisition", perm="procurement.requisition", tag="ai",
       summary="Create a draft purchase requisition from reorder recommendations ({item_ids}); it then follows normal approval")
def requisition_from_recs(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    ids = ctx.field("item_ids")
    if not isinstance(ids, list) or not ids:
        raise bad_request("Choose at least one item")
    with get_db().tx() as c:
        recs = {r["item_id"]: r for r in reorder_recommendations(c, get_hotel(c, hid))}
        chosen = [recs[int(i)] for i in ids if int(i) in recs]
        if not chosen:
            raise conflict("None of these items currently need reordering")
    from .procurement import create_preq
    ctx.body = {"department": "stores", "justification": "Reorder recommended by stock analysis (usage vs. stock on hand)",
                "lines": [{"item_id": r["item_id"], "quantity": r["suggested_qty"],
                           "est_unit_cost": int(r["estimated_cost"] / r["suggested_qty"]) if r["suggested_qty"] else 0} for r in chosen]}
    return create_preq(ctx)
