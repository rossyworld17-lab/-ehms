# Test report — release 1.1

## Environment
Python 3.13, SQLite 3 (test database rebuilt for every test) and PostgreSQL 16 (full suite run locally against
a PostgreSQL 16 server; CI runs it on every push), Chromium via Playwright for browser tests.

## Automated API / integration tests — 98 passed, 0 failed (SQLite and PostgreSQL)
`cd backend && python -m pytest -q` · `TEST_DATABASE_URL=postgresql://… python -m pytest -q`

| Area | Tests | What is proven |
|---|---|---|
| **HR suite (1.1)** | 8 | employee applies for leave, HR approves, holidays excluded from days, staff cancels, HR ends leave early with days returned; staff requests: change of details applied on approval, shift swap swaps roster shifts, letter PDF only for owner and HR, advance above one month's pay refused, approved advance notifies payroll and is completed by payroll only, nobody decides their own request; grievances hidden from HR officers; appraisals draft → share → acknowledge, no self-appraisal, drafts invisible to staff; job history applies promotion; training expiry list; logins issued by HR cannot carry admin roles; exit suspends login and revokes sessions; HR dashboard alerts |
| Authentication & RBAC | 11 | login, wrong password logged, lockout after 5 failures, unauthenticated rejection, permission enforcement, hotel scoping, logout & admin session revocation, full MFA enrolment and MFA-gated sign-in, suspension blocks login and is audited, privilege-escalation blocked, scrypt hashing |
| Reservations | 8 | creation & reference format, per-night quote with 10 % service charge + 7.5 % VAT, honest `not_configured` email status, same room cannot be double-booked (back-to-back allowed), category cannot be oversold without permission + reason, rate override needs permission, max occupancy, modify / cancel / no-show rules, availability decrements, duplicate-guest detection, identity masking |
| Front office & finance | 10 | full stay: walk-in → check-in → F&B charge (exact net/svc/tax) → blocked check-out with balance → payment → check-out → room dirty → housekeeping → inspection → room available → trial balance & balance sheet balanced; uninspected room refused; payment idempotency & duplicate reference; online payment not faked (501); refund maker-checker; charge reversal; journal lines and audit logs cannot be modified (DB triggers); night audit; room move & block rules; manual journal must balance |
| Booking engine & reports | 5 | public booking, lookup, cancellation; reports JSON/XLSX/CSV/PDF, invoice PDF, financial reports restricted; dashboard KPIs; inclusive and exclusive tax maths; OpenAPI + health + security headers |
| **POS & kitchen (0.4)** | 5 | waiter cannot settle or discount; kitchen display ticket per table; chef prepares/readies but cannot mark served; settlement needs an open shift; exact totals (₦19,000 → SC ₦1,900 → VAT ₦1,567.50 → ₦22,467.50); cash over-tender gives change, card/room cannot be over-tendered, card needs a reference; recipe ingredients deducted from the right stores (food from kitchen, drinks from bar); cost of sales posted; receipt PDF; shift expected cash and variance note; **charge to room appears on the guest folio** with net + service + tax = total; split bill, merge, item void needs reason, discount needs reason, split tender, order void; **sale blocked atomically when ingredients run out** (no payment, no stock change); menu & recipe management permissions; sold-out items cannot be ordered |
| **Inventory (0.4)** | 2 | requisition maker-checker; issue to housekeeping posts to supplies expense; transfers keep value; insufficient stock refused; wastage write-off; storekeeper cannot adjust; stock count posts the variance; stock movements are append-only (DB trigger); expiry and low-stock alerts; opening balances against equity |
| **Procurement (0.4)** | 2 | requisition approval (not own); quotation comparison picks the cheapest per line; PO above ₦500,000 needs `procurement.approve_high`; creator cannot approve; GRN refuses over-receipt and missing expiry dates; partial and final receipts update PO status and stock; invoice variance needs an approval note; invoice approval clears GRNI to zero and books the price variance; supplier invoice numbers unique per supplier; payments with 5 % WHT, idempotent, cannot exceed the balance; AP reaches zero; service lines expensed at GRN; invoices without a PO need an expense account; supplier performance and masked bank details |
| **Cross-cutting (0.4)** | 2 | permission upgrade grants new permissions to existing system roles exactly once and respects later removals; dashboard shows outlet revenue and supply-chain counts; new reports listed only to permitted roles; report exports audited |

