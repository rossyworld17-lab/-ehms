# EHMS — Enterprise Hotel Management System

A secure, multi-property hotel management platform: property management (PMS), reservations, front office,
guest folios, payments, double-entry accounting, housekeeping, reporting and a public booking engine.
Default localisation is Nigeria (NGN, Africa/Lagos, configurable VAT and service charge); every rate, tax
and policy is configurable for other countries.

> **Release 1.0 — production ready.** All 127 SRS requirements are implemented and traced; the release adds a
> security review with hardening, a performance review with optimisations and load-test tooling, and the acceptance
> pack (UAT scenarios, go-live checklist, training plan, sign-off). See [docs/RELEASE_NOTES.md](docs/RELEASE_NOTES.md)
> for what each release added and [docs/ROADMAP.md](docs/ROADMAP.md) for integrations planned after 1.0;
> the [progress register](docs/PROGRESS.md) tracks status. Nothing in the interface is a placeholder: screens and
> menu items appear only when the module behind them works and the user has permission.

## What works today

| Area | Highlights |
|---|---|
| Security & access | scrypt password hashing, JWT sessions with idle timeout and revocation, account lockout, TOTP multi-factor authentication, password reset, 41 permissions, 29 role templates + custom roles, per-hotel scoping, privilege-escalation guard, login history |
| Properties | Multiple hotels/branches per organisation, profile & policies, departments, configurable taxes (inclusive/exclusive, effective dates), service charge, payment methods mapped to ledger accounts |
| Rooms | Categories with standard / weekend / corporate / extra-person rates, room inventory, colour-coded live room board, out-of-order / maintenance / VIP blocks |
| Reservations | Individual, walk-in, corporate, group, travel-agent, VIP; enquiry → tentative → confirmed → checked-in → checked-out / cancelled / no-show / waitlist; per-night pricing with tax preview; transaction-safe double-booking prevention; authorised overbooking & rate overrides; duplicate-guest detection; room-by-day calendar |
| Front office | Check-in (inspected rooms only, lawful ID capture), room moves, check-out preview, early departure, night audit (posts room charges, rolls the business date, flags no-shows & overstays) |
| Folios & payments | Charges by department with automatic service charge and VAT, cash / transfer / POS / city-ledger payments with idempotency and duplicate detection, reversals and allowances, refunds with maker-checker approval, PDF invoices/receipts. Online card payments are never faked — they require a configured gateway |
| Accounting | Chart of accounts, automatic balanced journal for every charge/payment/refund, manual journals, reversals, trial balance, P&L, balance sheet (per hotel or consolidated); posted ledger and audit trail are tamper-protected at database level |
| Housekeeping | Tasks created automatically at check-out / room moves / night audit, assignment, mobile-friendly start → complete → inspect; a room is sellable only after inspection |
| Guests (CRM base) | Central profiles, stay & spend history, repeat/VIP flags, marketing consent, masked identity data |
| Dashboard & reports | Occupancy, ADR, RevPAR, arrivals/departures, revenue by department, balances, 30-day trend, 14-day forecast, channel mix; arrivals / departures / in-house / daily revenue / occupancy / outstanding balances reports exported to Excel, CSV, PDF |
| Booking engine | Public mobile-friendly portal (`/#/book/<HOTEL_CODE>`): availability, pricing incl. taxes, booking (pay at hotel), lookup and self-cancellation |
| Restaurant & bar POS *(0.4)* | Outlets (restaurant, bar, in-room dining), table plan, menu with categories, stations and sold-out switch; dine-in / takeaway / room service; split bill, merge, move table; authorised discounts and voids with reasons; split tenders (cash with change, POS card, transfer, **charge to room folio**); cashier shifts with float, expected vs counted cash and variance; 80 mm receipt PDF |
| Kitchen display *(0.4)* | Tickets by station (kitchen, grill, pastry, bar), oldest first with ageing colours, preparing → ready → served, rush flag, ready alerts on the POS, preparation-time report |
| Inventory & stores *(0.4)* | Item catalogue with barcodes and reorder levels; multiple stores; perpetual stock at weighted average cost (always reconciles to the Inventory GL account); requisitions with approval, issues to departments, transfers, wastage and adjustments, stock counts with variance posting; batches and expiry dates (FEFO); low-stock and expiry alerts; **recipes deduct ingredients automatically when a POS order is settled** |
| Maintenance *(0.7)* | Asset register with capitalisation and monthly straight-line depreciation; preventive schedules that raise work orders automatically; fault reporting by any staff (also from housekeeping checklists) with notifications; assignment, progress notes, spare parts from stores, vendor costs, room blocking until verified; independent verification; downtime and cost reports |
| Security *(0.7)* | Incident register with severity alerts, investigation notes and restricted sensitive cases; visitor/contractor log with masked IDs; lost-and-found with ID-checked returns and holding periods; emergency contacts; key-card / access-control event intake API and log |
| Events & banqueting *(0.7)* | Venues and capacities; enquiry → tentative → confirmed with venue-clash and capacity checks; quotation lines (venue, catering, beverage, equipment, décor…), quotation/invoice PDF; event folio for deposits and invoicing through the ledger; direct costs, staff allocation, profitability; venue calendar |
| Groups & billing *(0.95)* | Cancellation policies (free window, first night / percentage / fixed fee, no-show fee), fees posted automatically on cancellation or no-show and waivable only with permission and reason, online cancellation only inside the free window; group blocks holding rooms per category at a group rate, rooming lists from CSV, pickup tracking, manual and automatic release after cut-off, master folio billing; extra folios per stay (e.g. company bill) with charge transfers (whole or partial) and all folios settled before check-out; credit and debit notes approved by a second person, posted with the original tax split, PDF; exchange rates and foreign-currency payments converted at the day's rate |
| Stock costing *(0.95)* | Weighted average (default) or FIFO costing per hotel, with batches consumed in receipt order under FIFO |
| Recruitment *(0.95)* | Job openings, applicants through screening → interview → offer → hire, interview scores and notes, CVs in the document store, hiring creates the employee record, anonymisation of unsuccessful applicants |
| Business intelligence *(0.9)* | Analytics by property (or consolidated), date range and department, grouped by day/week/month/quarter/year, compared with the previous period or last year: occupancy, ADR, RevPAR, bookings, cancellations, lead time, length of stay, booking sources; revenue, expenses and gross operating profit **from posted ledger entries only**; occupancy history by room category (heat map) and by room; HR analytics (headcount, turnover, attendance, lateness, overtime, leave, payroll cost); reports scheduled daily/weekly/monthly, generated by the worker and delivered through the document store to recipients whose access is re-checked every time |
| AI & automation *(0.9)* | Explainable occupancy/revenue forecast (pickup by lead time, weekday fallback, ranges and limitations stated); nine unusual-transaction rules (large refunds, refund share, night-time cash, POS void rates, large discounts, large allowances, rate-override patterns, possible duplicate supplier invoices, manual cash journals) raising flags that a different person must review; rate and reorder recommendations that can only create a pricing rule *awaiting approval* or a *submitted* requisition; **Ask EHMS** assistant answering from permission-checked tools only, never acting, every question logged — built-in engine by default, optional Claude engine (opt-in) |
| Documents *(0.9)* | Upload to guests, reservations, folios, employees, suppliers, purchase orders, invoices, events, expenses, journals, assets, incidents and the hotel; type whitelist with content-signature check and size limit; confidential/restricted levels (write-only for staff without access, e.g. reception filing ID scans); versions; SHA-256 integrity check on download; retention by category with legal hold; complete access history including refused attempts |
| Guest relations *(0.8)* | Loyalty programme (points on settled stays, tiers with bonuses, redemption as a folio credit through the ledger, manual adjustments with reasons); complaints with category, severity, SLA deadlines, assignment, response/resolution times and automatic escalation; post-stay survey link in the thank-you message (low scores open a complaint automatically); feedback entry from review sites; transparent keyword sentiment/theme analysis; NPS and insights; email/SMS campaigns to consenting guests only, with opt-out |
| Sales & revenue *(0.8)* | Corporate, travel-agent and government accounts with credit terms and negotiated rates per room category; bookings against an account; account statements; sales targets with achievement; seasonal rate adjustments; occupancy-based pricing rules effective only after a second person approves; competitor rate records; revenue dashboard (on-the-books forecast, pickup, ADR, RevPAR, ALOS, booking window, cancellations) with suggestions. **Quoted nightly rates are locked on the booking**, so later price changes never alter a confirmed guest's price |
| Laundry *(0.6)* | Guest laundry with price list, express surcharge, stage tracking (washing → drying → ironing → quality check → ready → delivered), lost/damaged items excluded from the bill, automatic folio charge on delivery; internal linen batches by department; daily summary |
| HR *(0.6)* | Employee register with masked bank/statutory IDs, weekly duty rosters, attendance with overtime, staff self clock-in with lateness, leave types/balances with approval, confidential HR records, exits; **My HR** self-service (leave, payslips, attendance) |
| Payroll *(0.6)* | Runs computed from salary structure, attendance, unpaid leave, bonuses, deductions and staff loans; configurable PAYE bands with rent relief, pension, NHF, NSITF, ITF (Nigerian defaults); maker-checker approval posting the payroll journal; salary payment, statutory remittances, bank schedule CSV, payslip PDFs |
| Online payments *(0.5)* | Paystack and Flutterwave hosted checkout: payment links from any folio (emailed to the guest), "pay now" on the booking engine (booking confirmed automatically), HMAC-signed webhooks, provider verification of amount and currency before anything is posted, idempotent per reference, retries and an integration log |
| Finance operations *(0.5)* | Expense claims with maker-checker and payment, bank reconciliation (CSV import, auto-match, manual match), monthly budgets and budget vs actual, direct-method cash-flow statement, accounting period close/reopen enforced on every posting |
| Communication *(0.5)* | In-app notification bell, editable templates per event and channel, email (SMTP), SMS (Termii), WhatsApp Cloud API, delivery log with retries; background worker sends day-before reminders, birthday greetings, low-stock and invoice-due alerts exactly once; promo codes for the booking engine |
| Procurement *(0.4)* | Supplier register with performance and masked bank details; purchase requisitions; quotation comparison; purchase orders with standard / high-value approval and maker-checker; goods received notes with rejections, batch and expiry; three-way matched supplier invoices with tolerance; supplier payments with withholding tax; payables ageing |

