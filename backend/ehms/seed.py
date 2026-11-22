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
                 ("hrofficer@demo.ehms", "Tunde Ola (HR Officer)", "hr_officer", False),
                 ("maintenance@demo.ehms", "Segun Adeyemi (Maintenance Mgr)", "maintenance_manager", False),
                 ("technician@demo.ehms", "Ifeanyi Okeke (Technician)", "maintenance_technician", False),
                 ("security@demo.ehms", "Bala Usman (Security)", "security_officer", False),
                 ("sales@demo.ehms", "Zainab Lawal (Sales Mgr)", "sales_manager", False),
                 ("marketing@demo.ehms", "Ngozi Okon (Marketing Mgr)", "marketing_manager", False),
                 ("guestservice@demo.ehms", "Femi Ade (Guest Service)", "customer_service_officer", False)]
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
    seed_operations_demo(hid, org)
    seed_crm_demo(hid, org)
    seed_bi_demo(hid, org)


def _demo_pdf(title: str, lines: list[str]) -> bytes:
    import io as _io
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    buf = _io.BytesIO()
    cv = canvas.Canvas(buf, pagesize=A4)
    cv.setFont("Helvetica-Bold", 16)
    cv.drawString(60, 780, title)
    cv.setFont("Helvetica", 11)
    for i, ln in enumerate(lines):
        cv.drawString(60, 750 - i * 18, ln)
    cv.showPage()
    cv.save()
    return buf.getvalue()


def seed_bi_demo(hid: int, org: int) -> None:
    """Release 0.9 demo: hotel and supplier documents, two scheduled reports and a first unusual-transaction scan."""
    import json as _json
    from .modules.documents import store_document
    with get_db().tx() as c:
        if c.one("SELECT id FROM report_schedules WHERE hotel_id = ?", [hid]):
            return
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        uid = {r["code"]: r["uid"] for r in c.all("SELECT ro.code, MIN(u.id) AS uid FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles ro ON ro.id = ur.role_id "
                                                   "WHERE u.organisation_id = ? GROUP BY ro.code", [org])}
        gm = uid["general_manager"]
        store_document(c, org_id=org, hotel_id=hid, entity_type="hotel", entity_id=hid, category="licence", title="Hotel operating licence 2026 (demo)",
                       filename="operating-licence-2026.pdf", user_id=gm,
                       data=_demo_pdf("Operating licence (demo document)", ["Lagos State Tourism — hotel operating licence", "Licence no. DEMO-0001",
                                                                            "Valid 1 January 2026 – 31 December 2026", "This is sample data for the EHMS demo."]))
        store_document(c, org_id=org, hotel_id=hid, entity_type="hotel", entity_id=hid, category="policy", title="Guest data protection policy (demo)",
                       filename="data-protection-policy.pdf", user_id=gm,
                       data=_demo_pdf("Guest data protection policy (demo)", ["Personal data is processed under the Nigeria Data Protection Act 2023.",
                                                                              "Identity documents are visible only to authorised staff.", "Sample document."]))
        sup = c.one("SELECT id FROM suppliers WHERE organisation_id = ? ORDER BY id", [org])
        if sup:
            store_document(c, org_id=org, hotel_id=None, entity_type="supplier", entity_id=sup["id"], category="contract", title="Supply agreement (demo)",
                           filename="supply-agreement.pdf", user_id=uid.get("procurement_officer") or gm,
                           data=_demo_pdf("Supply agreement (demo)", ["Payment terms 30 days; prices fixed for 6 months.", "Sample document."]))
        fin = uid.get("finance_manager") or gm
        c.insert("report_schedules", {"hotel_id": hid, "name": "Weekly occupancy & ADR", "report_code": "occupancy", "params": "{}", "frequency": "weekly",
                                      "weekday": 0, "format": "pdf", "recipients": _json.dumps([gm] + ([uid["front_office_manager"]] if uid.get("front_office_manager") else [])),
                                      "active": 1, "created_by": gm, "created_at": now_iso()})
        c.insert("report_schedules", {"hotel_id": hid, "name": "Daily revenue", "report_code": "daily_revenue", "params": "{}", "frequency": "daily",
                                      "format": "xlsx", "recipients": _json.dumps([fin, gm]), "active": 1, "created_by": fin, "created_at": now_iso()})
        # a real manual cash entry, so the unusual-transaction scan has something to show in the demo
        from .services import account_id, business_date, post_journal
        post_journal(c, hid, business_date(hotel), "Petty cash top-up for generator diesel (demo)", "manual", "PC-DEMO-01",
                     [(account_id(c, org, "exp_fuel"), 4_500_000, 0, "maintenance", "Diesel"), (account_id(c, org, "cash"), 0, 4_500_000, None, "Petty cash")], fin)
        from .modules.insights import scan
        scan(c, hotel, 30)


