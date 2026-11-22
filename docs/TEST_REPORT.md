# Test report — release 0.4

## Environment
Python 3.13, SQLite 3 (test database rebuilt for every test) and PostgreSQL 16 (full suite run locally against
a PostgreSQL 16 server; CI runs it on every push), Chromium via Playwright for browser tests.

## Automated API / integration tests — 45 passed, 0 failed (SQLite and PostgreSQL)
`cd backend && python -m pytest -q` · `TEST_DATABASE_URL=postgresql://… python -m pytest -q`

| Area | Tests | What is proven |
|---|---|---|
| Authentication & RBAC | 11 | login, wrong password logged, lockout after 5 failures, unauthenticated rejection, permission enforcement, hotel scoping, logout & admin session revocation, full MFA enrolment and MFA-gated sign-in, suspension blocks login and is audited, privilege-escalation blocked, scrypt hashing |
| Reservations | 8 | creation & reference format, per-night quote with 10 % service charge + 7.5 % VAT, honest `not_configured` email status, same room cannot be double-booked (back-to-back allowed), category cannot be oversold without permission + reason, rate override needs permission, max occupancy, modify / cancel / no-show rules, availability decrements, duplicate-guest detection, identity masking |
| Front office & finance | 10 | full stay: walk-in → check-in → F&B charge (exact net/svc/tax) → blocked check-out with balance → payment → check-out → room dirty → housekeeping → inspection → room available → trial balance & balance sheet balanced; uninspected room refused; payment idempotency & duplicate reference; online payment not faked (501); refund maker-checker; charge reversal; journal lines and audit logs cannot be modified (DB triggers); night audit; room move & block rules; manual journal must balance |
| Booking engine & reports | 5 | public booking, lookup, cancellation; reports JSON/XLSX/CSV/PDF, invoice PDF, financial reports restricted; dashboard KPIs; inclusive and exclusive tax maths; OpenAPI + health + security headers |
| **POS & kitchen (0.4)** | 5 | waiter cannot settle or discount; kitchen display ticket per table; chef prepares/readies but cannot mark served; settlement needs an open shift; exact totals (₦19,000 → SC ₦1,900 → VAT ₦1,567.50 → ₦22,467.50); cash over-tender gives change, card/room cannot be over-tendered, card needs a reference; recipe ingredients deducted from the right stores (food from kitchen, drinks from bar); cost of sales posted; receipt PDF; shift expected cash and variance note; **charge to room appears on the guest folio** with net + service + tax = total; split bill, merge, item void needs reason, discount needs reason, split tender, order void; **sale blocked atomically when ingredients run out** (no payment, no stock change); menu & recipe management permissions; sold-out items cannot be ordered |
| **Inventory (0.4)** | 2 | requisition maker-checker; issue to housekeeping posts to supplies expense; transfers keep value; insufficient stock refused; wastage write-off; storekeeper cannot adjust; stock count posts the variance; stock movements are append-only (DB trigger); expiry and low-stock alerts; opening balances against equity |
| **Procurement (0.4)** | 2 | requisition approval (not own); quotation comparison picks the cheapest per line; PO above ₦500,000 needs `procurement.approve_high`; creator cannot approve; GRN refuses over-receipt and missing expiry dates; partial and final receipts update PO status and stock; invoice variance needs an approval note; invoice approval clears GRNI to zero and books the price variance; supplier invoice numbers unique per supplier; payments with 5 % WHT, idempotent, cannot exceed the balance; AP reaches zero; service lines expensed at GRN; invoices without a PO need an expense account; supplier performance and masked bank details |
| **Cross-cutting (0.4)** | 2 | permission upgrade grants new permissions to existing system roles exactly once and respects later removals; dashboard shows outlet revenue and supply-chain counts; new reports listed only to permitted roles; report exports audited |

Every 0.4 test ends with a ledger integrity check: total debits equal total credits, **and** the stock
sub-ledger value equals the Inventory GL account balance.

## Browser end-to-end tests — passed
`python frontend/e2e/smoke.py` (app running with demo data). Fails on any JavaScript error or error banner.

1. Administrator visits all screens, now including Point of sale, Kitchen display, Menu & outlets, Inventory
   (all tabs) and Procurement (all tabs).
2. Receptionist walk-in → check-in → folio charge → payment → check-out. Housekeeping inspection. Public booking.
3. **Cashier opens a shift, sells a takeaway meal and settles it in cash (0.4).**
4. Mobile layout (390 px).

Additional scripted browser walkthroughs for 0.4 (run during development): waiter → kitchen → cashier dine-in
sale with change; room-service order charged to a room; full procurement cycle across five roles
(requisition → approval → two quotations → PO → approval → GRN → invoice → approval → payment with WHT);
stock requisition approve/issue; trial balance balanced at the end; no console errors.

## Upgrade test — passed
A database created by release 0.3 (with its demo data) was started with 0.4: migration 0003 applied, new
ledger accounts added, system roles received the new permissions once, the 0.4 demo outlets/menu/stores/
suppliers were added once (re-running is a no-op), existing reservations kept, books balanced.

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
