# Development progress register

Maintained per the master prompt: completed modules, partially completed modules, pending integrations,
outstanding defects and test results. Requirement-level status is in [TRACEABILITY.md](TRACEABILITY.md).

_Last updated: release 0.4._

## Completed modules (implemented, integrated and tested)

| Module | Release | Integrated with |
|---|---|---|
| Authentication, sessions, MFA, password policy, lockout | 0.3 | every endpoint |
| Users, roles (29 templates + custom), permissions (67), hotel scoping, audit trail | 0.3, 0.4 | every module |
| Multi-property configuration, taxes, service charge, payment methods | 0.3 | reservations, folios, POS, procurement |
| Rooms, room board, status engine | 0.3 | reservations, front office, housekeeping |
| Reservations, availability, calendar, booking engine | 0.3 | rooms, guests, folios |
| Front office: check-in/out, moves, folios, payments, refunds, night audit | 0.3 | ledger, housekeeping, POS |
| Housekeeping tasks and inspection | 0.3 | rooms, front office |
| Double-entry accounting core: chart of accounts, journals, TB, P&L, balance sheet | 0.3 | every financial module |
| Restaurant & bar POS, cashier shifts, receipts | **0.4** | folios (charge to room), ledger, inventory (recipes), reports, dashboard |
| Kitchen display and kitchen performance | **0.4** | POS |
| Inventory & stores (WAC, batches/expiry, requisitions, transfers, counts) | **0.4** | POS, procurement, ledger, reports, dashboard |
| Procurement & suppliers (requisitions, quotations, POs, GRN, invoices, payments, WHT) | **0.4** | inventory, ledger (GRNI, AP, PPV, WHT), reports, dashboard |
| Reports with PDF/Excel/CSV export (12 reports), export audit | 0.3, 0.4 | all modules |

## Partially completed

| Area | Done | Remaining |
|---|---|---|
| CRM | profiles, history, repeat/VIP, consent | loyalty points, campaigns, surveys, feedback analysis |
| Finance | AR, AP, cash/bank, approvals | bank reconciliation, budgets, period close, credit/debit notes, cash-flow statement, multi-currency |
| Inventory | WAC valuation, FEFO depletion | optional FIFO costing, supplier returns, barcode scanner input |
| Notifications | email via SMTP; in-app records (e.g. order ready) | notification centre UI, SMS/WhatsApp, templates, reminders worker |
| Housekeeping | tasks, inspection, issue reporting, stock requisitions | lost-and-found register, laundry |

## Pending integrations (none are simulated)

| Integration | Behaviour today |
|---|---|
| Paystack / Flutterwave | online payments return HTTP 501 until credentials and webhooks are configured |
| SMS / WhatsApp Business | messages stored with status `not_configured` |
| Channel managers / OTAs | not connected |
| Door locks, key cards, CCTV | not connected |
| E-invoicing | not connected |

## Outstanding defects

None known. Defects found and fixed while building 0.4 are listed in [TEST_REPORT.md](TEST_REPORT.md).

## Test results (release 0.4)

| Suite | Result |
|---|---|
| API / integration (`pytest`), SQLite | 45 passed, 0 failed |
| API / integration (`pytest`), PostgreSQL 16 | 45 passed, 0 failed |
| Browser end-to-end (`frontend/e2e/smoke.py`) | passed — every screen for several roles, front-desk stay, POS cash sale, mobile layout |
| Upgrade from a 0.3 database | passed — migration applied, permissions granted once, accounts added, data kept, books balanced |
