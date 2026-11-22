# User acceptance testing, go-live and sign-off — release 1.0

Run these scenarios on a **staging** server loaded with your own configuration (rooms, rates, taxes, staff) — not
the demo data — using the account of a real person in each role. Record Pass / Fail and the defect reference.
Automated tests already cover each scenario (see [TEST_REPORT.md](TEST_REPORT.md)); UAT confirms the system fits
your hotel's way of working.

## 1. Scenarios

| # | Role | Scenario | Expected result | Pass / Fail |
|---|---|---|---|---|
| 1 | Administrator | Create a staff user with a role and one hotel; sign in as that user | User sees only that hotel and the menus of the role | |
| 2 | Any user | Enrol in two-step verification; sign out and in | Code requested at sign-in; sign-in works | |
| 3 | Reservations | Book a room for next week with a corporate account | Negotiated rate applied and locked; confirmation email queued (or "not configured") | |
| 4 | Reservations | Cancel a booking inside and outside the free window | No fee inside; fee posted to the folio outside; waiver only for authorised staff with a reason | |
| 5 | Receptionist | Walk-in, check-in, post a restaurant charge, take part payment in USD, settle the rest, check out | Converted USD amount shown; check-out blocked until settled; room becomes dirty | |
| 6 | Receptionist | Split a company bill into a second folio and transfer the dinner | Balances move; both folios must be settled before check-out | |
| 7 | Housekeeping | Clean the departed room; supervisor inspects | Room available for sale only after inspection | |
| 8 | Sales | Create a group block, load a rooming list (CSV), release unpicked rooms | Held rooms unavailable to others; bookings at the group rate; released rooms back on sale | |
| 9 | Front office manager | Raise a credit note on a closed folio; finance approves | Folio reopened in credit; revenue and VAT reduced; refund request possible; note PDF | |
| 10 | Cashier / waiter / chef | Open a shift, take a dine-in order, kitchen prepares, settle in cash with change, charge another order to a room | Ticket on kitchen display; stock deducted by recipe; room charge on the guest folio; shift variance shown at close | |
| 11 | Storekeeper / procurement | Requisition → approval → quotations → PO → approval → goods received → invoice → payment with WHT | Each approval by a different person; stock and payables correct; GRNI clears | |
| 12 | Inventory manager | Switch to FIFO (with accounting) and issue stock | Issue valued from the oldest receipts | |
| 13 | Finance | Run night audit; review trial balance, P&L, balance sheet, cash flow; close last month | Books balance; postings into the closed month refused | |
| 14 | Finance | Record today's exchange rates; reconcile a bank statement import | Rates used for foreign payments; reconciliation difference zero | |
| 15 | HR | Recruit (opening → applicant → offer → hire), roster, attendance, leave approval | Employee created from the hire; leave reduces balances and marks attendance | |
| 16 | HR / finance | Prepare payroll, approve (different person), pay, remit PAYE; employee downloads payslip | Statutory deductions per configured rules; journal posted; payslip only to its owner | |
| 17 | Maintenance | Report a fault that blocks a room; technician completes; manager verifies | Room out of sale until verified, then dirty with a cleaning task | |
| 18 | Security | Log a visitor, an incident (restricted category) and a lost-and-found item | Restricted incidents hidden from others; valuables released only with ID | |
| 19 | Sales | Event enquiry → tentative → confirmed → deposit → invoice | Venue clash prevented; event folio and profitability correct | |
| 20 | Guest service | Log a complaint; let it pass its deadline; check escalation; send a survey; review feedback insights | Escalation notification; survey answered online; low score opens a complaint | |
| 21 | General manager | Insights: analytics with comparison, forecast, unusual transactions (review one), recommendations | Figures match reports; a flag can't be reviewed by the person it concerns | |
| 22 | General manager | Ask EHMS: "What was revenue yesterday?", "What needs reordering?" — then ask a receptionist to try | Answers name their source; receptionist gets no financial answer | |
| 23 | Any | Upload an ID scan as reception; try to open it; open it as a manager; check access history | Reception cannot reopen it; the attempt and the manager's view are logged | |
| 24 | Finance | Schedule the daily revenue report to two people | Report appears in Documents next morning; only permitted recipients notified | |
| 25 | Guest | Book on the booking engine with a promo code and pay online (test mode keys) | Discount applied; booking confirmed by the provider's webhook | |
| 26 | Administrator | Restore last night's backup to staging | Data and documents restored; books balanced | |

