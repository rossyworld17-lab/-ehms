# Roadmap

The master prompt defines 12 build phases; the SRS groups them into 6. Release 1.0 status:

| Master-prompt phase | SRS phase | Status in 1.0 |
|---|---|---|
| 1. Requirements, architecture, database design | 1 | **Done** — architecture, schema, migrations, OpenAPI |
| 2. Authentication, user management, hotel configuration | 1 | **Done** — RBAC, MFA, sessions, audit, multi-property configuration, taxes, payment methods |
| 3. Property management, rooms, reservations | 2 | **Done** — room board, categories & rates, reservations, availability, calendar, booking engine |
| 4. Front office & CRM | 2 | **Done (0.8)** — front office; CRM with loyalty, complaints & SLA escalation, surveys, feedback analysis, consent-based campaigns |
| 5. Restaurant POS, housekeeping, laundry | 3 | **Done** — POS & kitchen display (0.4), housekeeping (0.3), laundry (0.6) |
| 6. Accounting, finance, payment integrations | 4 | **Done (0.5)** — ledger, statements incl. cash flow, AP, cashier shifts, expense claims, bank reconciliation, budgets, period close, Paystack/Flutterwave with webhooks. Credit/debit notes and foreign-currency payments added in 0.95 |
| 7. Inventory, procurement, suppliers | 4 | **Done (0.4)** — stores, WAC stock ledger, requisitions, counts, batches/expiry, recipes; suppliers, requisitions, quotations, POs with thresholds, GRN, three-way match, payments with WHT. FIFO costing option added in 0.95; barcode scanners work as keyboard input |
| 8. HRMS, payroll | 4 | **Done (0.6)** — employees, rosters, attendance, leave, records, self-service, payroll with configurable statutory rules. Recruitment pipeline added in 0.95 |
| 9. Maintenance, security, events | 3–4 | **Done (0.7)** — assets, depreciation, preventive and corrective work orders, incidents, visitors, lost & found, access-event intake, events & banqueting. Pending: live CCTV / lock vendor adapters (intake API ready) |
| 10. Sales, marketing, revenue management | 5 | **Done (0.8)** — corporate/agent accounts with negotiated rates and statements, targets, seasons, approved occupancy-based rules, competitor rates, revenue dashboard with pickup and suggestions |
| 11. BI, AI and automation | 5 | **Done (0.9)** — filtered multi-property analytics with period comparison, occupancy history, HR analytics, scheduled reports, explainable forecast, unusual-transaction review, rate/reorder recommendations, permission-aware assistant (built-in, optional Claude), document store; workflow automation since 0.5 |
| 12. Security/performance testing, deployment | 6 | **Done (1.0)** — Docker, CI (SQLite + PostgreSQL), backups/restore, security review and hardening, load test and optimisation, connection pooling, UAT scenarios, training plan, go-live checklist. To be done by the hotel: independent penetration test, UAT execution and sign-off |

## After 1.0 (integrations that need third-party accounts or hardware)
- Channel manager / OTA connectivity (two-way availability, rates and bookings).
- Vendor adapters for door locks / key-card encoders (the access-event intake API is ready) and CCTV references.
- FIRS e-invoicing once the hotel is onboarded to the e-invoicing system.
- Native mobile apps (the web app already works on phones and tablets).
- Foreign-currency bank accounts with revaluation, if the hotel holds foreign currency.

## Items needing project-owner decisions (SRS §17)
Deployment model (single property / multi-property / SaaS), payment providers and fees, SMS/WhatsApp provider,
statutory tax configuration sign-off (VAT, withholding-tax rates per supplier category, PAYE bands, pension/NHF/NSITF/ITF rates), ID-capture policy,
data-retention periods, hosting location. New in 0.4: the purchase-order high-value approval threshold
(default ₦500,000) and invoice matching tolerance (default 0.5 %, minimum ₦100) are configurable defaults —
confirm them against your delegation-of-authority policy; decide per store whether sales may continue when
recipe stock runs out (default: blocked).
