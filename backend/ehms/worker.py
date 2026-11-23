"""Background worker: scheduled jobs and message delivery.

Started automatically inside the web process (every EHMS_WORKER_INTERVAL seconds, default 60) unless
EHMS_WORKER=0. For multi-instance deployments run it once, separately:  python -m ehms.worker
Every job is idempotent: a (job, key) row in job_runs ensures each reminder is sent once."""
from __future__ import annotations

import asyncio
import datetime as dt
import logging
import os

from .db import IntegrityError, get_db, now_iso
from .services import business_date, hotel_today

log = logging.getLogger("ehms.worker")


def _once(c, job: str, key: str) -> bool:
    if c.one("SELECT id FROM job_runs WHERE job = ? AND run_key = ?", [job, key]):
        return False
    c.insert("job_runs", {"job": job, "run_key": key, "created_at": now_iso()})
    return True


def _users_with(c, hotel_id: int, perm: str) -> list[int]:
    return [r["id"] for r in c.all("SELECT DISTINCT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN role_permissions rp ON rp.role_id = ur.role_id "
                                   "LEFT JOIN user_hotels uh ON uh.user_id = u.id WHERE rp.permission_code = ? AND u.status = 'active' "
                                   "AND (u.all_hotels = 1 OR uh.hotel_id = ?)", [perm, hotel_id])]


def run_jobs() -> dict:
    from .modules.messaging import notify_template
    done = {"checkin_reminders": 0, "birthdays": 0, "low_stock_digests": 0, "invoice_alerts": 0, "preventive_work_orders": 0, "complaints_escalated": 0, "scheduled_reports": 0, "anomaly_flags": 0}
    db = get_db()
    with db.tx() as c:
        hotels = c.all("SELECT * FROM hotels WHERE active = 1")
    for h in hotels:
        with db.tx() as c:
            today = business_date(h)
            tomorrow = (today + dt.timedelta(days=1)).isoformat()
            for r in c.all("SELECT r.*, g.first_name, g.last_name, g.email, g.phone, rt.name AS room_type FROM reservations r JOIN guests g ON g.id = r.guest_id "
                           "JOIN room_types rt ON rt.id = r.room_type_id WHERE r.hotel_id = ? AND r.arrival = ? AND r.status = 'confirmed'", [h["id"], tomorrow]):
                if _once(c, "checkin_reminder", str(r["id"])):
                    notify_template(c, h, "checkin_reminder", {"email": r["email"], "phone": r["phone"]},
                                    {"guest": r["first_name"], "reference": r["reference"], "arrival": r["arrival"], "room_type": r["room_type"]},
                                    "reservation", r["id"])
                    done["checkin_reminders"] += 1
            md = hotel_today(h).strftime("-%m-%d")
            for g in c.all("SELECT * FROM guests WHERE organisation_id = ? AND marketing_consent = 1 AND CAST(date_of_birth AS VARCHAR(10)) LIKE ?", [h["organisation_id"], f"%{md}"]):
                if _once(c, "birthday", f"{h['id']}:{g['id']}:{hotel_today(h).year}"):
                    notify_template(c, h, "birthday", {"email": g["email"]}, {"guest": g["first_name"]}, "guest", g["id"])
                    done["birthdays"] += 1
            low = c.all("SELECT i.name FROM inventory_items i LEFT JOIN stock_levels l ON l.item_id = i.id WHERE i.hotel_id = ? AND i.active = 1 "
                        "AND i.reorder_level_milli > 0 GROUP BY i.id, i.name, i.reorder_level_milli HAVING COALESCE(SUM(l.quantity_milli),0) <= i.reorder_level_milli",
                        [h["id"]])
            if low and _once(c, "low_stock_digest", f"{h['id']}:{today}"):
                for uid in _users_with(c, h["id"], "inventory.manage"):
                    notify_template(c, h, "low_stock_digest", {"user_id": uid}, {"count": len(low), "items": ", ".join(x["name"] for x in low[:10])},
                                    "inventory", h["id"])
                done["low_stock_digests"] += 1
            from .modules.maintenance import raise_due_preventive
            done["preventive_work_orders"] += raise_due_preventive(c, h)
            from .modules.crm import escalate_overdue
            done["complaints_escalated"] += escalate_overdue(c, h)
            from .modules.hrsuite import hr_alerts
            done["hr_alerts"] = done.get("hr_alerts", 0) + hr_alerts(c, h)
            from .modules.groups import release_after_cutoff
            done["group_blocks_released"] = done.get("group_blocks_released", 0) + release_after_cutoff(c, h)
            from .modules.bi import run_due_schedules
            done["scheduled_reports"] += run_due_schedules(c, h)
            if _once(c, "anomaly_scan", f"{h['id']}:{today}"):
                from .modules.insights import scan_and_notify
                done["anomaly_flags"] += scan_and_notify(c, h)
            due = c.one("SELECT COUNT(*) AS n, COALESCE(SUM(amount - amount_paid),0) AS total FROM supplier_invoices WHERE hotel_id = ? "
                        "AND status IN ('approved','part_paid') AND due_date <= ?", [h["id"], (today + dt.timedelta(days=3)).isoformat()])
            if due["n"] and _once(c, "invoices_due", f"{h['id']}:{today}"):
                for uid in _users_with(c, h["id"], "procurement.pay"):
                    notify_template(c, h, "invoices_due", {"user_id": uid}, {"count": due["n"], "total": f"{h['currency']} {due['total'] / 100:,.2f}"},
                                    "procurement", h["id"])
                done["invoice_alerts"] += 1
    return done


def run_once() -> dict:
    from .notify import deliver_queued
    jobs = run_jobs()
    return {"jobs": jobs, "delivery": deliver_queued()}


async def loop(interval: int) -> None:
    while True:
        try:
            await asyncio.to_thread(run_once)
        except Exception:  # pragma: no cover
            log.exception("worker cycle failed")
        await asyncio.sleep(interval)


def enabled() -> bool:
    return os.environ.get("EHMS_WORKER", "1") == "1"


if __name__ == "__main__":  # pragma: no cover
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--loop" in sys.argv:
        asyncio.run(loop(int(os.environ.get("EHMS_WORKER_INTERVAL", "60"))))
    else:
        print(run_once())
