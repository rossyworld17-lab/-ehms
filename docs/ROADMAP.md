# Roadmap

The master prompt defines 12 build phases; the SRS groups them into 6. Release 0.8 status:

| Master-prompt phase | SRS phase | Status in 0.8 |
|---|---|---|
| 1. Requirements, architecture, database design | 1 | **Done** — architecture, schema, migrations, OpenAPI |
| 2. Authentication, user management, hotel configuration | 1 | **Done** — RBAC, MFA, sessions, audit, multi-property configuration, taxes, payment methods |
| 3. Property management, rooms, reservations | 2 | **Done** — room board, categories & rates, reservations, availability, calendar, booking engine |
| 4. Front office & CRM | 2 | **Done (0.8)** — front office; CRM with loyalty, complaints & SLA escalation, surveys, feedback analysis, consent-based campaigns |
| 5. Restaurant POS, housekeeping, laundry | 3 | **Done** — POS & kitchen display (0.4), housekeeping (0.3), laundry (0.6) |
| 6. Accounting, finance, payment integrations | 4 | **Done (0.5)** — ledger, statements incl. cash flow, AP, cashier shifts, expense claims, bank reconciliation, budgets, period close, Paystack/Flutterwave with webhooks. Pending: credit/debit note documents, multi-currency conversion |
| 7. Inventory, procurement, suppliers | 4 | **Done (0.4)** — stores, WAC stock ledger, requisitions, counts, batches/expiry, recipes; suppliers, requisitions, quotations, POs with thresholds, GRN, three-way match, payments with WHT. Pending: FIFO costing option, supplier returns / debit notes, barcode scanner input |
| 8. HRMS, payroll | 4 | **Done (0.6)** — employees, rosters, attendance, leave, records, self-service, payroll with configurable statutory rules. Pending: recruitment pipeline |
| 9. Maintenance, security, events | 3–4 | **Done (0.7)** — assets, depreciation, preventive and corrective work orders, incidents, visitors, lost & found, access-event intake, events & banqueting. Pending: live CCTV / lock vendor adapters (intake API ready) |
| 10. Sales, marketing, revenue management | 5 | **Done (0.8)** — corporate/agent accounts with negotiated rates and statements, targets, seasons, approved occupancy-based rules, competitor rates, revenue dashboard with pickup and suggestions |
| 11. BI, AI and automation | 5 | Dashboard KPIs and forecast-on-books done; workflow automation (reminders, digests, alerts) done (0.5); permission-aware AI assistant, predictive models and scheduled reports pending |
| 12. Security/performance testing, deployment | 6 | Docker, CI (SQLite + PostgreSQL), backups/restore, security headers done; external penetration test, load test, connection pooling, UAT and training pending |

## Remaining releases
- **0.9** BI and AI assistant (permission-aware), forecasting, anomaly detection, scheduled reports, document store; group blocks & rooming lists, split folios, credit/debit notes, multi-currency, cancellation fees, recruitment.
- **1.0** Hardening, performance, final acceptance documentation.

## Items needing project-owner decisions (SRS §17)
Deployment model (single property / multi-property / SaaS), payment providers and fees, SMS/WhatsApp provider,
statutory tax configuration sign-off (VAT, withholding-tax rates per supplier category, PAYE bands, pension/NHF/NSITF/ITF rates), ID-capture policy,
data-retention periods, hosting location. New in 0.4: the purchase-order high-value approval threshold
(default ₦500,000) and invoice matching tolerance (default 0.5 %, minimum ₦100) are configurable defaults —
confirm them against your delegation-of-authority policy; decide per store whether sales may continue when
recipe stock runs out (default: blocked).
