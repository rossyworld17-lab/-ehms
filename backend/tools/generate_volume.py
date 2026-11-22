"""Generate a year of synthetic stay history in a DEMO database, for performance testing only.

    DATABASE_URL=... EHMS_SECRET_KEY=... python tools/generate_volume.py --days 365 --occupancy 0.7

Adds checked-out reservations with folios, nightly room charges, restaurant charges, payments and matching
balanced journal entries for the demo hotel (code CGL). Refuses to run unless the demo organisation exists.
Never run it against a live hotel's database."""
from __future__ import annotations

import argparse
import datetime as dt
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ehms.db import get_db, now_iso  # noqa: E402
from ehms.services import account_id  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=365)
    ap.add_argument("--occupancy", type=float, default=0.7)
    a = ap.parse_args()
    random.seed(42)
    db = get_db()
    with db.tx() as c:
        h = c.one("SELECT h.* FROM hotels h JOIN organisations o ON o.id = h.organisation_id WHERE h.code = 'CGL' AND o.code = 'DEMO'")
        if not h:
            raise SystemExit("Demo hotel not found — this tool only runs on a demo database")
        org = h["organisation_id"]
        rooms = c.all("SELECT r.id, r.room_type_id, rt.base_rate FROM rooms r JOIN room_types rt ON rt.id = r.room_type_id WHERE r.hotel_id = ? AND r.active = 1", [h["id"]])
        user = c.scalar("SELECT MIN(id) FROM users WHERE organisation_id = ?", [org])
        cash = c.scalar("SELECT id FROM payment_methods WHERE hotel_id = ? AND code = 'CASH'", [h["id"]])
        acc = {k: account_id(c, org, k) for k in ("cash", "guest_ledger", "rev_room", "rev_fnb", "vat_payable", "service_charge_payable")}
    today = dt.date.fromisoformat(str(h["business_date"])[:10]) if h.get("business_date") else dt.date.today()
    start = today - dt.timedelta(days=a.days)
    busy: dict[int, dt.date] = {r["id"]: start for r in rooms}
    n_res = 0
    day = start
    seq = 0
    while day < today - dt.timedelta(days=1):
        with db.tx() as c:
            for r in rooms:
                if busy[r["id"]] > day or random.random() > a.occupancy / 2.2:
                    continue
                nights = random.choice([1, 1, 2, 2, 3, 4])
                dep = min(day + dt.timedelta(days=nights), today - dt.timedelta(days=1))
                if dep <= day:
                    continue
                busy[r["id"]] = dep
                seq += 1
                g = c.insert("guests", {"organisation_id": org, "first_name": random.choice(["Ada", "Bayo", "Chika", "Dayo", "Efe", "Femi", "Gozie", "Hauwa"]),
                                        "last_name": f"Load{seq:06d}", "email": f"load{seq}@example.com", "marketing_consent": 0, "created_at": now_iso()})
                created = (day - dt.timedelta(days=random.randint(0, 30))).isoformat() + "T10:00:00Z"
                rid = c.insert("reservations", {"hotel_id": h["id"], "reference": f"LOAD-{seq:07d}", "guest_id": g, "status": "checked_out", "booking_type": "individual",
                                                "source": random.choice(["front_desk", "website", "booking_engine", "phone", "ota", "corporate"]),
                                                "arrival": day.isoformat(), "departure": dep.isoformat(), "adults": 2, "children": 0, "room_type_id": r["room_type_id"],
                                                "room_id": r["id"], "nightly_rate": r["base_rate"], "rate_overridden": 0, "discount_amount": 0, "deposit_required": 0,
                                                "created_at": created, "updated_at": created, "checked_in_at": day.isoformat() + "T14:00:00Z",
                                                "checked_out_at": dep.isoformat() + "T11:00:00Z"})
                fid = c.insert("folios", {"hotel_id": h["id"], "number": f"FOL-LOAD-{seq:07d}", "reservation_id": rid, "guest_id": g, "status": "closed",
                                          "opened_at": day.isoformat() + "T14:00:00Z", "closed_at": dep.isoformat() + "T11:00:00Z"})
                total = 0
                for i in range((dep - day).days):
                    n = day + dt.timedelta(days=i)
                    net = r["base_rate"]
                    svc, tax = net // 10, (net + net // 10) * 75 // 1000
                    total += net + svc + tax
                    je = c.insert("journal_entries", {"hotel_id": h["id"], "number": f"JE-LOAD-{seq:07d}-{i}", "entry_date": n.isoformat(), "description": "Room night (load test)",
                                                      "source": "folio", "source_ref": f"FOL-LOAD-{seq:07d}", "created_by": user, "created_at": now_iso()})
                    for acct, dr, cr in ((acc["guest_ledger"], net + svc + tax, 0), (acc["rev_room"], 0, net), (acc["service_charge_payable"], 0, svc), (acc["vat_payable"], 0, tax)):
                        c.insert("journal_lines", {"entry_id": je, "account_id": acct, "debit": dr, "credit": cr, "department": "room"})
                    c.insert("folio_lines", {"folio_id": fid, "business_date": n.isoformat(), "kind": "charge", "department": "room", "description": "Room night", "quantity": 1,
                                             "net_amount": net, "tax_amount": tax, "service_charge": svc, "total_amount": net + svc + tax, "reference": f"ROOM:{rid}:{n.isoformat()}",
                                             "journal_entry_id": je, "posted_by": user, "posted_at": now_iso()})
                if random.random() < 0.6:
                    net = random.choice([800000, 1500000, 2500000, 4000000])
                    svc, tax = net // 10, (net + net // 10) * 75 // 1000
                    total += net + svc + tax
                    je = c.insert("journal_entries", {"hotel_id": h["id"], "number": f"JE-LOAD-{seq:07d}-F", "entry_date": day.isoformat(), "description": "Dinner (load test)",
                                                      "source": "folio", "source_ref": f"FOL-LOAD-{seq:07d}", "created_by": user, "created_at": now_iso()})
                    for acct, dr, cr in ((acc["guest_ledger"], net + svc + tax, 0), (acc["rev_fnb"], 0, net), (acc["service_charge_payable"], 0, svc), (acc["vat_payable"], 0, tax)):
                        c.insert("journal_lines", {"entry_id": je, "account_id": acct, "debit": dr, "credit": cr, "department": "fnb"})
                    c.insert("folio_lines", {"folio_id": fid, "business_date": day.isoformat(), "kind": "charge", "department": "fnb", "description": "Dinner", "quantity": 1,
                                             "net_amount": net, "tax_amount": tax, "service_charge": svc, "total_amount": net + svc + tax, "journal_entry_id": je,
                                             "posted_by": user, "posted_at": now_iso()})
                je = c.insert("journal_entries", {"hotel_id": h["id"], "number": f"JE-LOAD-{seq:07d}-P", "entry_date": dep.isoformat(), "description": "Payment (load test)",
                                                  "source": "payment", "source_ref": f"LOAD-{seq:07d}", "created_by": user, "created_at": now_iso()})
                c.insert("journal_lines", {"entry_id": je, "account_id": acc["cash"], "debit": total, "credit": 0})
                c.insert("journal_lines", {"entry_id": je, "account_id": acc["guest_ledger"], "debit": 0, "credit": total})
                pid = c.insert("payments", {"hotel_id": h["id"], "folio_id": fid, "method_id": cash, "kind": "payment", "amount": total, "currency": h["currency"], "status": "completed",
                                            "idempotency_key": f"load-{seq}", "received_by": user, "journal_entry_id": je, "created_at": dep.isoformat() + "T11:00:00Z"})
                c.insert("folio_lines", {"folio_id": fid, "business_date": dep.isoformat(), "kind": "payment", "department": "payment", "description": "Payment — Cash", "quantity": 1,
                                         "net_amount": total, "tax_amount": 0, "service_charge": 0, "total_amount": total, "payment_id": pid, "journal_entry_id": je,
                                         "posted_by": user, "posted_at": now_iso()})
                n_res += 1
        day += dt.timedelta(days=1)
    with db.tx() as c:
        counts = {t: c.scalar(f"SELECT COUNT(*) FROM {t}") for t in ("reservations", "folio_lines", "journal_lines", "payments", "guests")}
        dr, cr = c.one("SELECT SUM(debit) AS d, SUM(credit) AS c FROM journal_lines").values()
    print(f"Added {n_res} stays over {a.days} days. Table sizes: {counts}. Ledger balanced: {dr == cr}")


if __name__ == "__main__":
    main()