## Quick start (demo)

```bash
# Backend (Python 3.11+)
cd backend
pip install -r requirements.txt
export EHMS_SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))")
export DATABASE_URL=sqlite:///./ehms.db      # or postgresql://user:pass@host/db
EHMS_SEED_DEMO=1 uvicorn ehms.app:app --port 8000

# Frontend (Node 20+), in another terminal
cd frontend && npm install && npm run build   # the backend serves frontend/dist
```

Open <http://localhost:8000> and sign in with a demo account (password `Demo@12345`):

| Email | Role |
|---|---|
| admin@demo.ehms | Super Administrator (all hotels) |
| gm@demo.ehms | General Manager |
| fom@demo.ehms | Front Office Manager |
| frontdesk@demo.ehms | Receptionist |
| finance@demo.ehms / accounts@demo.ehms | Finance Manager / Accountant |
| hkmanager@demo.ehms / housekeeper@demo.ehms | Housekeeping |
| fnbmanager@demo.ehms / cashier@demo.ehms / waiter@demo.ehms / chef@demo.ehms | Restaurant manager, cashier, waiter, chef *(0.4)* |
| inventory@demo.ehms / stores@demo.ehms / procurement@demo.ehms | Inventory manager, storekeeper, procurement officer *(0.4)* |
| maintenance@demo.ehms / technician@demo.ehms / security@demo.ehms / sales@demo.ehms | Maintenance manager, technician, security officer, sales manager *(0.7)* |
| marketing@demo.ehms / guestservice@demo.ehms | Marketing manager, customer service officer *(0.8)* |
| hrmanager@demo.ehms / hrofficer@demo.ehms | HR manager, HR officer *(0.6)* — every demo staff account also has an employee record for **My HR** |
| auditor@demo.ehms | Auditor (read-only) |

