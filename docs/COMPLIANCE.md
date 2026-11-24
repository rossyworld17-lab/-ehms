# Requirements compliance — EHMS 1.3.0

This document checks EHMS against **every** requirement source: the *EHMS Software Requirements Specification v1*
(SRS) and the *Master software development prompt*, section by section, including the parts the functional
traceability matrix ([TRACEABILITY.md](TRACEABILITY.md), 127 functional requirements) does not cover — business
rules, non-functional requirements, integrations, interface, workflows, reports, audit, testing, acceptance and
deliverables.

**Status key** — **Met**: built and covered by automated tests · **Met (ready)**: built; needs your provider
account, device or server to switch on · **Partial**: core behaviour built, the stated gap remains ·
**Your step**: depends on the hotel (hosting, sign-off, contracts) · **Optional / planned**: marked optional in
the SRS or planned for after this release.

Evidence: 120 automated API/integration tests (SQLite and PostgreSQL), the browser end-to-end test
(`frontend/e2e/smoke.py`), [TEST_REPORT.md](TEST_REPORT.md) and the source.

## Summary

| | Count |
|---|---|
| SRS functional requirements (FR-…) | 127 / 127 Met |
| SRS business rules (BR-001…014) | 14 / 14 Met |
| Master prompt sections 1–34 | all Met, except the items listed under *Open items* |
| Open items | 7 (2 partial, 5 needing external providers or optional) — listed at the end |

Release 1.2 closed the gaps a line-by-line review found in 1.1.2: multiple languages, in-app backups with
verification and restore, wake-up calls, early check-in / late check-out, registration cards, drag-and-drop room
assignment, table reservations, purchase returns, referral programme, staff welfare, petty cash and payment
vouchers, room photos and videos, CCTV event links, check-out reminders, cancellation-risk and equipment-failure
prediction, guest demographics, an automated daily summary, hotel logo, downloadable booking confirmation,
biometric attendance intake, breadcrumb navigation, pagination, in-app help, and a generated data dictionary.

---

## Master prompt

