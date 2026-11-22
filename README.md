# EHMS — Enterprise Hotel Management System

A secure, multi-property hotel management platform: property management (PMS), reservations, front office,
guest folios, payments, double-entry accounting, housekeeping, reporting and a public booking engine.
Default localisation is Nigeria (NGN, Africa/Lagos, configurable VAT and service charge); every rate, tax
and policy is configurable for other countries.

> **Release 0.4 — adds master-prompt Phase 5 (restaurant & bar POS with kitchen display) and Phase 7 (inventory,
> stores, procurement and suppliers), fully integrated with guest folios and the double-entry ledger.**
> Traceability: 57 of 127 SRS requirements implemented, 25 partial. Laundry, HR/payroll, maintenance, events,
> AI and channel-manager integrations are scheduled in [docs/ROADMAP.md](docs/ROADMAP.md); the
> [progress register](docs/PROGRESS.md) lists what is done, partial, pending and outstanding. Nothing in the
> interface is a placeholder: screens and menu items appear only when the module behind them works and the
> user has permission.

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
cd backend && python -m pytest -q                       # 45 API/integration tests (SQLite)
TEST_DATABASE_URL=postgresql://... python -m pytest -q  # same suite on PostgreSQL
python ../frontend/e2e/smoke.py                         # browser end-to-end (app running with demo data)
```

## Documentation

- [Architecture & database](docs/ARCHITECTURE.md)
- [REST API reference](docs/API.md)
- [User guide](docs/USER_GUIDE.md) · [Administrator manual](docs/ADMIN_MANUAL.md)
- [Deployment, backup & recovery](docs/DEPLOYMENT.md)
- [Test report](docs/TEST_REPORT.md) · [Requirements traceability](docs/TRACEABILITY.md) · [Progress register](docs/PROGRESS.md) · [Roadmap](docs/ROADMAP.md)

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
