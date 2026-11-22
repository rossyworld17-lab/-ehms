# Development progress register

Maintained per the master prompt: completed modules, partially completed modules, pending integrations,
outstanding defects and test results. Requirement-level status is in [TRACEABILITY.md](TRACEABILITY.md).

_Last updated: release 0.6._

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
| Online payments: Paystack & Flutterwave links, booking prepayment, webhooks, verification | **0.5** | folios, reservations, ledger, booking engine |
| Promo codes | **0.5** | booking engine, reservations |
| Expense claims, bank reconciliation, budgets, cash flow, period close | **0.5** | ledger (period lock on every posting) |
| Communication centre: templates, email/SMS/WhatsApp, in-app bell, worker reminders | **0.5** | reservations, POS, inventory, procurement |
| Laundry (guest & internal linen) | **0.6** | folios, housekeeping |
| HR: employees, rosters, attendance, leave, records, self-service | **0.6** | users, notifications, payroll |
| Payroll with configurable statutory rules, loans, remittances | **0.6** | HR attendance & leave, ledger |

## Partially completed

| Area | Done | Remaining |
|---|---|---|
| CRM | profiles, history, repeat/VIP, consent | loyalty points, campaigns, surveys, feedback analysis |
| Finance | AR, AP, cash/bank, approvals, reconciliation, budgets, cash flow, period close | credit/debit note documents, multi-currency |
| Inventory | WAC valuation, FEFO depletion | optional FIFO costing, supplier returns, barcode scanner input |
| Housekeeping | tasks, inspection, issue reporting, stock requisitions, laundry | lost-and-found register (with security, 0.7) |
| HR | full HR & payroll | recruitment pipeline |

## Pending integrations (none are simulated)

| Integration | Behaviour today |
|---|---|
| Paystack / Flutterwave | adapters built and tested against the documented APIs (simulated in tests); need live keys and webhook registration |
| SMS (Termii) / WhatsApp Cloud API | adapters built; need provider accounts; until configured messages are stored `not_configured` |
| Channel managers / OTAs | not connected |
| Door locks, key cards, CCTV | not connected |
| E-invoicing | not connected |

## Outstanding defects

None known. Defects found and fixed while building 0.4 are listed in [TEST_REPORT.md](TEST_REPORT.md).

## Test results (release 0.6)

| Suite | Result |
|---|---|
| API / integration (`pytest`), SQLite | 59 passed, 0 failed |
| API / integration (`pytest`), PostgreSQL 16 | 59 passed, 0 failed |
| Browser end-to-end (`frontend/e2e/smoke.py`) | passed — every screen for several roles, front-desk stay, POS cash sale, payroll prepare → approve, mobile self clock-in |
| Upgrade from 0.3 and 0.4 databases | passed — migrations applied, permissions granted once, accounts added, demo data added once, books balanced |
