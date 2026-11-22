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
        existing = c.one("SELECT id FROM organisations WHERE code = 'DEMO'")
    if existing:
        from .rbac import apply_permission_upgrades
        with db.tx() as c:
            seed_chart_of_accounts(c, existing["id"])
            apply_permission_upgrades(c, existing["id"])
        _upgrade_demo(existing["id"])
        return
    with db.tx() as c:
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
                 ("auditor@demo.ehms", "Daniel Ikeh (Auditor)", "auditor", True),
                 ("fnbmanager@demo.ehms", "Tolu Bankole (Restaurant Mgr)", "restaurant_manager", False),
                 ("cashier@demo.ehms", "Chika Obi (Restaurant Cashier)", "restaurant_cashier", False),
                 ("waiter@demo.ehms", "Sani Bello (Waiter)", "waiter", False),
                 ("chef@demo.ehms", "Funmi Lawal (Chef)", "chef", False),
                 ("stores@demo.ehms", "Musa Garba (Storekeeper)", "storekeeper", False),
                 ("inventory@demo.ehms", "Grace Udo (Inventory Mgr)", "inventory_manager", False),
                 ("procurement@demo.ehms", "Yemi Alade (Procurement)", "procurement_officer", False),
                 ("hrmanager@demo.ehms", "Amaka Eze (HR Mgr)", "hr_manager", False),
                 ("hrofficer@demo.ehms", "Tunde Ola (HR Officer)", "hr_officer", False)]
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
    seed_fnb_and_stores(hid, org, users)
    seed_finance_demo(hid, org, users)
    seed_hr_demo(hid, org)


def seed_hr_demo(hid: int, org: int) -> None:
    """Release 0.6 demo: laundry price list, shift patterns and an employee record for every demo staff account."""
    import datetime as _dt
    from .modules.hr import ensure_leave_types
    from .services import business_date, next_number
    prices = [("Shirt", "wash_iron", 150000), ("Trousers", "wash_iron", 200000), ("Dress", "wash_iron", 250000), ("Suit (2-piece)", "dry_clean", 600000),
              ("Native attire (agbada)", "dry_clean", 800000), ("Underwear", "wash_only", 50000), ("Shirt", "iron_only", 80000), ("Bed sheet", "wash_iron", 0)]
    pay = {"general_manager": ("admin", "General Manager", 150_000_000), "front_office_manager": ("front_office", "Front Office Manager", 45_000_000),
           "receptionist": ("front_office", "Receptionist", 18_000_000), "reservations_officer": ("front_office", "Reservations Officer", 18_000_000),
           "finance_manager": ("finance", "Finance Manager", 60_000_000), "accountant": ("finance", "Accountant", 30_000_000),
           "housekeeping_manager": ("housekeeping", "Executive Housekeeper", 35_000_000), "housekeeping_staff": ("housekeeping", "Room Attendant", 12_000_000),
           "restaurant_manager": ("fnb", "Restaurant Manager", 35_000_000), "restaurant_cashier": ("fnb", "Cashier", 14_000_000), "waiter": ("fnb", "Waiter", 11_000_000),
           "chef": ("kitchen", "Head Chef", 40_000_000), "storekeeper": ("admin", "Storekeeper", 15_000_000), "inventory_manager": ("admin", "Inventory Manager", 30_000_000),
           "procurement_officer": ("admin", "Procurement Officer", 25_000_000), "hr_manager": ("hr", "HR Manager", 45_000_000), "hr_officer": ("hr", "HR Officer", 20_000_000)}
    with get_db().tx() as c:
        if c.one("SELECT id FROM laundry_prices WHERE hotel_id = ?", [hid]):
            return
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        on = business_date(hotel)
        for item, svc, price in prices:
            c.insert("laundry_prices", {"hotel_id": hid, "item": item, "service": svc, "price": price, "active": 1})
        shifts = {name: c.insert("shift_templates", {"hotel_id": hid, "name": name, "start_time": a, "end_time": b})
                  for name, a, b in (("Morning", "07:00", "15:00"), ("Afternoon", "15:00", "23:00"), ("Night", "23:00", "07:00"))}
        ensure_leave_types(c, hid)
        users = c.all("SELECT u.id, u.full_name, u.email, ro.code AS role FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles ro ON ro.id = ur.role_id "
                      "WHERE u.organisation_id = ? ORDER BY u.id", [org])
        monday = on - _dt.timedelta(days=on.weekday())
        for i, u in enumerate(users):
            if u["role"] not in pay or c.one("SELECT id FROM employees WHERE user_id = ?", [u["id"]]):
                continue
            dept, position, gross = pay[u["role"]]
            name = u["full_name"].split(" (")[0].split(" ")
            eid = c.insert("employees", {"hotel_id": hid, "employee_no": next_number(c, hid, "employee", "EMP", 4), "user_id": u["id"], "first_name": name[0],
                                         "last_name": " ".join(name[1:]) or "Staff", "email": u["email"], "department": dept, "position": position,
                                         "employment_type": "full_time", "hire_date": (on - _dt.timedelta(days=200 + 30 * i)).isoformat(), "status": "active",
                                         "basic_salary": gross * 50 // 100, "housing_allowance": gross * 25 // 100, "transport_allowance": gross * 15 // 100,
                                         "other_allowance": gross * 10 // 100, "bank_name": "Demo Bank", "bank_account_number": f"30{u['id']:08d}",
                                         "tax_id": f"TIN-DEMO-{u['id']:04d}", "pension_pfa": "Demo Pensions Ltd", "pension_pin": f"PEN{u['id']:09d}", "created_at": now_iso()})
            for d in range(6):
                c.insert("shift_assignments", {"employee_id": eid, "work_date": (monday + _dt.timedelta(days=d)).isoformat(),
                                               "shift_id": shifts["Afternoon" if dept in ("fnb", "kitchen") else "Morning"]})


