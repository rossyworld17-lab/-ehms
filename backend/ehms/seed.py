"""Bootstrap and demonstration data.

  python -m ehms.seed bootstrap --org "My Hotels Ltd" --org-code MHL --hotel "My Hotel" --hotel-code MH \
         --admin-email owner@example.com --admin-name "Jane Owner"
      Creates a real organisation, first hotel and an Organisation Owner account (prints a temporary password).

  python -m ehms.seed demo
      Loads clearly-labelled DEMO data (fictional hotels, staff and guests). Never run against production.
"""
from __future__ import annotations

import argparse
import datetime as dt
import secrets

from . import security
from .db import get_db, now_iso
from .migrate import migrate
from .rbac import seed_permissions_and_roles
from .services import business_date, hotel_today, seed_chart_of_accounts

DEMO_PASSWORD = "Demo@12345"


def bootstrap(org_name: str, org_code: str, hotel_name: str, hotel_code: str, admin_email: str, admin_name: str,
              password: str | None = None) -> dict:
    migrate()
    from .modules.properties import seed_hotel_defaults
    password = password or ("Tmp-" + secrets.token_urlsafe(10) + "7a")
    with get_db().tx() as c:
        if c.one("SELECT id FROM organisations WHERE code = ?", [org_code]):
            raise SystemExit(f"Organisation {org_code} already exists")
        org = c.insert("organisations", {"code": org_code, "name": org_name, "created_at": now_iso()})
        roles = seed_permissions_and_roles(c, org)
        seed_chart_of_accounts(c, org)
        hid = c.insert("hotels", {"organisation_id": org, "code": hotel_code.upper(), "name": hotel_name, "created_at": now_iso()})
        seed_hotel_defaults(c, hid, org)
        uid = c.insert("users", {"organisation_id": org, "email": admin_email.lower(), "full_name": admin_name,
                                 "password_hash": security.hash_password(password), "all_hotels": 1, "must_change_password": 1,
                                 "created_at": now_iso(), "password_changed_at": now_iso()})
        c.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", [uid, roles["org_owner"]])
    return {"organisation_id": org, "hotel_id": hid, "admin_email": admin_email, "temporary_password": password}


ROOM_TYPES = [
    ("STD", "Standard Room", "Comfortable queen room with work desk, smart TV and rain shower.", 2, 1, "1 Queen", 24, 4500000, 5000000, 4000000),
    ("DLX", "Deluxe Room", "Spacious king room with city view, minibar and sofa.", 3, 1, "1 King", 32, 6500000, 7000000, 5800000),
    ("EXE", "Executive Room", "Executive floor, lounge access, king bed and bathtub.", 3, 1, "1 King", 38, 9500000, 9500000, 8500000),
    ("JST", "Junior Suite", "Separate living area, king bed and dining corner.", 4, 2, "1 King + sofa bed", 55, 15000000, 15000000, 13500000),
    ("PRS", "Presidential Suite", "Two-bedroom suite with private lounge, kitchenette and butler service.", 6, 3, "2 King + 1 Twin", 140, 45000000, 45000000, None),
]
AMENITIES = "Wi-Fi, Air conditioning, Smart TV, Safe, Kettle, Hair dryer"

GUESTS = [("Adaeze", "Okonkwo", "Lagos"), ("Tunde", "Bakare", "Ibadan"), ("Ebiere", "Tamuno", "Yenagoa"), ("Chinedu", "Eze", "Enugu"),
          ("Fatima", "Bello", "Kano"), ("Ifeoma", "Nwosu", "Owerri"), ("Seun", "Adeyemi", "Abeokuta"), ("Diepreye", "Alamieyeseigha", "Brass"),
          ("Amaka", "Obi", "Onitsha"), ("Yusuf", "Garba", "Kaduna"), ("Grace", "Ekanem", "Uyo"), ("Michael", "Johnson", "London")]


