"""Rate engine: negotiated (corporate / travel-agent) rates, rate cards with weekend rates, seasonal adjustments,
and approved occupancy-based (dynamic) adjustments. Quoted per-night rates are locked on the reservation so a
guest pays what they were quoted even if demand changes later."""
from __future__ import annotations

import datetime as dt
import json

from .db import Connection


def occupancy_pct(c: Connection, hotel_id: int, night: dt.date) -> float:
    total = c.scalar("SELECT COUNT(*) FROM rooms WHERE hotel_id = ? AND active = 1 AND service_status IN ('in_service','vip_hold')", [hotel_id]) or 0
    if not total:
        return 0.0
    d = night.isoformat()
    sold = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status IN ('confirmed','tentative','checked_in') AND arrival <= ? AND departure > ?",
                    [hotel_id, d, d]) or 0
    return sold * 100 / total


def card_rate(c: Connection, hotel_id: int, rt: dict, booking_type: str, night: dt.date, account_id: int | None = None) -> tuple[int, list[str]]:
    """Rate before dynamic pricing, with the reasons applied (for transparency in quotes)."""
    d = night.isoformat()
    if account_id:
        neg = c.one("SELECT rate FROM corporate_rates WHERE account_id = ? AND room_type_id = ? AND valid_from <= ? AND valid_to >= ? ORDER BY id DESC LIMIT 1",
                    [account_id, rt["id"], d, d])
        if neg:
            return neg["rate"], ["negotiated rate"]
    if booking_type == "corporate" and rt.get("corporate_rate"):
        return rt["corporate_rate"], ["corporate rate"]
    rate, why = (rt["weekend_rate"], ["weekend rate"]) if night.weekday() in (4, 5) and rt.get("weekend_rate") else (rt["base_rate"], [])
    s = c.one("SELECT * FROM rate_seasons WHERE hotel_id = ? AND active = 1 AND start_date <= ? AND end_date >= ? AND (room_type_id IS NULL OR room_type_id = ?) "
              "ORDER BY CASE WHEN room_type_id IS NULL THEN 1 ELSE 0 END, id DESC LIMIT 1", [rt["hotel_id"], d, d, rt["id"]])
    if s:
        rate = rate * (10000 + s["adjustment_bp"]) // 10000
        why.append(f"{s['name']} {s['adjustment_bp'] / 100:+g}%")
    return max(rate, 0), why


def dynamic_adjustment(c: Connection, hotel_id: int, rt: dict, night: dt.date) -> tuple[int, str | None]:
    occ = occupancy_pct(c, hotel_id, night)
    r = c.one("SELECT * FROM rate_rules WHERE hotel_id = ? AND status = 'active' AND (room_type_id IS NULL OR room_type_id = ?) "
              "AND min_occupancy_pct <= ? AND max_occupancy_pct >= ? ORDER BY ABS(adjustment_bp) DESC LIMIT 1", [hotel_id, rt["id"], occ, occ])
    return (r["adjustment_bp"], f"{r['name']} {r['adjustment_bp'] / 100:+g}% at {occ:.0f}% occupancy") if r else (0, None)


def quote_night(c: Connection, hotel_id: int, rt: dict, booking_type: str, night: dt.date, override: int | None, account_id: int | None) -> tuple[int, list[str]]:
    if override is not None:
        return override, ["agreed rate"]
    rate, why = card_rate(c, hotel_id, rt, booking_type, night, account_id)
    if not account_id and booking_type != "corporate":
        adj, reason = dynamic_adjustment(c, hotel_id, rt, night)
        if adj:
            rate = rate * (10000 + adj) // 10000
            why.append(reason)
    return max(rate, 0), why


def stay_night_rate(c: Connection, r: dict, rt: dict, night: dt.date) -> int:
    """Rate actually charged for a night of an existing reservation (before extra-person charges and discounts)."""
    if r["rate_overridden"]:
        return r["nightly_rate"]
    locked = json.loads(r["locked_rates"]) if r.get("locked_rates") else {}
    if night.isoformat() in locked:
        return int(locked[night.isoformat()])
    return card_rate(c, r["hotel_id"], rt, r["booking_type"], night, r.get("corporate_account_id"))[0]
