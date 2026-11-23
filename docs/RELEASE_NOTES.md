# Release notes

## 1.1.1 — reliable start-up
- The interface is shipped pre-built in `frontend/dist`; running EHMS needs only Python. An old interface build
  could silently hide modules (Food & Beverage and Supply chain appeared missing for the super administrator).
- The server now compares the interface build with its own version and shows a red banner, and logs a warning,
  when they differ; interface files are always revalidated by the browser so an upgrade is never hidden by its cache.
- `start_demo_windows.bat` starts the demo on Windows with a double-click.

## 1.1 — full HR suite
- HR dashboard with alerts (probation, contract end, expiring certificates, unlinked logins), birthdays and anniversaries.
- Employee records gain line manager, probation and contract end dates, job history (promotions, transfers, pay
  changes, confirmations), training and certification register, leave adjustments.
- Performance appraisals: draft, share, employee acknowledgement with comment.
- Staff requests with HR approval: salary advance, loan, employment letter (PDF), change of details (applied on
  approval), shift swap (roster updated), confidential grievance, other.
- Leave: cancellation by staff, cancellation or early return by HR, leave calendar, balances for all staff, public
  holidays excluded from day counts.
- HR can give an employee a system login (non-admin roles, temporary password); recording an exit suspends the login.
- My HR rebuilt with tabs: overview, leave, requests, profile, appraisals and training, payslips and attendance.
- Three new permissions (`hr.requests.approve`, `hr.performance`, `hr.accounts`) for the HR manager.
- Fix: a cancellation policy with 0 free hours no longer allows a free cancellation.

## 1.0 — production readiness
- Security review ([SECURITY.md](SECURITY.md)): production start-up guards (strong shared secret key, no demo data),
  restricted trust of forwarded client addresses, stricter Content-Security-Policy, rate limits on every public
  endpoint, SQL identifier validation, and a permanent automated audit that every route is authorised and scoped.
- Performance review ([PERFORMANCE.md](PERFORMANCE.md)): PostgreSQL connection pooling, range queries for the
  dashboard and occupancy report, 20 new indexes; load-test and data-volume tools in `backend/tools/`.
- Acceptance documentation ([ACCEPTANCE.md](ACCEPTANCE.md)): UAT scenarios, go-live checklist, training plan, sign-off.
- Notification panel closes with Escape, an outside click or navigation.

## 0.95 — completing the scope
Cancellation policies with automatic fees and audited waivers; group blocks, rooming lists, release after cut-off,
master folio; extra folios and charge transfers; credit and debit notes with approval; exchange rates and
foreign-currency payments; optional FIFO costing; recruitment pipeline. All 127 SRS requirements traced as implemented.

## 0.9 — intelligence and documents
Multi-property analytics with comparison, occupancy history, HR analytics, scheduled reports; explainable forecast,
unusual-transaction review, rate and reorder recommendations; Ask EHMS assistant (built-in, optional Claude engine);
document store with versions, integrity check, retention, legal hold and access history.

## 0.8 — guest relations, sales and revenue
Loyalty, complaints with SLA and escalation, post-stay surveys and feedback analysis, consent-based campaigns;
corporate and agent accounts with negotiated rates, targets, seasons, approved pricing rules, competitor rates,
revenue dashboard; quoted rates locked on bookings.

## 0.7 — maintenance, security, events
Asset register and depreciation, preventive and corrective work orders; incidents, visitors, lost and found,
access-control intake; events and banqueting with quotations, folios and profitability.

## 0.6 — laundry, HR, payroll
Guest and linen laundry; employees, rosters, attendance, leave, self-service; payroll with configurable statutory rules.

## 0.5 — payments and finance operations
Paystack and Flutterwave with webhooks; promo codes; expense claims, bank reconciliation, budgets, cash flow,
period close; communication centre and background worker.

## 0.4 — food & beverage and supply chain
POS and kitchen display, cashier shifts; inventory with weighted-average costing, batches and recipes;
procurement from requisition to payment with withholding tax.

## 0.3 — core platform
Authentication with MFA, RBAC, audit; multi-property configuration; rooms, reservations, booking engine; front
office and folios; double-entry accounting; housekeeping; reports.

## Upgrading
Start the new version against your existing database: migrations run automatically, new permissions are granted to
system roles once, and books stay balanced. Take a backup first ([DEPLOYMENT.md](DEPLOYMENT.md)).