def seed_crm_demo(hid: int, org: int) -> None:
    """Release 0.8 demo: corporate & agent accounts with negotiated rates, loyalty members, complaints, feedback,
    a festive season, a dynamic pricing rule awaiting approval, competitor rates, sales targets and a draft campaign."""
    import datetime as _dt
    import json as _json
    import secrets as _secrets
    from .services import business_date, next_number
    with get_db().tx() as c:
        if c.one("SELECT id FROM corporate_accounts WHERE organisation_id = ?", [org]):
            return
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        on = business_date(hotel)
        uid = {r["code"]: r["uid"] for r in c.all("SELECT ro.code, MIN(u.id) AS uid FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles ro ON ro.id = ur.role_id "
                                                   "WHERE u.organisation_id = ? GROUP BY ro.code", [org])}
        sales = uid.get("sales_manager") or uid["general_manager"]
        types = {t["code"]: t for t in c.all("SELECT * FROM room_types WHERE hotel_id = ?", [hid])}
        delta = c.insert("corporate_accounts", {"organisation_id": org, "code": "DELTA", "kind": "corporate", "name": "Delta Energy Services Ltd (demo)", "contact_name": "Kunle Adeyemi",
                                                "email": "travel@delta.demo", "phone": "+234 800 000 2222", "credit_limit": 500_000_000, "payment_terms_days": 30, "status": "active",
                                                "account_manager": sales, "created_at": now_iso()})
        c.insert("corporate_accounts", {"organisation_id": org, "code": "SKYTRV", "kind": "travel_agent", "name": "Skyline Travels (demo)", "contact_name": "Ada Obi",
                                        "email": "bookings@skyline.demo", "commission_bp": 1000, "status": "active", "account_manager": sales, "created_at": now_iso()})
        c.insert("corporate_accounts", {"organisation_id": org, "code": "NNPCL", "kind": "corporate", "name": "Northern Gas Ltd (demo prospect)", "status": "prospect",
                                        "account_manager": sales, "created_at": now_iso()})
        for code, rate in (("STD", 3_800_000), ("DLX", 5_200_000), ("EXE", 7_500_000)):
            if code in types:
                c.insert("corporate_rates", {"account_id": delta, "hotel_id": hid, "room_type_id": types[code]["id"], "rate": rate, "valid_from": on.replace(month=1, day=1).isoformat(),
                                             "valid_to": on.replace(month=12, day=31).isoformat()})
        guests = c.all("SELECT * FROM guests WHERE organisation_id = ? ORDER BY id", [org])
        for i, g in enumerate(guests[:6]):
            lifetime = [12_500, 3_200, 800, 31_000, 1_500, 0][i]
            tier = "platinum" if lifetime >= 30000 else "gold" if lifetime >= 10000 else "silver" if lifetime >= 2000 else "bronze"
            aid = c.insert("loyalty_accounts", {"guest_id": g["id"], "member_no": f"LYL{10000001 + i}", "points_balance": lifetime // 2, "lifetime_points": lifetime, "tier": tier,
                                                "active": 1, "enrolled_at": now_iso()})
            if lifetime:
                c.insert("loyalty_transactions", {"account_id": aid, "hotel_id": hid, "kind": "earn", "points": lifetime // 2, "balance_after": lifetime // 2, "reference": "HISTORY",
                                                  "description": "Points from previous stays (demo)", "created_at": now_iso()})
        rooms = {r["number"]: r["id"] for r in c.all("SELECT id, number FROM rooms WHERE hotel_id = ?", [hid])}
        for cat, prio, desc, status, hours_ago, res in (("noise", "high", "Loud music from the bar until 2am (demo)", "open", 3, None),
                                                         ("billing", "normal", "Minibar charged twice (demo)", "resolved", 30, "Duplicate charge reversed; apology given"),
                                                         ("cleanliness", "normal", "Bathroom not cleaned on day 2 (demo)", "in_progress", 10, None)):
            created = (_dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(hours=hours_ago)).replace(microsecond=0)
            c.insert("complaints", {"hotel_id": hid, "number": next_number(c, hid, "complaint", "CMP"), "guest_id": guests[1]["id"] if guests else None, "room_id": rooms.get("106"),
                                    "channel": "in_person", "category": cat, "department": {"noise": "front_office", "billing": "finance", "cleanliness": "housekeeping"}[cat],
                                    "priority": prio, "description": desc, "status": status,
                                    "due_at": (created + _dt.timedelta(hours=8 if prio == "high" else 24)).isoformat().replace("+00:00", "Z"),
                                    "first_response_at": (created + _dt.timedelta(minutes=40)).isoformat().replace("+00:00", "Z") if status != "open" else None,
                                    "resolved_at": (created + _dt.timedelta(hours=5)).isoformat().replace("+00:00", "Z") if status == "resolved" else None,
                                    "resolution": res, "guest_satisfied": 1 if status == "resolved" else None,
                                    "reported_by": uid.get("receptionist") or uid["general_manager"], "created_at": created.isoformat().replace("+00:00", "Z")})
        from .modules.crm import analyse
        for i, (ov, cl, sv, fd, nps, txt) in enumerate(((5, 5, 5, 4, 10, "Excellent stay, very friendly staff and a spotless room. Will recommend!"),
                                                        (4, 4, 5, 3, 8, "Great service at reception, breakfast was a bit cold."),
                                                        (2, 2, 3, 3, 3, "Room was dirty on arrival and the AC was noisy. Disappointing."),
                                                        (5, 4, 5, 5, 9, "Delicious food in the restaurant and comfortable bed."),
                                                        (3, 3, 2, 4, 6, "Check-in queue was slow, waited 30 minutes. Wifi poor."))):
            sentiment, themes = analyse(txt)
            c.insert("feedback", {"hotel_id": hid, "guest_id": guests[i]["id"] if i < len(guests) else None, "token": _secrets.token_urlsafe(16), "source": "survey",
                                  "overall": ov, "cleanliness": cl, "service": sv, "food": fd, "nps": nps, "comments": txt, "sentiment": sentiment, "themes": themes,
                                  "sent_at": now_iso(), "submitted_at": now_iso(), "created_at": now_iso()})
        # one survey invitation still awaiting the guest's answer
        c.insert("feedback", {"hotel_id": hid, "guest_id": guests[0]["id"] if guests else None, "token": _secrets.token_urlsafe(16), "source": "survey",
                              "sent_at": now_iso(), "created_at": now_iso()})
        c.insert("rate_seasons", {"hotel_id": hid, "name": "Festive season", "start_date": f"{on.year}-12-20", "end_date": f"{on.year + 1}-01-03", "adjustment_bp": 2000,
                                  "active": 1, "created_by": sales})
        c.insert("rate_rules", {"hotel_id": hid, "name": "High-demand uplift", "min_occupancy_pct": 80, "max_occupancy_pct": 100, "adjustment_bp": 1500, "status": "pending_approval",
                                "created_by": sales, "created_at": now_iso()})
        for d in range(0, 14, 2):
            day = (on + _dt.timedelta(days=d)).isoformat()
            for comp, rate in (("Lagoon View Hotel (demo)", 4_200_000 + d * 20_000), ("Island Suites (demo)", 5_000_000)):
                c.insert("competitor_rates", {"hotel_id": hid, "competitor": comp, "stay_date": day, "room_category": "Standard double", "rate": rate, "source": "OTA check",
                                              "recorded_by": sales, "recorded_at": now_iso()})
        period = on.strftime("%Y-%m")
        for metric, target in (("room_revenue", 3_500_000_000), ("rooms_sold", 450), ("fnb_revenue", 900_000_000), ("event_revenue", 1_000_000_000)):
            c.insert("sales_targets", {"hotel_id": hid, "period": period, "metric": metric, "target": target, "owner_id": sales})
        c.insert("campaigns", {"hotel_id": hid, "name": "Festive getaway offer (demo)", "channel": "email", "segment": _json.dumps({"min_stays": 1}),
                               "subject": "{guest}, celebrate the festive season at {hotel}", "body": "Dear {guest},\n\nEnjoy 10% off direct bookings with code {promo_code}.",
                               "promo_code": "WELCOME10", "status": "draft", "created_by": uid.get("marketing_manager") or sales, "created_at": now_iso()})