Upgrading from 0.3? Start the new version on your existing database: migrations run automatically, existing
system roles receive the new permissions once, and (in demo mode) the 0.4 demo outlets, menu, stores and
suppliers are added.

Public booking engine: <http://localhost:8000/#/book/CGL>. API reference: <http://localhost:8000/api/docs>.

Demo data is fictional and clearly labelled. **Never enable `EHMS_SEED_DEMO` in production.**

## Production

```bash
cp .env.example .env            # set POSTGRES_PASSWORD and EHMS_SECRET_KEY
docker compose up -d --build
docker compose exec app python -m ehms.seed bootstrap --org "Your Company Ltd" --org-code YCL \
  --hotel "Your Hotel" --hotel-code YH --admin-email you@example.com --admin-name "Your Name"
```

See [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) for TLS, email, payment gateways, backups and restore.

## Tests

```bash
cd backend && python -m pytest -q                       # 90 API/integration tests (SQLite)
TEST_DATABASE_URL=postgresql://... python -m pytest -q  # same suite on PostgreSQL
python ../frontend/e2e/smoke.py                         # browser end-to-end (app running with demo data)
```

## Documentation

- [Architecture & database](docs/ARCHITECTURE.md)
- [REST API reference](docs/API.md)
- **[EHMS v1.0.0 User Guide (Word)](docs/EHMS_v1.0.0_User_Guide.docx)** — complete guide for staff, managers and administrators
- [User guide](docs/USER_GUIDE.md) · [Administrator manual](docs/ADMIN_MANUAL.md)
- [Deployment, backup & recovery](docs/DEPLOYMENT.md)
- [Test report](docs/TEST_REPORT.md) · [Requirements traceability](docs/TRACEABILITY.md) · [Progress register](docs/PROGRESS.md) · [Roadmap](docs/ROADMAP.md)
- [Security review](docs/SECURITY.md) · [Performance review](docs/PERFORMANCE.md) · [Acceptance, go-live & sign-off](docs/ACCEPTANCE.md) · [Release notes](docs/RELEASE_NOTES.md)

## Screenshots

| Dashboard | Room board | Guest folio |
|---|---|---|
| ![](docs/screenshots/01_dashboard.png) | ![](docs/screenshots/02_room_board.png) | ![](docs/screenshots/21_folio_settled.png) |
| **Housekeeping** | **Balance sheet** | **Booking engine** |
| ![](docs/screenshots/07_housekeeping.png) | ![](docs/screenshots/17_balance_sheet.png) | ![](docs/screenshots/24_booking_portal.png) |
| **Point of sale** | **Kitchen display** | **Menu & recipes** |
| ![](docs/screenshots/40_pos_order.png) | ![](docs/screenshots/41_kitchen_display.png) | ![](docs/screenshots/42_menu_recipes.png) |
| **Inventory** | **Quotation comparison** | **Goods received** |
| ![](docs/screenshots/43_inventory.png) | ![](docs/screenshots/44_quote_comparison.png) | ![](docs/screenshots/45_goods_received.png) |