def seed_finance_demo(hid: int, org: int, users: dict) -> None:
    """Release 0.5 demo: a booking-engine promo code, this year's revenue/expense budget and two expense claims."""
    import datetime as _dt
    from .services import business_date, next_number
    with get_db().tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        on = business_date(hotel)
        c.insert("promo_codes", {"hotel_id": hid, "code": "WELCOME10", "description": "10% off the room for direct online bookings (demo)",
                                 "discount_type": "percent", "value": 10, "valid_from": on.isoformat(), "valid_to": (on + _dt.timedelta(days=365)).isoformat(),
                                 "min_nights": 1, "active": 1, "created_by": users.get("general_manager"), "created_at": now_iso()})
        acct = {r["system_key"]: r["id"] for r in c.all("SELECT id, system_key FROM accounts WHERE organisation_id = ? AND system_key IS NOT NULL", [org])}
        for key, monthly in (("rev_room", 1_500_000_000), ("rev_fnb", 400_000_000), ("exp_utilities", 120_000_000), ("exp_food", 150_000_000), ("exp_supplies", 40_000_000)):
            for m in range(1, 13):
                c.insert("budget_lines", {"hotel_id": hid, "account_id": acct[key], "period": f"{on.year}-{m:02d}", "amount": monthly})
        for dept, key, amount, desc, payee, who in (("maintenance", "exp_maintenance", 4_500_000, "Generator servicing — emergency call-out (demo)", "PowerFix Ltd", "general_manager"),
                                                    ("housekeeping", "exp_supplies", 1_850_000, "Extra cleaning chemicals for deep clean (demo)", "Market purchase", "housekeeping_manager")):
            c.insert("expense_claims", {"hotel_id": hid, "number": next_number(c, hid, "expense", "EXP"), "department": dept, "account_id": acct[key],
                                        "description": desc, "payee": payee, "amount": amount, "status": "submitted", "requested_by": users.get(who) or users["general_manager"],
                                        "expense_date": on.isoformat(), "created_at": now_iso()})


NEW_DEMO_STAFF_04 = [("fnbmanager@demo.ehms", "Tolu Bankole (Restaurant Mgr)", "restaurant_manager"),
                     ("cashier@demo.ehms", "Chika Obi (Restaurant Cashier)", "restaurant_cashier"), ("waiter@demo.ehms", "Sani Bello (Waiter)", "waiter"),
                     ("chef@demo.ehms", "Funmi Lawal (Chef)", "chef"), ("stores@demo.ehms", "Musa Garba (Storekeeper)", "storekeeper"),
                     ("inventory@demo.ehms", "Grace Udo (Inventory Mgr)", "inventory_manager"),
                     ("procurement@demo.ehms", "Yemi Alade (Procurement)", "procurement_officer"),
                     ("hrmanager@demo.ehms", "Amaka Eze (HR Mgr)", "hr_manager"), ("hrofficer@demo.ehms", "Tunde Ola (HR Officer)", "hr_officer")]


NEW_DEMO_STAFF_06 = [("hrmanager@demo.ehms", "Amaka Eze (HR Mgr)", "hr_manager"), ("hrofficer@demo.ehms", "Tunde Ola (HR Officer)", "hr_officer")]


