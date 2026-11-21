# Roadmap

The master prompt defines 12 build phases; the SRS groups them into 6. Release 0.3 status:

| Master-prompt phase | SRS phase | Status in 0.3 |
|---|---|---|
| 1. Requirements, architecture, database design | 1 | **Done** — architecture, schema, migrations, OpenAPI |
| 2. Authentication, user management, hotel configuration | 1 | **Done** — RBAC, MFA, sessions, audit, multi-property configuration, taxes, payment methods |
| 3. Property management, rooms, reservations | 2 | **Done** — room board, categories & rates, reservations, availability, calendar, booking engine |
| 4. Front office & CRM | 2 | **Front office done** (check-in/out, moves, folios, night audit). CRM base done; loyalty points, campaigns, surveys and feedback pending |
| 5. Restaurant POS, housekeeping, laundry | 3 | **Housekeeping done.** Restaurant/bar POS, kitchen display, room service, laundry pending (room-service charges can already be posted to folios) |
| 6. Accounting, finance, payment integrations | 4 | **Core done** — double-entry ledger, TB/P&L/BS, payments, refunds with approval. Pending: Paystack/Flutterwave adapters & webhooks, bank reconciliation, budgets, period close, credit notes, cash-flow statement, cashier shifts, multi-currency |
| 7. Inventory, procurement, suppliers | 4 | Pending |
| 8. HRMS, payroll | 4 | Pending (statutory rules configurable: PAYE, pension, NHF, NSITF) |
| 9. Maintenance, security, events | 3–4 | Room blocks for maintenance done; work orders/assets, incident log, events & banquets pending |
| 10. Sales, marketing, revenue management | 5 | Pending (corporate accounts, rate rules, competitor rates, pickup/pace) |
| 11. BI, AI and automation | 5 | Dashboard KPIs and forecast-on-books done; permission-aware AI assistant, predictive models and scheduled reports pending |
| 12. Security/performance testing, deployment | 6 | Docker, CI, backups/restore, security headers done; external penetration test, load test, connection pooling, UAT and training pending |

## Next release (0.4) — proposed order
1. Payment gateway adapters (Paystack, Flutterwave) with signed webhooks; promo codes in the booking engine.
2. Restaurant & bar POS with kitchen display, table management, split/merge bills and post-to-room.
3. Inventory & stores (recipes → automatic stock deduction), procurement with approval thresholds.
4. Cashier shifts and reconciliation, bank reconciliation, period close.
5. Notification templates, SMS/WhatsApp adapter, reservation reminders via a background worker.

## Items needing project-owner decisions (SRS §17)
Deployment model (single property / multi-property / SaaS), payment providers and fees, SMS/WhatsApp provider,
statutory tax configuration sign-off, ID-capture policy, data-retention periods, hosting location.