| **Online payments (0.5)** | 5 | payment link emailed; forged webhook rejected (401); signed webhook for an unpaid transaction credits nothing; paid → folio credited exactly once although webhook and return page both arrive; tampered amount not credited (`amount_mismatch`); provider down → 3 retries then HTTP 502, nothing taken; no provider → 501; booking-engine prepayment with Flutterwave confirms the reservation; integration log written. Provider APIs are simulated by a fake transport matching their documented request/response format |
| **Promo codes (0.5)** | (in the above) | invalid percentage rejected; discount shown in availability; invalid code explained; usage limit enforced; code stored on the reservation |
| **Finance operations (0.5)** | 3 | expense claim maker-checker and payment journal; bank statement import, auto-match, unmatched bank charge, zero difference; reconciliation restricted; budget vs actual; cash flow closing = cash GL balance; financing classified; current month cannot be closed; posting into a closed month refused; reopen needs a reason |
| **Messaging & worker (0.5)** | 1 | template override with unknown placeholder renders safely; day-before reminder by email (honestly `not_configured` without SMTP) and SMS (delivered through the fake provider); idempotent reruns; retry refused without a provider; low-stock digest reaches inventory managers in-app; mark read / read all; users cannot touch others' notifications |

| **Laundry (0.6)** | 1 | price list & 50 % express surcharge; damaged item needs a note and is not charged; delivery only after quality check; no going back a stage; cancellation only before processing; delivery posts the laundry charge to the folio; internal linen batch not billed; lost items in the summary; accountant has no access |
| **HR (0.6)** | 2 | employee number generated; onboarding record; department manager sees no pay, masked bank details and no confidential records; exit needs a reason; self-service leave with working-day count, overlap and balance checks; staff cannot approve; manager approval marks attendance as leave and notifies the employee; self clock-in/out rules; managers cannot approve their own leave |
| **Payroll (0.6)** | 2 | hand-checked payslip (₦350,000 fixed pay → pension ₦28,000, NHF ₦5,000, PAYE ₦39,560 under the 2026 bands); absence deduction, overtime, bonus, loan recovery; preparer cannot approve; approval posts net, PAYE and other liabilities and reduces loan balances; draft-only adjustments; payment needs a reference and clears salaries payable; PAYE remitted once; bank schedule; employees download only their own approved payslips; rule validation and permission |