def _add_new_staff(org: int, hid: int, staff: list) -> None:
    with get_db().tx() as c:
        roles = seed_permissions_and_roles(c, org)
        for email, name, role in staff:
            if c.one("SELECT id FROM users WHERE email = ?", [email]):
                continue
            uid = c.insert("users", {"organisation_id": org, "email": email, "full_name": name, "password_hash": security.hash_password(DEMO_PASSWORD),
                                     "all_hotels": 0, "created_at": now_iso(), "password_changed_at": now_iso()})
            c.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", [uid, roles[role]])
            c.execute("INSERT INTO user_hotels (user_id, hotel_id) VALUES (?, ?)", [uid, hid])


def _upgrade_demo(org: int) -> None:
    """A demo database created by an earlier release: add the release 0.4 demo staff, stores, menu and suppliers once."""
    db = get_db()
    with db.tx() as c:
        hid = c.scalar("SELECT id FROM hotels WHERE organisation_id = ? AND code = 'CGL'", [org])
        if not hid:
            return
        if c.one("SELECT id FROM stores WHERE hotel_id = ?", [hid]):
            users = {r["code"]: r["uid"] for r in c.all("SELECT ro.code, MIN(u.id) AS uid FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                                                        "JOIN roles ro ON ro.id = ur.role_id WHERE u.organisation_id = ? GROUP BY ro.code", [org])}
            needs_05 = not c.one("SELECT id FROM promo_codes WHERE hotel_id = ?", [hid])
        else:
            needs_05 = None
    if needs_05 is not None:
        if needs_05:
            seed_finance_demo(hid, org, users)
            print("Added release 0.5 demo data (promo code, budget, expense claims).")
        _add_new_staff(org, hid, NEW_DEMO_STAFF_06)
        seed_hr_demo(hid, org)
        return
    with db.tx() as c:
        roles = seed_permissions_and_roles(c, org)
        users = {r["code"]: r["uid"] for r in c.all("SELECT ro.code, MIN(u.id) AS uid FROM users u JOIN user_roles ur ON ur.user_id = u.id "
                                                    "JOIN roles ro ON ro.id = ur.role_id WHERE u.organisation_id = ? GROUP BY ro.code", [org])}
        for email, name, role in NEW_DEMO_STAFF_04:
            if c.one("SELECT id FROM users WHERE email = ?", [email]):
                continue
            uid = c.insert("users", {"organisation_id": org, "email": email, "full_name": name, "password_hash": security.hash_password(DEMO_PASSWORD),
                                     "all_hotels": 0, "created_at": now_iso(), "password_changed_at": now_iso()})
            c.execute("INSERT INTO user_roles (user_id, role_id) VALUES (?, ?)", [uid, roles[role]])
            c.execute("INSERT INTO user_hotels (user_id, hotel_id) VALUES (?, ?)", [uid, hid])
            users[role] = uid
    seed_fnb_and_stores(hid, org, users)
    seed_finance_demo(hid, org, users)
    seed_hr_demo(hid, org)
    print("Added release 0.4 demo data (outlets, menu, stores, suppliers) to the existing demo organisation.")


# ------------------------------------------------------------------ release 0.4 demo: stores, menu, suppliers
STORES = [("MAIN", "Main Store", "main"), ("KIT", "Kitchen Store", "kitchen"), ("BAR", "Bar Store", "bar"), ("HSK", "Housekeeping Store", "housekeeping")]
# code, name, category, unit, unit cost (kobo), reorder level, reorder qty, track expiry, {store: opening qty}
ITEMS = [
    ("RICE", "Rice (parboiled)", "food", "kg", 150000, 20, 50, 0, {"MAIN": 100, "KIT": 25}),
    ("CHKN", "Chicken (whole, frozen)", "food", "kg", 450000, 10, 30, 1, {"MAIN": 40, "KIT": 15}),
    ("BEEF", "Beef (boneless)", "food", "kg", 550000, 8, 20, 1, {"MAIN": 25, "KIT": 10}),
    ("TOM", "Tomato paste", "food", "kg", 200000, 5, 15, 1, {"MAIN": 20, "KIT": 6}),
    ("OIL", "Vegetable oil", "food", "litre", 250000, 10, 20, 0, {"MAIN": 40, "KIT": 10}),
    ("PLNT", "Plantain", "food", "kg", 120000, 10, 30, 0, {"KIT": 20}),
    ("FISH", "Croaker fish", "food", "kg", 600000, 5, 15, 1, {"MAIN": 15, "KIT": 6}),
    ("YAM", "Yam", "food", "kg", 100000, 10, 30, 0, {"MAIN": 50, "KIT": 12}),
    ("EGG", "Eggs", "food", "piece", 15000, 60, 180, 1, {"KIT": 120}),
    ("BRD", "Bread loaf", "food", "piece", 120000, 10, 20, 1, {"KIT": 12}),
    ("SDRK", "Soft drink (35cl)", "beverage", "bottle", 25000, 48, 120, 1, {"MAIN": 120, "BAR": 60}),
    ("WATR", "Table water (75cl)", "beverage", "bottle", 20000, 48, 120, 0, {"MAIN": 200, "BAR": 80}),
    ("BEER", "Lager beer (60cl)", "beverage", "bottle", 70000, 48, 96, 1, {"MAIN": 96, "BAR": 48}),
    ("WINE", "House red wine (75cl)", "beverage", "bottle", 800000, 6, 12, 0, {"MAIN": 18, "BAR": 6}),
    ("JUIC", "Orange juice (1L)", "beverage", "carton", 180000, 10, 24, 1, {"BAR": 12, "MAIN": 24}),
    ("SOAP", "Guest soap (40g)", "toiletries", "piece", 15000, 200, 500, 0, {"HSK": 400, "MAIN": 600}),
    ("SHMP", "Shampoo sachet", "toiletries", "piece", 12000, 200, 500, 0, {"HSK": 350}),
    ("TOWL", "Bath towel", "linen", "piece", 650000, 40, 60, 0, {"HSK": 80}),
    ("DTRG", "Laundry detergent", "cleaning", "kg", 180000, 10, 25, 0, {"HSK": 30, "MAIN": 20}),
    ("DSL", "Diesel (generator)", "fuel", "litre", 120000, 500, 2000, 0, {"MAIN": 1500}),
]
# category, kind, items: code, name, price (kobo), station, recipe [(item code, qty per portion)]
MENU = [
    ("Mains", "food", [("JRC", "Jollof rice & chicken", 850000, "kitchen", [("RICE", 0.2), ("CHKN", 0.3), ("TOM", 0.03), ("OIL", 0.03)]),
                       ("FRC", "Fried rice & beef", 900000, "kitchen", [("RICE", 0.2), ("BEEF", 0.2), ("OIL", 0.03)]),
                       ("PFS", "Peppered croaker fish", 1200000, "grill", [("FISH", 0.5), ("OIL", 0.02)]),
                       ("YPE", "Yam & egg sauce", 650000, "kitchen", [("YAM", 0.4), ("EGG", 2), ("TOM", 0.02), ("OIL", 0.02)])]),
    ("Sides", "food", [("DOD", "Fried plantain (dodo)", 250000, "kitchen", [("PLNT", 0.25), ("OIL", 0.02)]),
                       ("TST", "Toast & butter", 200000, "kitchen", [("BRD", 0.25)])]),
    ("Soft drinks", "beverage", [("SDK", "Soft drink", 100000, "bar", [("SDRK", 1)]),
                                 ("WTR", "Table water", 80000, "bar", [("WATR", 1)]),
                                 ("OJ", "Fresh orange juice (glass)", 180000, "bar", [("JUIC", 0.25)])]),
    ("Beer & wine", "beverage", [("LGR", "Lager beer", 200000, "bar", [("BEER", 1)]),
                                 ("RWG", "House red wine (glass)", 350000, "bar", [("WINE", 0.2)]),
                                 ("RWB", "House red wine (bottle)", 2400000, "bar", [("WINE", 1)])]),
]
SUPPLIERS = [("SUP001", "Lagos Fresh Foods Ltd (demo)", "Food", "Adaeze Nnaji", 500, 30),
             ("SUP002", "Victoria Beverages Distributors (demo)", "Beverages", "Kunle Afolabi", 500, 14),
             ("SUP003", "CleanPro Supplies Nig. (demo)", "Housekeeping", "Hauwa Sule", 500, 30),
             ("SUP004", "PowerFuel Energy (demo)", "Fuel", "Obinna Eze", 500, 7)]


def seed_fnb_and_stores(hid: int, org: int, users: dict) -> None:
    """Stores with opening stock (posted through the real stock ledger and journal), outlets, tables,
    menu with recipes, suppliers and one approved purchase order awaiting delivery."""
    from .services import account_id, business_date, post_journal
    from .stock import apply_movement
    import datetime as _dt
    db = get_db()
    with db.tx() as c:
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        on = business_date(hotel)
        stores = {code: c.insert("stores", {"hotel_id": hid, "code": code, "name": name, "kind": kind, "allow_negative": 0, "active": 1})
                  for code, name, kind in STORES}
        store_rows = {code: c.one("SELECT * FROM stores WHERE id = ?", [sid]) for code, sid in stores.items()}
        items = {}
        opening_value = 0
        for code, name, cat, unit, cost, rl, rq, exp, qtys in ITEMS:
            iid = c.insert("inventory_items", {"hotel_id": hid, "code": code, "name": name, "category": cat, "unit": unit, "last_cost": cost,
                                               "reorder_level_milli": rl * 1000, "reorder_qty_milli": rq * 1000, "track_expiry": exp, "active": 1,
                                               "created_at": now_iso()})
            items[code] = c.one("SELECT * FROM inventory_items WHERE id = ?", [iid])
            for scode, q in qtys.items():
                expiry = (on + _dt.timedelta(days=12 if code in ("BRD", "EGG") else 120)).isoformat() if exp else None
                value = cost * q
                apply_movement(c, hid, items[code], store_rows[scode], "opening", q * 1000, value, "opening", "OPENING", users["storekeeper"], on,
                               reason="Opening balance (demo)", batch_no="OPEN-1" if exp else None, expiry_date=expiry)
                opening_value += value
        post_journal(c, hid, on, "Opening stock balances (demo)", "inventory", "OPENING", [
            (account_id(c, org, "inventory"), opening_value, 0, None, "Opening stock"),
            (account_id(c, org, "equity"), 0, opening_value, None, "Opening stock")], users["storekeeper"])
        outlets = {}
        for code, name, kind, store in (("REST", "Savanna Restaurant", "restaurant", "KIT"), ("BAR", "Lagoon Bar", "bar", "BAR"),
                                        ("RSV", "In-Room Dining", "room_service", "KIT")):
            outlets[code] = c.insert("outlets", {"hotel_id": hid, "code": code, "name": name, "kind": kind, "store_id": stores[store], "active": 1})
        for i in range(1, 11):
            c.insert("pos_tables", {"outlet_id": outlets["REST"], "code": f"T{i}", "area": "Terrace" if i > 7 else "Main hall", "seats": 2 if i % 3 == 0 else 4, "active": 1})
        for i in range(1, 7):
            c.insert("pos_tables", {"outlet_id": outlets["BAR"], "code": f"B{i}", "area": "Bar", "seats": 2, "active": 1})
        for sort, (cat, kind, entries) in enumerate(MENU):
            cid = c.insert("menu_categories", {"hotel_id": hid, "name": cat, "kind": kind, "sort_order": sort, "active": 1})
            for code, name, price, station, recipe in entries:
                mid = c.insert("menu_items", {"hotel_id": hid, "category_id": cid, "code": code, "name": name, "price": price, "station": station,
                                              "issue_store_id": stores["BAR"] if kind == "beverage" else None, "available": 1, "active": 1})
                for icode, q in recipe:
                    c.insert("recipe_lines", {"menu_item_id": mid, "item_id": items[icode]["id"], "quantity_milli": int(round(q * 1000))})
        sup = {}
        for code, name, cat, contact, wht, terms in SUPPLIERS:
            sup[code] = c.insert("suppliers", {"organisation_id": org, "code": code, "name": name, "category": cat, "contact_name": contact,
                                               "phone": "+234 800 000 0000", "email": f"{code.lower()}@supplier.demo", "tax_id": f"TIN-DEMO-{code[-3:]}",
                                               "bank_name": "Demo Bank", "bank_account_name": name, "bank_account_number": f"00{code[-3:]}123456",
                                               "payment_terms_days": terms, "wht_bp": wht, "active": 1, "created_at": now_iso()})
        # an approved purchase order awaiting delivery (ready to receive in the demo)
        po_id = c.insert("purchase_orders", {"hotel_id": hid, "number": f"PO-{hotel['code']}-DEMO01", "supplier_id": sup["SUP001"], "store_id": stores["MAIN"],
                                             "status": "approved", "order_date": on.isoformat(),
                                             "expected_date": (on + _dt.timedelta(days=2)).isoformat(), "total": 0,
                                             "approval_level": "standard", "note": "Weekly fresh food order (demo)", "created_by": users["procurement_officer"],
                                             "approved_by": users["finance_manager"], "created_at": now_iso(), "approved_at": now_iso()})
        total = 0
        for icode, q in (("CHKN", 30), ("RICE", 50), ("FISH", 10)):
            it = items[icode]
            c.insert("purchase_order_lines", {"po_id": po_id, "item_id": it["id"], "description": it["name"], "quantity_milli": q * 1000, "unit_cost": it["last_cost"]})
            total += q * it["last_cost"]
        c.update("purchase_orders", po_id, {"total": total})


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