| § | Requirement | Status | Where / how |
|---|---|---|---|
| 1 | Complete, working, integrated ERP — no dead buttons or fake success | Met | Every menu item maps to a working, tested module; menus appear only with permission; payments/messages report `not_configured` honestly |
| 2 | React + TypeScript, Python, PostgreSQL, REST, token auth, design system, charts, file storage, Docker | Met | `frontend/` (React 19, TS), `backend/` (Python, Starlette), PostgreSQL or SQLite, OpenAPI at `/api/docs`, JWT sessions, SVG charts, document store, `Dockerfile` + `docker-compose.yml` |
| 2 | Desktop, tablet, mobile; multiple hotels; multi-currency; configurable tax; time zones; central and property admin | Met | Responsive layouts (mobile tested); hotel selector; exchange rates & foreign-currency payments; tax rules with dates; per-hotel time zone |
| 2 | Multiple languages | **Partial** | Language framework with **English and French**: menu, header, breadcrumb, sign-in and the guest booking engine are translated; each user's choice is saved. Page bodies are still English — more strings and languages can be added in `frontend/src/i18n.tsx` |
| 2 | Nigeria defaults (NGN, Africa/Lagos, VAT 7.5 %, service charge), adaptable | Met | Seed defaults; every rate configurable |
| 3 | 29 roles, create/edit/suspend/deactivate, departments and branches, custom roles, MFA, login history, activity logs, reset, session expiry and revocation, approval workflows | Met | Users & access, Roles & permissions (privilege-escalation guard), TOTP MFA, lockout, audit trail, maker-checker approvals |
| 4.1 | Hotel profile incl. **logo**, registration, category, floors, times, policies, taxes, currency, terms, amenities, emergency contacts | Met | Hotel settings (logo upload added in 1.2) |
| 4.2 | Rooms: number, name, category, floor, wing, occupancy, beds, size, description, amenities, rates (standard, weekend, seasonal, corporate, promotional), extra person, status; **photographs** | Met | Rooms & rates; seasons, negotiated rates, promo codes; **photo gallery and video links per room category** (1.2) |
| 4.2 | Standard … accessible categories + custom categories | Met | Category list is free; demo has STD/DLX/EXE/JST/PRS |
| 4.3 | Real-time colour room board, all statuses, automatic updates, no overlapping allocations without authorised override | Met | Room board; status from check-in/out and housekeeping; overbooking needs `reservations.overbook` + reason |
| 5 | Individual, group, corporate, walk-in, agent, online, phone, email, repeat, VIP, event bookings; all fields; all statuses | Met | Reservations (statuses incl. waitlisted), booking types and sources |
| 5 | Booking & availability calendars, **drag-and-drop room assignment**, modify/cancel/confirm, references, confirmation email, SMS/WhatsApp, reminders, cancellation & refunds, deposits, group allocation, history, source tracking, overbooking prevention, audit | Met | Calendar; room board drag-and-drop (1.2); cancellation policies; refunds maker-checker; group blocks |
| 6 | **Hotel website** ("visit the hotel's website, view hotel information") | Met | Public website at the main address with about, rooms, dining, events, facilities, gallery, location, contact form; edited and published from Administration → Website without code (1.3) |
| 6 | Booking engine: info, categories, **photos and videos**, availability, prices, booking, online payment, confirmation, modify/cancel, **download receipt**; promo/corporate/packages; no double booking | Met (ready) | `#/book/<code>` with gallery, video link, promo and **referral code**, downloadable confirmation PDF (1.2). Paystack/Flutterwave built — live payments need your merchant keys. Channel managers: see open items |
| 7 | Check-in: search, walk-in, ID capture (masked), lawful photos, assign room, deposit, **registration card**, arrival time, requests | Met | Front desk; registration card PDF (1.2); ID documents in the document store |
| 7 | Check-out: charges from all departments, taxes, discounts, invoice, payment, refunds, receipt, room status, housekeeping trigger | Met | Folio, invoice PDF, dirty status + housekeeping task at check-out |
| 7 | Transfers, **early check-in, late check-out**, upgrades, extensions, **wake-up calls**, complaints, lost & found, communication, arrival/departure/in-house lists, VIP | Met | Room move; early/late with configurable fees (1.2); wake-up calls with reminders (1.2) |
| 8 | CRM database, preferences, history, spend, loyalty, segmentation, repeat/VIP, birthdays, promotions, surveys, post-checkout messages, retention campaigns, feedback analysis | Met | Guests, Guest relations, loyalty, campaigns to consenting guests, surveys, NPS, **referrals** (1.2) |
| 9 | Restaurant profiles, areas, tables, **table reservations**, menus with photos and prices, specials and packages, room service, takeaway, catering, kitchen orders | Met | POS, Menu & outlets (specials/packages as menu items and categories), table bookings (1.2) |
| 9 | POS: orders, tables, waiters, kitchen display, permissions, split, merge, discounts, taxes, tenders, receipts, room charge, refunds | Met | Point of sale |
| 9 | Kitchen display, queue, status, prep time, recipes, consumption, inventory, wastage, daily reports | Met | Kitchen display & performance, recipes deduct stock, wastage |
| 10 | Housekeeping schedules, assignments, checklists, inspection, linen, laundry, minibar, amenities, lost & found, complaints, maintenance reporting, readiness; mobile staff screen; manager dashboard | Met | Housekeeping (mobile tested) |
| 11 | Laundry: requests, linen, items, wash/dry/iron, QC, delivery, pricing, billing, lost/damaged, staff, inventory, reports | Met | Laundry |
| 12.1 | Chart of accounts, GL, journals, AP, AR, TB, P&L, BS, cash flow, bank rec, periods, opening balances, closing, audit; double entry | Met | Accounting, Finance operations; every posting balanced (tested) |
| 12.2–12.3 | Revenue by department (rooms, F&B, laundry, events, spa, transport…); expenses with approvals and documents | Met | Department codes; expense claims maker-checker |
| 12.4 | Cash/bank, deposits, withdrawals, **petty cash**, cashier reconciliation, shifts, payment tracking, bank rec, cash variance | Met | Petty cash funds with limits, approval, top-ups and **payment vouchers** (1.2); cashier shifts with variance |
| 12.5 | Configurable VAT, WHT, dates, exemptions | Met | Tax rules; WHT on supplier payments |
| 12.6 | Cash, transfer, POS terminals, cards, online, links; Paystack/Flutterwave; no card data stored | Met (ready) | Payment methods; payment links; webhooks verified; only references stored |
| 12.7 | Daily/monthly/annual, P&L, departmental, balances, payments, refunds, expenses, tax, cashier, budget vs actual | Met | Reports (PDF/Excel/CSV), Finance operations |
| 13 | Item categories, codes, **barcodes**, units, valuation (average/FIFO), stores, GRN, requisitions, transfers, issues, adjustments, counts, expiry, batches, reorder alerts, damage/expiry/wastage, suppliers, reports; integration and automatic deduction; movement history | Met | Inventory & stores (append-only movement ledger) |
| 14 | Suppliers, categories, contacts, performance, requisitions, POs, quotations and comparison, approvals by amount, GRN, invoices, payments, **purchase returns**, balances, reports | Met | Procurement; returns to supplier before or after invoicing (1.2) |
| 15 | Employee records, IDs, documents; recruitment, interviews, onboarding, attendance, shifts, leave and approval, transfers, promotions, disciplinary, training, appraisal, **welfare**, resignation, retirement, exit | Met | Human resources (full suite 1.1); welfare register (1.2) |
| 15 | Payroll: salary, allowances, bonuses, overtime, deductions, loans/advances, statutory, processing, payslips, approval, bank schedules, reports; configurable rules | Met | Payroll (prepare → approve → pay), statutory rules |
| 16 | Assets, depreciation, preventive and corrective maintenance, work orders, faults, assignment, spare parts, costs, service providers, inspection, history; automatic notifications | Met | Maintenance |
| 17 | Venues, capacity, calendar, bookings, quotations, packages, catering, equipment, décor, contracts, deposits, invoices, schedule, staff, costs, profitability | Met | Events & banqueting (quotation/invoice PDFs; contracts filed in Documents) |
| 18 | Corporate and agent accounts, agreements, group sales, pipeline, campaigns, offers, discounts, loyalty, **referral programmes**, segmentation, campaign performance, forecasting | Met | Sales & revenue, Guest relations, referrals (1.2) |
| 18 | Dynamic/seasonal/weekend/demand/occupancy pricing under approval, competitor rates, ADR, RevPAR, occupancy, ALOS, pace, cancellations, forecast | Met | Pricing rules need a second approver; revenue dashboard; Insights |
| 19 | Incidents, classification, investigation, visitors, contractors, access logs, **key-card** integration, lost property, emergencies, fire inspections, **CCTV readiness**, security schedules (HR roster), emergency contacts, reports; privacy law | Met (ready) | Security; door-lock/key-card/CCTV systems post events (with clip links) to a token-protected intake; NDPA notes in ADMIN_MANUAL |
| 20 | Complaints, categories, assignment, tracking, escalation, feedback forms, **online review monitoring**, ratings, service recovery, response times; dashboards | **Partial** | All built; review-site feedback is captured by staff — no live review-site API is connected |
| 21 | Executive dashboard KPIs and interactive charts (incl. **guest demographics**, retention, forecasts); filters; PDF/Excel/CSV | Met | Dashboard, Insights (guest insights added 1.2) |
| 22 | Assistant answering authorised questions | Met | Ask EHMS (respects permissions) |
| 22 | Occupancy, revenue, demand, **guest preferences**, **cancellation risk**, inventory demand, **preventive maintenance prediction**, sentiment, **automated summaries** | Met | Insights: forecast, recommendations, cancellation risk, equipment failures, guest insights, daily summary (1.2) — all explainable, none act on their own |
| 22 | Automations: confirmations, check-in **and check-out reminders**, birthdays, **payment reminders**, housekeeping tasks, maintenance alerts, reorder alerts, leave notifications, daily reports | Met | Background worker; check-out-day reminder with balance due (1.2) |
| 23 | Email, SMS, WhatsApp, in-app; templates, history, failed messages, preferences | Met (ready) | Messaging; providers need your accounts. **Push notifications** for future mobile apps: see open items |
| 24 | Confirmations, registration forms, invoices, receipts, pro-forma, **payment vouchers**, POs, GRNs, payslips, contracts, quotations, statements, reports; PDF/Excel; secure storage | Met | PDFs throughout; vouchers (1.2); document store with access control and integrity checks |
| 25 | Audit of all listed actions with user, reference, action, old/new value, time, IP/device; tamper-protected | Met | `audit_logs` with database triggers blocking change/deletion |
| 26 | Payment gateways, email, SMS, WhatsApp, booking platforms, channel managers, accounting/payroll apps, locks, key cards, CCTV, access control, e-invoicing; secure auth, webhook validation, retries, logs; no simulated success | Met (ready) / open item | Built: Paystack, Flutterwave, SMTP, Termii SMS, WhatsApp Cloud, lock/key-card/CCTV/attendance intakes, open REST API, signed webhooks, retries and integration log. Vendor-specific channel-manager, bank, accounting, payroll and e-invoicing connectors: see open items |
| 27 | Normalised relational schema with all listed entities, keys, indexes, constraints, transactions | Met | 146 tables, 417 foreign keys — [DATA_DICTIONARY.md](DATA_DICTIONARY.md) |
| 28 | Navy/gold design, collapsible menu, top bar, hotel selector, profile, notifications, global search, **breadcrumbs**, tables, search/filter, **pagination**, confirmations, loading, errors, success, responsive; role dashboards | Met | Breadcrumb and paging added in 1.2 |
| 29 | Hashing, MFA, RBAC, validation, SQL injection and XSS protection, CSRF where applicable, secure API auth, HTTPS, rate limiting, sessions, encryption in transit, **encryption at rest where appropriate**, backup, audit, revocation, dependency updates; OWASP; privacy | **Partial** | All built and reviewed in [SECURITY.md](SECURITY.md). CSRF does not apply (tokens are not cookies). HTTPS via the reverse proxy in DEPLOYMENT.md. At rest: no card data stored, identity numbers masked, documents checksummed; database and backup encryption is done at disk level by the server, not field by field in EHMS |
| 30 | Scheduled and manual backups, secure storage, history, **verification**, restoration, disaster recovery, failure notifications, retention | Met | Administration → **Backups** (1.2): back up now, daily schedule, retention, history, test-restore verification, download, failure alerts; `python -m ehms.backup restore` |
| 31 | Unit, integration and end-to-end tests of every listed area | Met | 120 tests + browser E2E; mobile layout; security audit test |
| 32 | 23 deliverables | Met | App, dashboards, portal, backend, schema, migrations, API docs, auth, modules, finance, inventory, HR, AI, PDF/Excel, automations, audit, tests and reports, deployment config, backup/recovery, user guide (Word + online), administrator manual, technical docs |
| 33 | Phased delivery, progress register | Met | Releases 0.3 → 1.2 in [RELEASE_NOTES.md](RELEASE_NOTES.md); [PROGRESS.md](PROGRESS.md) |
| 34 | Final acceptance criteria 1–12 | Met | Each is covered by tests or this table |
| 34 | 13. Ready for controlled production deployment | Your step | Production configuration, guards and go-live checklist in DEPLOYMENT.md and ACCEPTANCE.md; deploying to your server is the hotel's step |