| **Maintenance (0.7)** | 2 | housekeeping issue raises a work order; receptionist's urgent fault blocks the room; technician cannot assign; assignment notifies; start before complete; spare part reduces stock and posts repairs expense; resolution required; technician cannot verify own work; verification returns the room to service as dirty with a cleaning task; preventive orders raised once per schedule and the schedule rolls forward on verification; opening-balance capitalisation, monthly depreciation once per month, capitalised cost locked |
| **Security (0.7)** | 2 | high-severity alert to security staff; receptionist can report but not browse; resolution required; notes and police reference; harassment auto-restricted and hidden from non-sensitive users; visitor ID masked for non-managers; sign-out once; valuable lost item stored in the safe, released only with ID check, not disposable before the holding period; emergency contacts for all staff; access-event intake rejects missing/wrong tokens and records events |
| **Events (0.7)** | 1 | enquiries never block; overlapping ballroom hold refused (venue clash); capacity enforced; confirmation opens an event folio; quotation totals with tax and service charge; quotation PDF; deposit on the folio; sales cannot invoice; complete only after invoice; finance invoices once to events and F&B revenue; folio balance = total − deposit; profit = net − direct costs; locked after invoicing; venue calendar and pipeline |
| **CRM (0.8)** | 3 | enrolment needs the guest's agreement; points earned once on check-out from settled spend with tier bonus; redemption below the minimum or above the balance refused; redemption posts a balanced allowance and reduces the balance; survey link single-use; a low score opens a complaint; sentiment and themes; complaint SLA by severity, receptionist can log but not view all, resolution required, overdue complaints escalated once by the worker; campaigns reach consenting guests only, opt-out honoured, send once |
| **Sales & revenue (0.8)** | 2 | negotiated account rate applied; inactive account refused; season adjustment; occupancy rule inactive until approved, proposer cannot approve; **quoted rates locked on the booking** (a later rule does not reprice it, room-night posting uses the locked rate); targets achievement; revenue dashboard KPIs and pickup |
| **Documents (0.9)** | 2 | file-type whitelist, content-signature mismatch, invalid base64 and size limit refused; path in file name stripped; ID scan confidential by default and write-only for reception (hidden in lists, download refused and the refusal logged); GM downloads identical bytes; new version supersedes the old; lowering confidentiality restricted; deletion refused before retention and under legal hold, allowed after with the file erased and the record kept; retention only extendable; tampered file refused (integrity check) and logged; employee files need `hr.records`; employee documents need `hr.view` to list |
| **BI (0.9)** | 2 | analytics KPIs, weekly series, previous-period and previous-year comparison; financial revenue equals the ledger's revenue accounts exactly and GOP = revenue − expenses; invalid granularity and inaccessible hotels refused; occupancy history and HR analytics; sales manager gets no financials and no HR analytics; waiter refused; scheduled report refused for a recipient without the report permission; generated as xlsx into Documents and notified; a user without the report permission cannot open it; due once per day; schedule suspends itself when its creator is suspended |
| **AI (0.9)** | 4 | anomaly scan flags a large allowance and a manual cash journal, never twice; flag about yourself cannot be reviewed by you; accountant may view but not decide; note required; closed flags stay closed; forecast ranges consistent and revenue hidden without `reports.financial`; recommendations filtered by permission; proposed rule awaits approval and cannot be approved by its proposer; reorder recommendation creates a submitted requisition; assistant refused without `ai.assistant`, answers occupancy/revenue/forecast/feedback from tools, refuses to act, explains missing permissions, logs every question; Claude engine is offered only permitted tools, a forbidden tool call returns a permission error, and a provider failure falls back to the built-in engine (provider simulated) |
| **Cancellation & groups (0.95)** | 3 | fee preview and posting inside the late window, none when early; waiver refused without permission, recorded with reason when allowed; non-refundable no-show = full stay; used policy cannot be re-priced; online cancellation refused after the free window; block larger than free rooms refused; held rooms reduce availability for others; rooming list creates bookings at the group rate (bad rows reported, good rows kept); pickup does not reduce availability twice; allotment cannot go below pickup; release frees exactly the unpicked rooms; worker releases after cut-off; reception cannot create blocks; master-folio billing posts room nights to the group folio and the guest checks out with nothing due |
| **Folios & notes (0.95)** | 2 | extra folio opened; whole and partial transfers move balances without touching the ledger; a line cannot be transferred twice; check-out blocked until every folio is settled, then extra folios close; credit note cannot exceed charges; FOM cannot approve, finance cannot approve its own note; approval reopens a closed folio, reduces room revenue and VAT exactly; decided notes stay decided; rejection needs a note; debit note approved; PDF |
| **FX, FIFO, recruitment (0.95)** | 3 | rate entry restricted, base currency and invalid rates refused, big jumps warned; foreign payment converted at the latest rate with both amounts stored; idempotent; unknown currency refused; WAC vs FIFO issue values hand-checked (180,000 vs 140,000) and the remaining value equals the dearer batch; recruitment visible only with `hr.view`; salary range validated; duplicate applicant refused; stages cannot be skipped; offer needs salary and date; rejection needs a note; hire creates the employee with the offered position/date and moves the CV; anonymisation of unsuccessful applicants |
| **Hardening (1.0)** | 5 | automated audit of all 383 routes: every non-public route has a permission (or is self-service), every route with a record id checks hotel/organisation/user scope, every public route is rate-limited; SQL identifier validation; production refuses weak/placeholder secret keys and demo data; CSP and security headers; 413 for oversized requests; 429 after the public rate limit |

Every 0.4 test ends with a ledger integrity check: total debits equal total credits, **and** the stock
sub-ledger value equals the Inventory GL account balance.

## Browser end-to-end tests — passed
`python frontend/e2e/smoke.py` (app running with demo data). Fails on any JavaScript error or error banner.

1. Administrator visits all screens, now including Point of sale, Kitchen display, Menu & outlets, Inventory
   (all tabs) and Procurement (all tabs).
2. Receptionist walk-in → check-in → folio charge → payment → check-out. Housekeeping inspection. Public booking.
3. **Cashier opens a shift, sells a takeaway meal and settles it in cash (0.4).**
4. Finance operations (all tabs), Promotions, Messaging (run reminders), notification bell (0.5).
5. Laundry price list, HR tabs and employee profile; HR manager prepares payroll in the UI and the finance manager approves it (0.6).
6. Maintenance, security and events tabs; event detail; sales manager confirms an event in the UI (0.7).
7. Booking engine with promo code WELCOME10 shows the discount; the payment return page handles an unknown reference (0.5).
8. Mobile layout (390 px) including My HR self clock-in and reporting a fault (0.7).
9. Guest relations and Sales & revenue (all tabs); a guest completes the post-stay survey on a phone-sized screen (0.8).
10. Insights (all tabs), Ask EHMS (two questions), Documents (open a document and its access history) (0.9).
11. Group block detail, credit-note queue, exchange rates, cancellation policies, stock costing, applicant record (0.95).