## 2. Go-live checklist
- [ ] Production `.env`: strong `EHMS_SECRET_KEY`, `EHMS_ENV=production`, `EHMS_SEED_DEMO=0`, `EHMS_PUBLIC_URL`,
      `FORWARDED_ALLOW_IPS` = reverse-proxy address; SMTP / SMS / WhatsApp / payment keys (live) configured and tested.
- [ ] TLS certificate on the reverse proxy; HTTP redirected to HTTPS; proxy body limit ≥ 16 MB; login rate limit at the proxy.
- [ ] Hotel profile, taxes (VAT, consumption tax where applicable), service charge, payment methods, cancellation policies,
      room categories, rooms, rates, seasons, outlets, menu and recipes, stores and opening stock, suppliers, chart of accounts
      mapping, statutory payroll rules, leave types reviewed and signed off by the responsible managers.
- [ ] Opening balances posted (guest deposits, receivables, payables, stock, fixed assets) and agreed to the old system.
- [ ] Future reservations migrated and spot-checked (dates, rates, deposits).
- [ ] Users created from the staffing list; roles reviewed; MFA enforced for administrators, finance and HR.
- [ ] Daily backup running; off-site copy configured; restore tested (scenario 26).
- [ ] Independent penetration test completed and high findings closed ([SECURITY.md](SECURITY.md)).
- [ ] Night-audit time, worker running (reminders, digests, scheduled reports, anomaly scan) verified.
- [ ] Staff trained (below); support contacts and escalation path published.
- [ ] Parallel run or cut-over plan agreed (recommended: cut over after a night audit, with the old system read-only).

## 3. Training plan (suggested)

| Audience | Duration | Content | Material |
|---|---|---|---|
| Front office | 2 × 2 h | reservations, groups, check-in/out, folios, payments, cancellations, night audit | USER_GUIDE: front desk, folios, groups |
| Housekeeping & maintenance | 1 h | tasks, inspection, fault reporting, mobile use | USER_GUIDE |
| F&B | 2 h | POS, kitchen display, shifts, menu | USER_GUIDE: POS |
| Stores & procurement | 2 h | stock, requisitions, POs, receiving, invoices | USER_GUIDE |
| Finance | 3 h | ledger, reports, approvals, reconciliation, notes, rates, period close, payroll approval | USER_GUIDE, ADMIN_MANUAL |
| HR | 2 h | employees, recruitment, rosters, leave, payroll preparation | USER_GUIDE |
| Managers | 1.5 h | dashboard, Insights, Ask EHMS, approvals, documents | USER_GUIDE |
| Administrators | 2 h | users, roles, settings, messaging, backups, upgrades | ADMIN_MANUAL, DEPLOYMENT |

## 4. Sign-off

| Area | Name | Role | Decision (accept / accept with conditions / reject) | Date | Signature |
|---|---|---|---|---|---|
| Front office & reservations | | | | | |
| Housekeeping & maintenance | | | | | |
| Food & beverage | | | | | |
| Stores & procurement | | | | | |
| Finance & payroll | | | | | |
| Human resources | | | | | |
| Sales, CRM & revenue | | | | | |
| IT & security | | | | | |
| General manager (overall) | | | | | |

Open conditions and defects at sign-off are listed with an owner and a due date in [PROGRESS.md](PROGRESS.md).
