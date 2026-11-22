"""Browser end-to-end smoke test (Playwright). Run with the app on BASE (default http://localhost:8765)
loaded with demo data:  python e2e/smoke.py
Visits every screen for several roles, runs the core front-desk workflow and fails on any JS error."""
import os
import re
import sys

from playwright.sync_api import sync_playwright, expect

BASE = os.environ.get("BASE", "http://localhost:8765")
SHOTS = os.environ.get("SHOTS", "/tmp/ehms_shots")
os.makedirs(SHOTS, exist_ok=True)
errors: list[str] = []


def login(page, email, password="Demo@12345"):
    page.goto(f"{BASE}/#/login")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_selector(".top", timeout=10000)


def visit(page, path, shot, expect_text=None):
    page.goto(f"{BASE}/#{path}")
    page.wait_for_timeout(700)
    page.wait_for_load_state("networkidle")
    if expect_text:
        expect(page.get_by_text(expect_text).first).to_be_visible(timeout=8000)
    if page.locator(".errorbox").count():
        errors.append(f"{path}: error box shown: {page.locator('.errorbox').first.inner_text()}")
    page.screenshot(path=f"{SHOTS}/{shot}.png", full_page=False)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.on("pageerror", lambda e: errors.append(f"JS error: {e}"))
        page.on("console", lambda m: errors.append(f"console.{m.type}: {m.text}") if m.type == "error" and "401" not in m.text and "409" not in m.text and "400" not in m.text else None)

        # ---------------- admin tour of every screen
        login(page, "admin@demo.ehms")
        for path, shot, txt in [("/", "01_dashboard", "Occupancy tonight"), ("/rooms", "02_room_board", "Room board"), ("/reservations", "03_front_desk", "Arrivals"),
                                ("/reservations?tab=in_house", "04_in_house", "In-house"), ("/calendar", "05_calendar", "Availability calendar"),
                                ("/guests", "06_guests", "Guests"), ("/housekeeping", "07_housekeeping", "Awaiting inspection"),
                                ("/accounting", "08_trial_balance", "Trial balance"), ("/reports", "09_reports", "Reports"), ("/approvals", "10_approvals", "Approvals"),
                                ("/admin/users", "11_users", "Users & access"), ("/admin/roles", "12_roles", "Roles & permissions"),
                                ("/admin/hotel", "13_hotel_settings", "Hotel profile"), ("/admin/rooms", "14_rooms_rates", "Room categories"),
                                ("/admin/audit", "15_audit", "Audit trail"), ("/profile", "16_profile", "Two-step verification"),
                                ("/pos", "40_pos", "Point of sale"), ("/kitchen", "41_kitchen", "Kitchen display"), ("/pos-setup", "42_pos_setup", "POS setup"),
                                ("/inventory", "43_inventory", "Inventory & stores"), ("/procurement", "44_procurement", "Procurement"),
                                ("/finance", "50_finance", "Finance operations"), ("/promotions", "51_promotions", "WELCOME10"),
                                ("/admin/messaging", "52_messaging", "Day-before arrival reminder"),
                                ("/laundry", "60_laundry", "Laundry"), ("/hr", "61_hr", "Human resources"), ("/payroll", "62_payroll", "Payroll"),
                                ("/my-hr", "63_my_hr", "My HR"), ("/maintenance", "70_maintenance", "Air-conditioner compressor"),
                                ("/security", "71_security", "Report an incident"), ("/events", "72_events", "Okafor")]:
            visit(page, path, shot, txt)
        # accounting tabs
        page.goto(f"{BASE}/#/accounting")
        for tab in ("Profit & loss", "Balance sheet", "Journal", "Chart of accounts"):
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(500)
        page.get_by_role("tab", name="Balance sheet").click()
        expect(page.get_by_text("Balanced").first).to_be_visible()
        page.screenshot(path=f"{SHOTS}/17_balance_sheet.png")
        # a report
        page.goto(f"{BASE}/#/reports")
        page.get_by_role("button", name="Occupancy & ADR / RevPAR").click()
        page.get_by_role("button", name="Run report").click()
        expect(page.get_by_role("button", name="Excel")).to_be_visible()
        page.screenshot(path=f"{SHOTS}/18_report.png")

        # ---------------- receptionist: walk-in -> check-in -> charge -> pay -> check-out
        page.get_by_role("button", name=re.compile("Demo Administrator")).click()
        page.get_by_role("button", name="Sign out").click()
        login(page, "frontdesk@demo.ehms")
        page.goto(f"{BASE}/#/reservations/new")
        page.get_by_label("Booking type").select_option("walk_in")
        page.locator(".typecard", has_text="Standard Room").click()
        page.get_by_label("Assign room (optional)").select_option(index=1)
        page.get_by_role("tab", name="New guest").click()
        page.get_by_label("First name").fill("Playwright")
        page.get_by_label("Last name").fill("Walkin")
        page.get_by_role("textbox", name="Email", exact=True).fill("pw.walkin@example.com")
        page.get_by_role("textbox", name="Phone", exact=True).fill("+2348011112222")
        expect(page.locator(".quote .total")).to_be_visible()
        page.screenshot(path=f"{SHOTS}/19_new_reservation.png", full_page=True)
        page.get_by_role("button", name="Create reservation").click()
        expect(page.get_by_role("heading", name=re.compile("RES-CGL-"))).to_be_visible(timeout=8000)
        page.get_by_role("button", name="Check in").click()
        page.get_by_role("dialog").get_by_role("button", name="Check in").click()
        expect(page.locator("h1 .pill", has_text="Checked In")).to_be_visible(timeout=8000)
        page.screenshot(path=f"{SHOTS}/20_checked_in.png")
        page.get_by_role("button", name="Folio").click()
        page.get_by_role("button", name="Post charge").click()
        page.get_by_label("Description").fill("Dinner — table 4")
        page.get_by_label("Unit price before tax (₦)").fill("15000")
        page.get_by_role("dialog").get_by_role("button", name="Post charge").click()
        expect(page.get_by_text("Dinner — table 4")).to_be_visible()
        page.get_by_role("button", name="Take payment").click()
        page.get_by_label("Method").select_option(label="Card (POS Terminal)")
        page.get_by_label(re.compile("Reference")).fill("APPR-445566")
        page.wait_for_timeout(400)
        page.get_by_role("button", name="Record payment").click()
        expect(page.get_by_text("Settled").first).to_be_visible(timeout=8000)
        page.screenshot(path=f"{SHOTS}/21_folio_settled.png")
        page.locator("a", has_text="RES-CGL-").first.click()
        page.get_by_role("button", name="Check out").click()
        page.get_by_role("button", name="Complete check-out").click()
        expect(page.locator("h1 .pill", has_text="Checked Out")).to_be_visible(timeout=8000)
        page.screenshot(path=f"{SHOTS}/22_checked_out.png")

        # ---------------- housekeeping manager inspects a cleaned room
        page.get_by_role("button", name=re.compile("Blessing")).click()
        page.get_by_role("button", name="Sign out").click()
        login(page, "hkmanager@demo.ehms")
        page.goto(f"{BASE}/#/housekeeping")
        page.get_by_role("button", name="Inspect").first.click()
        page.get_by_role("button", name="Pass — room ready").click()
        page.wait_for_timeout(800)
        page.screenshot(path=f"{SHOTS}/23_housekeeping.png")

        # ---------------- public booking portal (no login)
        ctx2 = browser.new_context(viewport={"width": 1280, "height": 900})
        pub = ctx2.new_page()
        pub.on("pageerror", lambda e: errors.append(f"JS error (portal): {e}"))
        pub.goto(f"{BASE}/#/book/CGL")
        pub.get_by_role("button", name="Check availability").click()
        expect(pub.locator(".portal-room").first).to_be_visible(timeout=8000)
        pub.screenshot(path=f"{SHOTS}/24_booking_portal.png", full_page=True)
        pub.locator(".portal-room").first.get_by_role("button", name="Select").click()
        pub.get_by_label("First name").fill("Online")
        pub.get_by_label("Last name").fill("Booker")
        pub.get_by_role("textbox", name="Email", exact=True).fill("online.booker@example.com")
        pub.get_by_role("textbox", name="Phone", exact=True).fill("+2348099990000")
        pub.get_by_text("I accept the booking terms").click()
        pub.get_by_role("button", name="Request booking").click()
        expect(pub.get_by_text("Thank you!")).to_be_visible(timeout=8000)
        pub.screenshot(path=f"{SHOTS}/25_booking_done.png")

        # release 0.4 tabs (fresh administrator session)
        page = browser.new_context(viewport={"width": 1440, "height": 900}).new_page()
        page.on("pageerror", lambda e: errors.append(f"JS error (0.4 tabs): {e}"))
        login(page, "admin@demo.ehms")
        page.goto(f"{BASE}/#/inventory")
        page.wait_for_selector("[role=tab]")
        page.wait_for_timeout(600)
        for tab in ("Item catalogue", "Requisitions", "Movements", "Stock counts", "Alerts", "Stores"):
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(300)
        page.goto(f"{BASE}/#/procurement")
        page.wait_for_selector("[role=tab]")
        page.wait_for_timeout(600)
        for tab in ("Requisitions & quotes", "Purchase orders", "Supplier invoices", "Suppliers"):
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(300)
        page.goto(f"{BASE}/#/finance")
        page.wait_for_selector("[role=tab]")
        page.wait_for_timeout(600)
        for tab in ("Bank reconciliation", "Budget vs actual", "Periods", "Online payments", "Cash flow", "Expense claims"):
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(400)
        page.screenshot(path=f"{SHOTS}/53_expenses.png")
        page.locator(".bell").click()
        page.wait_for_timeout(300)
        page.goto(f"{BASE}/#/admin/messaging")
        page.get_by_role("tab", name="Delivery log").click()
        page.get_by_role("button", name="Run reminders & deliver now").click()
        page.wait_for_timeout(800)
        page.goto(f"{BASE}/#/pos-setup")
        page.wait_for_selector("[role=tab]")
        page.wait_for_timeout(600)
        for tab in ("Outlets & tables", "Cashier shifts", "Kitchen performance"):
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(300)

        # ---------------- POS: cashier sells a takeaway lunch for cash
        c = browser.new_context(viewport={"width": 1366, "height": 860}).new_page()
        c.on("pageerror", lambda e: errors.append(f"JS error (pos): {e}"))
        login(c, "cashier@demo.ehms")
        c.goto(f"{BASE}/#/pos")
        c.get_by_label("Outlet").select_option(label="Savanna Restaurant")
        c.get_by_role("button", name="Open shift").click()
        c.locator(".modal-f").get_by_role("button", name="Open shift").click()
        c.get_by_role("button", name="Takeaway").click()
        c.get_by_role("button", name="Open order").click()
        c.locator(".menubtn", has_text="Fried rice").click()
        c.get_by_role("button", name=re.compile("Send to kitchen")).click()
        c.wait_for_timeout(500)
        c.get_by_role("button", name="Settle").click()
        c.get_by_role("button", name="Confirm payment").click()
        expect(c.get_by_text("Settled").first).to_be_visible(timeout=8000)
        c.screenshot(path=f"{SHOTS}/45_pos_settled.png")

        # ---------------- HR tabs, laundry price list (0.6)
        page.goto(f"{BASE}/#/hr")
        page.wait_for_selector("[role=tab]")
        page.wait_for_timeout(600)
        for tab in ("Roster", "Attendance", "Leave", "Employees"):
            page.get_by_role("tab", name=tab).click()
            page.wait_for_timeout(400)
        page.locator("td", has_text="EMP-CGL-").first.click()
        expect(page.get_by_text("Leave balances (this year)")).to_be_visible(timeout=8000)
        page.screenshot(path=f"{SHOTS}/64_employee.png")
        page.goto(f"{BASE}/#/laundry")
        page.get_by_role("tab", name="Price list").click()
        expect(page.get_by_text("Native attire (agbada)")).to_be_visible(timeout=8000)

        # ---------------- maintenance, security, events tabs (0.7)
        for path, tabs in (("/maintenance", ("Assets", "Performance", "Work orders")), ("/security", ("Visitors & contractors", "Lost & found", "Emergency contacts", "Access log", "Incidents")),
                           ("/events", ("All events", "Venue calendar", "Revenue & profit", "Venues", "Upcoming"))):
            page.goto(f"{BASE}/#{path}")
            page.wait_for_selector("[role=tab]")
            page.wait_for_timeout(500)
            for tab in tabs:
                page.get_by_role("tab", name=tab).click()
                page.wait_for_timeout(350)
        page.goto(f"{BASE}/#/events")
        page.locator("td", has_text="Okafor").first.click()
        expect(page.get_by_text("Quotation total")).to_be_visible(timeout=8000)
        page.screenshot(path=f"{SHOTS}/73_event.png")
        page.keyboard.press("Escape")
        sl = browser.new_context(viewport={"width": 1366, "height": 860}).new_page()
        sl.on("pageerror", lambda e: errors.append(f"JS error (events): {e}"))
        login(sl, "sales@demo.ehms")
        sl.goto(f"{BASE}/#/events")
        sl.locator("td", has_text="board meeting").first.click()
        sl.get_by_role("button", name="Confirm").click()
        expect(sl.get_by_text("Event confirmed")).to_be_visible(timeout=8000)

        # ---------------- payroll: HR prepares in the UI, finance approves (0.6)
        hr = browser.new_context(viewport={"width": 1366, "height": 860}).new_page()
        hr.on("pageerror", lambda e: errors.append(f"JS error (payroll): {e}"))
        login(hr, "hrmanager@demo.ehms")
        hr.goto(f"{BASE}/#/payroll")
        hr.get_by_role("button", name="Prepare payroll").click()
        expect(hr.get_by_role("heading", name=re.compile("Payroll 20"))).to_be_visible(timeout=10000)
        hr.screenshot(path=f"{SHOTS}/65_payroll_run.png")
        fin = browser.new_context(viewport={"width": 1366, "height": 860}).new_page()
        fin.on("pageerror", lambda e: errors.append(f"JS error (payroll approve): {e}"))
        fin.on("dialog", lambda d: d.accept())
        login(fin, "finance@demo.ehms")
        fin.goto(f"{BASE}/#/payroll")
        fin.locator("td", has_text="20").first.click()
        fin.get_by_role("button", name="Approve").click()
        expect(fin.get_by_text("Payroll approved")).to_be_visible(timeout=8000)

        # ---------------- booking engine promo code (0.5)
        g = browser.new_context(viewport={"width": 1280, "height": 900}).new_page()
        g.on("pageerror", lambda e: errors.append(f"JS error (portal promo): {e}"))
        g.goto(f"{BASE}/#/book/CGL")
        g.get_by_label("Promo code").fill("WELCOME10")
        g.get_by_role("button", name="Check availability").click()
        expect(g.get_by_text("Promo code applied").first).to_be_visible(timeout=8000)
        g.screenshot(path=f"{SHOTS}/54_portal_promo.png")
        g.goto(f"{BASE}/payment-return?reference=UNKNOWN")
        expect(g.get_by_text("We could not check this payment")).to_be_visible(timeout=8000)

        # ---------------- mobile layout
        m = browser.new_context(viewport={"width": 390, "height": 844}).new_page()
        m.on("pageerror", lambda e: errors.append(f"JS error (mobile): {e}"))
        login(m, "housekeeper@demo.ehms")
        m.goto(f"{BASE}/#/housekeeping")
        m.wait_for_timeout(800)
        m.screenshot(path=f"{SHOTS}/26_mobile_housekeeper.png", full_page=True)
        m.goto(f"{BASE}/#/my-hr")
        m.get_by_role("button", name="Clock in").click()
        expect(m.get_by_text("Clocked in")).to_be_visible(timeout=8000)
        m.screenshot(path=f"{SHOTS}/66_mobile_my_hr.png", full_page=True)
        m.goto(f"{BASE}/#/maintenance")
        m.get_by_role("button", name="Report a fault").click()
        m.get_by_label("What is wrong?").fill("Bathroom extractor fan noisy")
        m.locator(".modal-f").get_by_role("button", name="Report").click()
        expect(m.get_by_text("Fault reported to maintenance")).to_be_visible(timeout=8000)
        m.screenshot(path=f"{SHOTS}/74_mobile_fault.png", full_page=True)
        browser.close()

    if errors:
        print("FAILURES:")
        for e in errors:
            print(" -", e)
        sys.exit(1)
    print("E2E OK — screenshots in", SHOTS)


if __name__ == "__main__":
    main()