Additional scripted browser walkthroughs for 0.4 (run during development): waiter → kitchen → cashier dine-in
sale with change; room-service order charged to a room; full procurement cycle across five roles
(requisition → approval → two quotations → PO → approval → GRN → invoice → approval → payment with WHT);
stock requisition approve/issue; trial balance balanced at the end; no console errors.

## Upgrade test — passed
A database created by release 0.3 (with its demo data) was started with 0.4: migration 0003 applied, new
ledger accounts added, system roles received the new permissions once, the 0.4 demo outlets/menu/stores/
suppliers were added once (re-running is a no-op), existing reservations kept, books balanced.

## Load and security testing (1.0)
See [PERFORMANCE.md](PERFORMANCE.md) (load test with one year of history: 0 errors at 50 virtual users) and
[SECURITY.md](SECURITY.md) (review method, findings and fixes).

## Defects found and fixed during 1.0 testing
- Without a configured secret key each worker process signed tokens with its own key → production guard.
- Forwarded client addresses were trusted from any source → only from the reverse proxy.
- Dashboard trend and occupancy report ran a few queries per day → range queries (identical results, verified).
- Notification panel could not be closed by keyboard or touch → closes on Escape, outside click, navigation.

## Upgrade test (0.95) — passed
A 0.9 demo database upgraded twice with 0.95: migration 0009 applied, new permissions granted, policies, rates,
group block, opening and credit note added once, books balanced.

## Defects found and fixed during 0.95 testing
- Group reservations stored the rack rate as the nightly rate (the locked rate was right) → the group rate is stored, also when a group booking is changed.
- Loading a rooming list as a sales manager failed for lack of guest-profile permission → loading a rooming list authorises creating those guests.
- A test used a literal `%` in SQL, which PostgreSQL's driver rejects → parameter.

## Upgrade test (0.9) — passed
A 0.8 demo database upgraded twice with 0.9: migration 0008 applied, BI/AI/document permissions granted to
system roles, demo documents, schedules and one anomaly flag added once, books balanced.

## Defects found and fixed during 0.9 testing
- A refused document access was rolled back with the request, so it was missing from the access history → refusals and failed integrity checks are logged in their own transaction.
- Listing documents for an employee did not require `hr.view` → it does.
- Two app processes could each generate the same scheduled report → a once-per-day guard in the shared job table.
- The assistant's speech bubbles inherited the page's two-column layout → class renamed.

## Upgrade test (0.8) — passed
A database created by release 0.7 with demo data was upgraded with 0.8 twice: migration 0007 applied, CRM and
sales permissions granted, 0.8 demo data added once, books balanced.

## Defects found and fixed during 0.8 testing
- PostgreSQL treated `%` inside SQL text as a parameter marker in the revenue queries → patterns passed as parameters.
- A failed survey submission replaced the whole form with "Survey not found" → submission errors now show inline.
- The last chart axis label could overlap the one before it → skipped when too close.
- Browser test could click "Record payment" before the amount due had loaded → waits for the amount.

## Defects found and fixed during 0.7 testing
- Staff who can report faults could not list or open their own reports → reporters see their own work orders.
- Event profit showed "100% margin" before any costs were recorded → states that no costs are recorded yet.

## Defects found and fixed during 0.6 testing
- Laundry staff could not search in-house guests (the lookup was POS-only) → laundry has its own lookup.
- Payroll header showed the preparer's user ID → shows names of preparer and approver.

## Defects found and fixed during 0.5 testing
- PostgreSQL has no `LIKE` on DATE columns (birthday job) → compare on a text cast.
- The command-line demo upgrade did not add new ledger accounts (only app start-up did) → both paths share the upgrade.
- The old booking API accepted any non-"pay at hotel" option as online payment → kept for compatibility.

## Defects found and fixed during 0.4 testing
- Drinks sold in the restaurant were deducted from the kitchen store → menu items can now name their issuing
  store (drinks issue from the bar store).
- PostgreSQL rejected a text timestamp in the "send to kitchen" update → split into two typed updates.
- Tapping the same dish twice created two lines → repeated taps increase the quantity of the unsent line.
- Settlement defaulted to bank transfer → defaults to cash.
- Terminal opened on in-room dining → opens on the main restaurant.
- Per-store stock rows were flagged red against the hotel-wide reorder level → flag removed (alerts use the total).
- Changing `?tab=` in the address did not switch tabs on an already-open page → tabs follow the address.
- "Point of sale" menu item highlighted on "Menu & outlets" → exact menu highlighting.
- Quotation total row misaligned → fixed.

## Not yet covered
External penetration test, load/performance test, accessibility audit with assistive technology, and modules
listed as pending in ROADMAP.md.