## SRS — sections beyond the functional requirements

| SRS section | Status | Notes |
|---|---|---|
| 4 Business rules BR-001 … BR-014 | Met | Each enforced in code and tested (overlap check, check-in conditions, settled folio, inspected rooms, verified payments, reversals, traceable stock, approval limits, payroll restriction, audited actions, tenant scope, AI never authorises, policy-based fees, closed periods) |
| 5 Performance | Met | p95 170 ms at 50 users ([PERFORMANCE.md](PERFORMANCE.md)); background jobs, indexes, pagination |
| 5 Availability 99.5 % | Your step | Depends on hosting; transactions, backups and logging built |
| 5 Security, privacy, scalability, usability, accessibility, maintainability, compatibility | Met | Labels and keyboard use throughout, contrast, responsive; Chrome/Edge/Firefox/Safari |
| 5 Backup and DR, RPO/RTO | Met / Your step | Automated, verified backups; RPO/RTO to be agreed (ADMIN_MANUAL) |
| 6 Database entities and data rules | Met | [DATA_DICTIONARY.md](DATA_DICTIONARY.md); soft deletion and history where retention requires |
| 7 Integrations (high/medium) | Met (ready) | Paystack, Flutterwave, email, SMS, WhatsApp |
| 7 OTA platforms, accounting software (medium) | Open item | Open REST API and exports available; no vendor connector |
| 7 Biometric devices, door access, channel manager, identity provider, smart room, BI tools (optional) | Met (ready) / Optional | Biometric clock and door-access intakes built (1.2); BI tools use CSV/XLSX exports or the API; channel manager, SSO and smart-room not built |
| 8 Interface, management and department dashboards, usability, **help and support access** | Met | Help & support page (1.2); public website with staff login link (1.3) |
| 9 Workflows (reservation → check-out, restaurant → folio, procurement, maintenance) | Met | Each runs end to end in tests |
| 10 Reports (operational, financial, commercial, HR, inventory) with filters and exports | Met | Reports, Insights, HR analytics |
| 11 Audit and internal control | Met | See master prompt §25 |
| 12 Testing strategy, critical scenarios, **backup restoration test**, defect register | Met | Restore tested automatically ([TEST_REPORT.md](TEST_REPORT.md)); defects listed per release in ACCEPTANCE.md and TEST_REPORT.md |
| 13 Acceptance — UAT completed and signed off; production approved | Your step | UAT scenarios and sign-off form in [ACCEPTANCE.md](ACCEPTANCE.md) |
| 15 Deliverables: architecture, design, ER and **data dictionary**, interface designs (screenshots), apps, migrations, API, integration docs, test plans/reports, UAT records, deployment, manuals, maintenance and backup docs, repository, training and handover | Met / Your step | All in `docs/`; UAT records and production deployment are completed by the hotel |

## Open items

| # | Item | Why it is open | What is needed |
|---|---|---|---|
| 1 | Page text in languages other than English | French covers menu, header, sign-in and booking engine | Translate remaining screens in `frontend/src/i18n.tsx` |
| 2 | Field-level encryption of stored personal data | Protected by masking, access control and disk encryption at the server | Optional enhancement if your auditors require it |
| 3 | Channel manager / OTA connectors | Each provider has its own API and contract | Choose a provider; connect through the REST API |
| 4 | Accounting, payroll, bank and e-invoicing software connectors | As above | Choose the software; exports and the API are ready |
| 5 | Live review-site monitoring | Review sites need partner API access | Staff record review feedback in Guest relations today |
| 6 | Push notifications to mobile apps | There is no mobile app yet (SRS future enhancement) | In-app, email, SMS and WhatsApp work now |
| 7 | Single sign-on, smart-room control | Marked optional in the SRS | — |