def seed_operations_demo(hid: int, org: int) -> None:
    """Release 0.7 demo: assets with preventive schedules, an open work order, venues and events, emergency contacts,
    a lost-property item."""
    import datetime as _dt
    from .services import business_date, next_number
    with get_db().tx() as c:
        if c.one("SELECT id FROM assets WHERE hotel_id = ?", [hid]):
            return
        hotel = c.one("SELECT * FROM hotels WHERE id = ?", [hid])
        on = business_date(hotel)
        uid = {r["code"]: r["uid"] for r in c.all("SELECT ro.code, MIN(u.id) AS uid FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN roles ro ON ro.id = ur.role_id "
                                                   "WHERE u.organisation_id = ? GROUP BY ro.code", [org])}
        tech = uid.get("maintenance_technician")
        rooms = {r["number"]: r["id"] for r in c.all("SELECT id, number FROM rooms WHERE hotel_id = ?", [hid])}
        assets = {}
        for code, name, cat, loc, cost, life, freq, due_in in (
                ("GEN-01", "Main diesel generator 500 kVA (demo)", "generator", "Power house", 4_500_000_000, 120, 30, 2),
                ("GEN-02", "Standby generator 250 kVA (demo)", "generator", "Power house", 2_200_000_000, 120, 30, 12),
                ("LIFT-01", "Passenger lift A (demo)", "elevator", "Main lobby", 3_800_000_000, 180, 90, 40),
                ("PUMP-01", "Borehole pump (demo)", "pump", "Water treatment room", 350_000_000, 60, 60, 20),
                ("AC-205", "Split AC unit room 205 (demo)", "air_conditioner", "Room 205", 85_000_000, 72, 90, 5),
                ("FIRE-01", "Fire extinguishers — floor 1 (demo)", "fire_safety", "Floor 1 corridors", 60_000_000, 60, 180, 75),
                ("CHILL-01", "Kitchen walk-in chiller (demo)", "refrigeration", "Main kitchen", 1_200_000_000, 96, 30, 1)):
            aid = c.insert("assets", {"hotel_id": hid, "code": code, "name": name, "category": cat, "location": loc, "room_id": rooms.get("205") if code == "AC-205" else None,
                                      "purchase_date": (on - _dt.timedelta(days=400)).isoformat(), "purchase_cost": cost, "useful_life_months": life,
                                      "warranty_until": (on + _dt.timedelta(days=200)).isoformat() if code in ("LIFT-01", "CHILL-01") else None,
                                      "status": "under_repair" if code == "AC-205" else "operational", "created_at": now_iso()})
            c.insert("maintenance_schedules", {"asset_id": aid, "title": {"generator": "Oil, filter and load test", "elevator": "Statutory lift inspection",
                                                                          "pump": "Pump service", "air_conditioner": "Filter clean & gas check", "fire_safety": "Extinguisher inspection",
                                                                          "refrigeration": "Coil clean & temperature log check"}[cat],
                                               "frequency_days": freq, "next_due": (on + _dt.timedelta(days=due_in)).isoformat(), "assigned_to": tech, "active": 1})
            assets[code] = aid
        c.insert("work_orders", {"hotel_id": hid, "number": next_number(c, hid, "work_order", "WO"), "asset_id": assets["AC-205"], "room_id": rooms.get("205"),
                                 "title": "Air-conditioner compressor replacement (demo)", "description": "Compressor failed; room blocked.", "kind": "corrective",
                                 "priority": "high", "status": "in_progress", "blocks_room": 1, "reported_by": uid.get("housekeeping_manager") or uid["general_manager"],
                                 "assigned_to": tech, "due_date": (on + _dt.timedelta(days=1)).isoformat(), "created_at": now_iso(), "started_at": now_iso()})
        if rooms.get("205"):
            c.execute("UPDATE rooms SET service_note = ? WHERE id = ? AND service_status = 'maintenance'", [f"WO-{hotel['code']}-000001: Air-conditioner compressor replacement (demo)", rooms["205"]])
        ball = c.insert("venues", {"hotel_id": hid, "code": "BALL", "name": "Grand Ballroom", "capacity_theatre": 400, "capacity_banquet": 300, "capacity_classroom": 200,
                                   "area_sqm": 520, "hourly_rate": 15_000_000, "daily_rate": 120_000_000, "facilities": "Stage, PA system, projector, dance floor", "active": 1})
        board = c.insert("venues", {"hotel_id": hid, "code": "BOARD", "name": "Executive Boardroom", "capacity_theatre": 0, "capacity_banquet": 0, "capacity_classroom": 16,
                                    "area_sqm": 60, "hourly_rate": 2_500_000, "daily_rate": 18_000_000, "facilities": "Video conferencing, smart TV", "active": 1})
        d1 = on + _dt.timedelta(days=14)
        for title, etype, client, company, venue, days, guests, status, items in (
                ("Okafor–Bello wedding reception (demo)", "wedding", "Chioma Okafor", None, ball, 14, 250, "confirmed",
                 [("venue", "Grand Ballroom — full day", 1, 120_000_000), ("catering", "Buffet dinner per guest", 250, 1_200_000), ("beverage", "Soft drinks & water package per guest", 250, 300_000),
                  ("decoration", "Floral décor & lighting", 1, 85_000_000)]),
                ("Delta Energy quarterly board meeting (demo)", "meeting", "Kunle Adeyemi", "Delta Energy Services Ltd (demo)", board, 21, 12, "enquiry",
                 [("venue", "Executive Boardroom — full day", 1, 18_000_000), ("catering", "Working lunch per guest", 12, 650_000)])):
            day = on + _dt.timedelta(days=days)
            eid = c.insert("events", {"hotel_id": hid, "number": next_number(c, hid, "event", "EVT"), "title": title, "event_type": etype, "status": "enquiry",
                                      "client_name": client, "client_phone": "+234 800 000 1111", "client_email": f"{client.split()[0].lower()}@example.com", "company": company,
                                      "start_at": f"{day.isoformat()}T10:00", "end_at": f"{day.isoformat()}T22:00" if etype == "wedding" else f"{day.isoformat()}T17:00",
                                      "expected_guests": guests, "layout": "banquet" if etype == "wedding" else "boardroom", "deposit_required": 150_000_000 if etype == "wedding" else 0,
                                      "sales_owner": uid.get("sales_manager"), "created_by": uid.get("sales_manager") or uid["general_manager"], "created_at": now_iso()})
            c.insert("event_venues", {"event_id": eid, "venue_id": venue, "start_at": f"{day.isoformat()}T08:00", "end_at": f"{day.isoformat()}T23:00" if etype == "wedding" else f"{day.isoformat()}T18:00"})
            for kind, desc, q, price in items:
                c.insert("event_items", {"event_id": eid, "kind": kind, "description": desc, "quantity": q, "unit_price": price})
            if status == "confirmed":
                from .modules.events import _event_folio
                e = c.one("SELECT * FROM events WHERE id = ?", [eid])
                c.update("events", eid, {"status": "confirmed", "folio_id": _event_folio(c, e)})
        for i, (name, role, phone) in enumerate((("Lagos State Emergency", "Police / Fire / Ambulance", "112"), ("Fire Service (Victoria Island)", "Fire", "+234 800 000 0112"),
                                                  ("Reddington Hospital (demo)", "Hospital", "+234 800 000 0113"), ("Duty Manager", "Hotel duty manager", "+234 800 000 0114"))):
            c.insert("emergency_contacts", {"hotel_id": hid, "name": name, "role": role, "phone": phone, "sort_order": i})
        c.insert("lost_found", {"hotel_id": hid, "number": next_number(c, hid, "lost_found", "LF"), "found_at": now_iso(), "location": "Pool deck", "description": "Black leather wallet (demo)",
                                "category": "documents", "valuable": 1, "stored_location": "Security safe", "found_by": uid.get("security_officer") or uid["general_manager"],
                                "status": "stored", "dispose_after": (on + _dt.timedelta(days=180)).isoformat()})


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
           "procurement_officer": ("admin", "Procurement Officer", 25_000_000), "hr_manager": ("hr", "HR Manager", 45_000_000), "hr_officer": ("hr", "HR Officer", 20_000_000),
           "maintenance_manager": ("maintenance", "Chief Engineer", 45_000_000), "maintenance_technician": ("maintenance", "Technician", 16_000_000),
           "security_officer": ("security", "Security Supervisor", 15_000_000), "sales_manager": ("sales", "Sales Manager", 40_000_000)}
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


NEW_DEMO_STAFF_07 = [("maintenance@demo.ehms", "Segun Adeyemi (Maintenance Mgr)", "maintenance_manager"),
                     ("technician@demo.ehms", "Ifeanyi Okeke (Technician)", "maintenance_technician"),
                     ("security@demo.ehms", "Bala Usman (Security)", "security_officer"), ("sales@demo.ehms", "Zainab Lawal (Sales Mgr)", "sales_manager"),
                     ("marketing@demo.ehms", "Ngozi Okon (Marketing Mgr)", "marketing_manager"), ("guestservice@demo.ehms", "Femi Ade (Guest Service)", "customer_service_officer")]
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
        _add_new_staff(org, hid, NEW_DEMO_STAFF_07)
        seed_operations_demo(hid, org)
        seed_crm_demo(hid, org)
        seed_bi_demo(hid, org)
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
    _add_new_staff(org, hid, NEW_DEMO_STAFF_07)
    seed_operations_demo(hid, org)
    seed_crm_demo(hid, org)
    seed_bi_demo(hid, org)
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
