# Roadmap

The master prompt defines 12 build phases; the SRS groups them into 6. Release 0.4 status:

| Master-prompt phase | SRS phase | Status in 0.4 |
|---|---|---|
| 1. Requirements, architecture, database design | 1 | **Done** — architecture, schema, migrations, OpenAPI |
| 2. Authentication, user management, hotel configuration | 1 | **Done** — RBAC, MFA, sessions, audit, multi-property configuration, taxes, payment methods |
| 3. Property management, rooms, reservations | 2 | **Done** — room board, categories & rates, reservations, availability, calendar, booking engine |
| 4. Front office & CRM | 2 | **Front office done** (check-in/out, moves, folios, night audit). CRM base done; loyalty points, campaigns, surveys and feedback pending |
| 5. Restaurant POS, housekeeping, laundry | 3 | **POS, kitchen display and housekeeping done (0.4).** Laundry module pending (laundry charges can already be posted to folios; linen and detergent are stocked through inventory) |
| 6. Accounting, finance, payment integrations | 4 | **Core done** — double-entry ledger, TB/P&L/BS, payments, refunds with approval, accounts payable (0.4), cashier shifts (0.4). Pending: Paystack/Flutterwave adapters & webhooks, bank reconciliation, budgets, period close, credit notes, cash-flow statement, multi-currency |
| 7. Inventory, procurement, suppliers | 4 | **Done (0.4)** — stores, WAC stock ledger, requisitions, counts, batches/expiry, recipes; suppliers, requisitions, quotations, POs with thresholds, GRN, three-way match, payments with WHT. Pending: FIFO costing option, supplier returns / debit notes, barcode scanner input |
| 8. HRMS, payroll | 4 | Pending (statutory rules configurable: PAYE, pension, NHF, NSITF) |
| 9. Maintenance, security, events | 3–4 | Room blocks for maintenance done; maintenance materials can be requisitioned from stores (0.4); work orders/assets, incident log, events & banquets pending |
| 10. Sales, marketing, revenue management | 5 | Pending (corporate accounts, rate rules, competitor rates, pickup/pace) |
| 11. BI, AI and automation | 5 | Dashboard KPIs (now incl. outlet revenue, low stock, pending POs) and forecast-on-books done; permission-aware AI assistant, predictive models and scheduled reports pending |
| 12. Security/performance testing, deployment | 6 | Docker, CI (SQLite + PostgreSQL), backups/restore, security headers done; external penetration test, load test, connection pooling, UAT and training pending |

## Next release (0.5) — proposed order
1. Payment gateway adapters (Paystack, Flutterwave) with signed webhooks; promo codes in the booking engine.
2. Laundry: guest laundry orders with item tracking and billing to folio; internal linen cycle.
3. Cashier-level bank reconciliation, period close, credit notes, cash-flow statement.
4. Notification centre in the UI (in-app messages such as "order ready" are already recorded), templates, SMS/WhatsApp adapter, reservation reminders via a background worker.
5. Maintenance work orders and asset register (consuming spare parts from stores).

## Items needing project-owner decisions (SRS §17)
Deployment model (single property / multi-property / SaaS), payment providers and fees, SMS/WhatsApp provider,
statutory tax configuration sign-off (VAT, withholding-tax rates per supplier category), ID-capture policy,
data-retention periods, hosting location. New in 0.4: the purchase-order high-value approval threshold
(default ₦500,000) and invoice matching tolerance (default 0.5 %, minimum ₦100) are configurable defaults —
confirm them against your delegation-of-authority policy; decide per store whether sales may continue when
recipe stock runs out (default: blocked).
