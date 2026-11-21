"""Executive dashboard KPIs: occupancy, ADR, RevPAR, arrivals, departures, revenue, balances, trends. (Section 8.2, 21)"""
from __future__ import annotations

import datetime as dt

from ..db import get_db
from ..http import Ctx, route
from ..services import business_date, get_hotel


def kpis_for(c, hid: int, day: dt.date) -> dict:
    d = day.isoformat()
    total = c.scalar("SELECT COUNT(*) FROM rooms WHERE hotel_id = ? AND active = 1", [hid]) or 0
    ooo = c.scalar("SELECT COUNT(*) FROM rooms WHERE hotel_id = ? AND active = 1 AND service_status NOT IN ('in_service','vip_hold')", [hid]) or 0
    occupied = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status IN ('checked_in','checked_out') AND arrival <= ? AND departure > ?",
                        [hid, d, d]) or 0
    room_rev = c.scalar("SELECT COALESCE(SUM(fl.net_amount),0) FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? "
                        "AND fl.department = 'room' AND fl.kind IN ('charge','adjustment') AND fl.business_date = ?", [hid, d]) or 0
    available = max(total - ooo, 0)
    return {"date": d, "total_rooms": total, "out_of_service": ooo, "sellable_rooms": available, "rooms_sold": occupied,
            "occupancy_pct": round(occupied * 100 / available, 1) if available else 0.0, "room_revenue": room_rev,
            "adr": room_rev // occupied if occupied else 0, "revpar": room_rev // available if available else 0}


@route("GET", "/api/hotels/{hotel_id:int}/dashboard", perm="dashboard.view", tag="dashboard", summary="Executive dashboard KPIs and trends")
def dashboard(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        hotel = get_hotel(c, hid)
        bdate = business_date(hotel)
        d = bdate.isoformat()
        rooms = c.all("SELECT occupancy, hk_status, service_status FROM rooms WHERE hotel_id = ? AND active = 1", [hid])
        status = {
            "occupied": sum(1 for r in rooms if r["occupancy"] == "occupied"),
            "vacant_ready": sum(1 for r in rooms if r["occupancy"] == "vacant" and r["hk_status"] == "inspected" and r["service_status"] in ("in_service", "vip_hold")),
            "vacant_dirty": sum(1 for r in rooms if r["occupancy"] == "vacant" and r["hk_status"] in ("dirty", "in_progress")),
            "awaiting_inspection": sum(1 for r in rooms if r["occupancy"] == "vacant" and r["hk_status"] == "clean"),
            "out_of_service": sum(1 for r in rooms if r["service_status"] not in ("in_service", "vip_hold")),
        }
        arrivals = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND arrival = ? AND status IN ('confirmed','tentative')", [hid, d])
        arrived = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND arrival = ? AND status IN ('checked_in','checked_out')", [hid, d])
        departures = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND departure <= ? AND status = 'checked_in'", [hid, d])
        departed = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status = 'checked_out' AND departure = ?", [hid, d])
        guests_in = c.scalar("SELECT COALESCE(SUM(adults + children),0) FROM reservations WHERE hotel_id = ? AND status = 'checked_in'", [hid])
        pending = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status IN ('tentative','waitlisted','enquiry') AND departure > ?", [hid, d])
        revenue_today = c.all("SELECT fl.department, COALESCE(SUM(fl.net_amount),0) AS amount FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id "
                              "WHERE f.hotel_id = ? AND fl.kind IN ('charge','adjustment') AND fl.business_date = ? GROUP BY fl.department", [hid, d])
        outstanding = c.scalar(
            "SELECT COALESCE(SUM(CASE WHEN fl.kind IN ('charge','adjustment','refund') THEN fl.total_amount ELSE -fl.total_amount END),0) "
            "FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id WHERE f.hotel_id = ? AND f.status = 'open'", [hid])
        payments_today = c.scalar("SELECT COALESCE(SUM(CASE WHEN p.kind = 'payment' THEN p.amount ELSE -p.amount END),0) FROM payments p "
                                  "JOIN journal_entries je ON je.id = p.journal_entry_id WHERE p.hotel_id = ? AND p.status = 'completed' "
                                  "AND je.entry_date = ?", [hid, d])
        hk_pending = c.scalar("SELECT COUNT(*) FROM housekeeping_tasks WHERE hotel_id = ? AND status IN ('pending','in_progress','rejected')", [hid])
        hk_inspect = c.scalar("SELECT COUNT(*) FROM housekeeping_tasks WHERE hotel_id = ? AND status = 'completed'", [hid])
        approvals = c.scalar("SELECT COUNT(*) FROM approvals WHERE hotel_id = ? AND status = 'pending'", [hid])
        today = kpis_for(c, hid, bdate)
        trend = [kpis_for(c, hid, bdate - dt.timedelta(days=i)) for i in range(29, -1, -1)]
        forecast = []
        for i in range(0, 14):
            day = (bdate + dt.timedelta(days=i)).isoformat()
            on_books = c.scalar("SELECT COUNT(*) FROM reservations WHERE hotel_id = ? AND status IN ('confirmed','tentative','checked_in') "
                                "AND arrival <= ? AND departure > ?", [hid, day, day])
            forecast.append({"date": day, "rooms_on_books": on_books,
                             "occupancy_pct": round(on_books * 100 / today["sellable_rooms"], 1) if today["sellable_rooms"] else 0})
        month_start = bdate.replace(day=1).isoformat()
        sources = c.all("SELECT source, COUNT(*) AS bookings FROM reservations WHERE hotel_id = ? AND created_at >= ? "
                        "AND status NOT IN ('enquiry') GROUP BY source ORDER BY bookings DESC", [hid, month_start])
        by_type = c.all("SELECT rt.name, COUNT(r.id) AS bookings FROM room_types rt LEFT JOIN reservations r ON r.room_type_id = rt.id "
                        "AND r.status IN ('confirmed','checked_in','checked_out') AND r.arrival >= ? WHERE rt.hotel_id = ? GROUP BY rt.name ORDER BY bookings DESC",
                        [month_start, hid])
        mtd = c.all("SELECT fl.department, COALESCE(SUM(fl.net_amount),0) AS amount FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id "
                    "WHERE f.hotel_id = ? AND fl.kind IN ('charge','adjustment') AND fl.business_date >= ? AND fl.business_date <= ? GROUP BY fl.department",
                    [hid, month_start, d])
    return {"business_date": d, "hotel": {"id": hotel["id"], "name": hotel["name"], "currency": hotel["currency"]},
            "today": today, "room_status": status,
            "front_office": {"arrivals_expected": arrivals, "arrived": arrived, "departures_expected": departures, "departed": departed,
                             "in_house_guests": guests_in, "pending_reservations": pending},
            "revenue_today": revenue_today, "revenue_mtd": mtd, "outstanding_balances": outstanding, "payments_today": payments_today,
            "tasks": {"housekeeping_open": hk_pending, "awaiting_inspection": hk_inspect, "approvals_pending": approvals},
            "trend": trend, "forecast": forecast, "booking_sources": sources, "room_type_mix": by_type}