def seed_demo() -> None:
    migrate()
    from .modules.frontoffice import ensure_folio, post_charge, post_room_night
    from .modules.properties import seed_hotel_defaults
    from .services import account_id, next_number, post_journal
    db = get_db()
    with db.tx() as c:
        if c.one("SELECT id FROM organisations WHERE code = 'DEMO'"):
            return
        org = c.insert("organisations", {"code": "DEMO", "name": "DEMO — Crestview Hospitality Group", "created_at": now_iso()})
        roles = seed_permissions_and_roles(c, org)
        seed_chart_of_accounts(c, org)
        hotels = []
        for code, name, city, floors in (("CGL", "Crestview Grand Lagos (Demo)", "Victoria Island, Lagos", 4),
                                         ("CSA", "Crestview Suites Abuja (Demo)", "Wuse II, Abuja", 3)):
            hid = c.insert("hotels", {"organisation_id": org, "code": code, "name": name, "legal_name": "Crestview Hospitality Ltd (demo)",
                                      "category": "hotel", "star_rating": 4, "address": "12 Demo Avenue", "city": city, "state": city.split(", ")[-1],
                                      "country": "Nigeria", "phone": "+234 800 000 0000", "email": f"reservations@{code.lower()}.demo",
                                      "floors": floors, "timezone": "Africa/Lagos", "currency": "NGN", "check_in_time": "14:00", "check_out_time": "12:00",
                                      "cancellation_policy": "Free cancellation up to 48 hours before arrival. Later cancellations and no-shows are charged one night.",
                                      "reservation_policy": "A valid ID is required at check-in. Deposits may be requested for peak dates.",
                                      "terms": "Prices include applicable taxes and service charge as shown. This is demonstration data.",
                                      "amenities": "Swimming pool, Gym, Restaurant, Bar, Conference hall, Airport shuttle, Wi-Fi",
                                      "service_charge_bp": 1000, "created_at": now_iso()})
            seed_hotel_defaults(c, hid, org)
            # VAT is configurable; 7.5% shown as an example. Confirm current rates with your tax adviser.
            c.insert("tax_rules", {"hotel_id": hid, "code": "VAT", "name": "Value Added Tax", "rate_bp": 750, "applies_to": "all",
                                   "is_inclusive": 0, "effective_from": "2020-02-01", "active": 1})
            hotels.append(hid)
            types = {}
            for t in ROOM_TYPES:
                types[t[0]] = c.insert("room_types", {"hotel_id": hid, "code": t[0], "name": t[1], "description": t[2], "max_occupancy": t[3],
                                                      "beds": t[4], "bed_config": t[5], "size_sqm": t[6], "base_rate": t[7], "weekend_rate": t[8],
                                                      "corporate_rate": t[9], "extra_person_charge": 1500000, "amenities": AMENITIES})
            layout = {1: ["STD"] * 5 + ["DLX"] * 3, 2: ["STD"] * 3 + ["DLX"] * 4 + ["EXE"], 3: ["DLX"] * 2 + ["EXE"] * 4 + ["JST"] * 2, 4: ["JST"] * 2 + ["PRS"]}
            for floor in range(1, floors + 1):
                for i, tcode in enumerate(layout[floor], 1):
                    c.insert("rooms", {"hotel_id": hid, "room_type_id": types[tcode], "number": f"{floor}{i:02d}", "floor": str(floor),
                                       "wing": "Main", "hk_status": "inspected"})
        hid = hotels[0]
        # staff
        staff = [("admin@demo.ehms", "Demo Administrator", "super_admin", True), ("gm@demo.ehms", "Ngozi Adebayo (GM)", "general_manager", True),
                 ("fom@demo.ehms", "Emeka Uzor (Front Office Mgr)", "front_office_manager", False),
                 ("frontdesk@demo.ehms", "Blessing Okafor (Receptionist)", "receptionist", False),
                 ("reservations@demo.ehms", "Kemi Ajayi (Reservations)", "reservations_officer", False),
                 ("finance@demo.ehms", "Ibrahim Musa (Finance Mgr)", "finance_manager", True),
                 ("accounts@demo.ehms", "Joy Etim (Accountant)", "accountant", False),
                 ("hkmanager@demo.ehms", "Patience Douglas (HK Mgr)", "housekeeping_manager", False),
                 ("housekeeper@demo.ehms", "Mary Iwu (Housekeeper)", "housekeeping_staff", False),
                 ("housekeeper2@demo.ehms", "Esther Ojo (Housekeeper)", "housekeeping_staff", False),
                 ("auditor@demo.ehms", "Daniel Ikeh (Auditor)", "auditor", True)]
        users = {}
        for email, name, role, all_h in staff:
            uid = c.insert("users", {"organisation_id": org, "email": email, "full_name": name, "password_hash": security.hash_password(DEMO_PASSWORD),
                                     "all_hotels": 1 if all_h else 0, "created_at": now_iso(), "password_changed_at": now_iso()})
            c.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", [uid, roles[role]])
            if not all_h:
                c.execute("INSERT INTO user_hotels (user_id, hotel_id) VALUES (?, ?)", [uid, hid])
            users[role] = uid
        guests = []
        for i, (fn, ln, city) in enumerate(GUESTS):
            guests.append(c.insert("guests", {"organisation_id": org, "first_name": fn, "last_name": ln, "email": f"{fn.lower()}.{ln.lower()}@example.com",
                                              "phone": f"+234 80{i:02d} 555 {1000 + i}", "nationality": "British" if city == "London" else "Nigerian",
                                              "address": f"{city}", "vip": 1 if i in (4, 7) else 0, "marketing_consent": 1 if i % 2 == 0 else 0,
                                              "company": "Delta Energy Services Ltd (demo)" if i in (3, 9) else None,
                                              "preferences": "High floor, extra pillows" if i in (0, 7) else None, "created_at": now_iso()}))
    # operational history (separate transactions, using real posting logic)
    with db.tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        today = hotel_today(hotel)
        c.update("hotels", hid, {"business_date": today.isoformat()})
        hotel["business_date"] = today.isoformat()
        rooms = {r["number"]: r for r in c.all("SELECT * FROM rooms WHERE hotel_id = ?", [hid])}
        rt = {t["code"]: t for t in c.all("SELECT * FROM room_types WHERE hotel_id = ?", [hid])}
        cash = c.one("SELECT * FROM payment_methods WHERE hotel_id = ? AND code = 'CASH'", [hid])
        pos = c.one("SELECT * FROM payment_methods WHERE hotel_id = ? AND code = 'POS'", [hid])
        fd = users["receptionist"]

        def res(guest_idx, tcode, room_no, arr_off, nights, status, source="front_desk", btype="individual", adults=2, requests=None):
            arrival = today + dt.timedelta(days=arr_off)
            ref = next_number(c, hid, "reservation", "RES")
            rid = c.insert("reservations", {"hotel_id": hid, "reference": ref, "guest_id": guests[guest_idx], "status": status,
                                            "booking_type": btype, "source": source, "arrival": arrival.isoformat(),
                                            "departure": (arrival + dt.timedelta(days=nights)).isoformat(), "adults": adults, "children": 0,
                                            "room_type_id": rt[tcode]["id"], "room_id": rooms[room_no]["id"] if room_no else None,
                                            "nightly_rate": rt[tcode]["base_rate"], "rate_overridden": 0, "discount_amount": 0, "deposit_required": 0,
                                            "special_requests": requests, "created_by": fd, "created_at": now_iso(), "updated_at": now_iso()})
            return c.one("SELECT * FROM reservations WHERE id = ?", [rid])

        def pay(folio, method, amount, ref):
            je = post_journal(c, hid, today, f"Payment {method['name']} on {folio['number']}", "payment", ref, [
                (method["account_id"], amount, 0, None, "demo payment"), (account_id(c, org, "guest_ledger"), 0, amount, None, "demo payment")], fd)
            pid = c.insert("payments", {"hotel_id": hid, "folio_id": folio["id"], "method_id": method["id"], "kind": "payment", "amount": amount,
                                        "currency": "NGN", "status": "completed", "reference": ref, "idempotency_key": f"demo-{ref}",
                                        "received_by": fd, "journal_entry_id": je, "created_at": now_iso()})
            c.insert("folio_lines", {"folio_id": folio["id"], "business_date": today.isoformat(), "kind": "payment", "department": "payment",
                                     "description": f"Payment — {method['name']} ({ref})", "quantity": 1, "net_amount": amount, "tax_amount": 0,
                                     "service_charge": 0, "total_amount": amount, "reference": ref, "payment_id": pid, "journal_entry_id": je,
                                     "posted_by": fd, "posted_at": now_iso()})

        # in-house guests (arrived in the past, room nights posted up to yesterday)
        inhouse = [(0, "DLX", "106", -2, 4), (3, "EXE", "208", -1, 3), (7, "JST", "307", -3, 3), (9, "STD", "101", -1, 2), (5, "DLX", "204", -2, 2)]
        for gi, tcode, room_no, off, nights in inhouse:
            r = res(gi, tcode, room_no, off, nights, "checked_in", btype="corporate" if gi in (3, 9) else "individual", requests="Late check-out if possible" if gi == 7 else None)
            c.update("reservations", r["id"], {"checked_in_at": now_iso()})
            c.update("rooms", rooms[room_no]["id"], {"occupancy": "occupied"})
            folio = ensure_folio(c, r)
            for n in range(-off):
                post_room_night(c, None, hotel, c.one("SELECT * FROM reservations WHERE id = ?", [r["id"]]), folio,
                                dt.date.fromisoformat(r["arrival"]) + dt.timedelta(days=n))
            if gi in (0, 7):
                post_charge(c, None, hotel, folio, "fnb", "Restaurant dinner — table 12", 2850000, 1, "DEMO-POS-1001", today - dt.timedelta(days=1))
            if gi == 7:
                post_charge(c, None, hotel, folio, "laundry", "Laundry — 6 items", 900000, 1, "DEMO-LDY-55", today - dt.timedelta(days=1))
            if gi in (0, 3):
                pay(folio, pos if gi == 0 else cash, 10000000, f"DEMO-{r['reference']}")
        # arrivals today
        res(1, "STD", "102", 0, 2, "confirmed", "phone", requests="Airport pickup at 15:00")
        res(4, "PRS", "403", 0, 3, "confirmed", "corporate", "vip")
        res(6, "DLX", None, 0, 1, "confirmed", "website")
        res(10, "EXE", "303", 0, 2, "tentative", "email")
        # future
        res(2, "DLX", "107", 2, 3, "confirmed", "booking_engine")
        res(8, "JST", None, 4, 2, "confirmed", "travel_agent", "travel_agent")
        res(11, "STD", None, 7, 5, "tentative", "booking_engine", adults=1)
        res(1, "EXE", None, 10, 2, "waitlisted", "phone")
        # past stays (checked out) for history
        for gi, tcode, room_no, off in ((2, "STD", "103", -9), (5, "STD", "105", -6), (6, "STD", "104", -5)):
            r = res(gi, tcode, room_no, off, 2, "checked_in")
            folio = ensure_folio(c, r)
            for n in range(2):
                post_room_night(c, None, hotel, r, folio, dt.date.fromisoformat(r["arrival"]) + dt.timedelta(days=n))
            bal = c.scalar("SELECT COALESCE(SUM(total_amount),0) FROM folio_lines WHERE folio_id = ? AND kind = 'charge'", [folio["id"]])
            pay(folio, cash, bal, f"DEMO-{r['reference']}-SETTLE")
            c.update("folios", folio["id"], {"status": "closed", "closed_at": now_iso()})
            c.update("reservations", r["id"], {"status": "checked_out", "checked_in_at": now_iso(), "checked_out_at": now_iso()})
        # rooms needing housekeeping
        for no in ("103", "105"):
            c.update("rooms", rooms[no]["id"], {"hk_status": "dirty"})
            c.insert("housekeeping_tasks", {"hotel_id": hid, "room_id": rooms[no]["id"], "task_type": "checkout_clean", "status": "pending", "priority": 1,
                                            "assigned_to": users["housekeeping_staff"], "business_date": today.isoformat(), "created_at": now_iso()})
        c.update("rooms", rooms["104"]["id"], {"hk_status": "clean"})
        c.insert("housekeeping_tasks", {"hotel_id": hid, "room_id": rooms["104"]["id"], "task_type": "checkout_clean", "status": "completed",
                                        "priority": 1, "assigned_to": users["housekeeping_staff"], "business_date": today.isoformat(),
                                        "created_at": now_iso(), "started_at": now_iso(), "completed_at": now_iso()})
        c.update("rooms", rooms["205"]["id"], {"service_status": "maintenance", "service_note": "Air-conditioner compressor replacement (demo)"})


if __name__ == "__main__":  # pragma: no cover
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("bootstrap")
    for a in ("org", "org-code", "hotel", "hotel-code", "admin-email", "admin-name"):
        b.add_argument(f"--{a}", required=True)
    sub.add_parser("demo")
    args = p.parse_args()
    if args.cmd == "bootstrap":
        out = bootstrap(args.org, args.org_code, args.hotel, args.hotel_code, args.admin_email, args.admin_name)
        print(f"Created organisation and hotel. Sign in as {out['admin_email']} with temporary password: {out['temporary_password']}")
    else:
        seed_demo()
        print(f"Demo data loaded. Sign in as admin@demo.ehms / {DEMO_PASSWORD}")
