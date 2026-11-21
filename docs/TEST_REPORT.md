# Test report — release 0.3

## Environment
Python 3.13, SQLite 3.53 (test database rebuilt for every test), Chromium via Playwright for browser tests.
PostgreSQL 16: production schema, constraints and append-only triggers verified by loading the rendered
migrations into a PostgreSQL 16 server; the CI workflow runs the full API suite against PostgreSQL on each push.

## Automated API / integration tests — 34 passed, 0 failed
`cd backend && python -m pytest -q`

| Area | Tests | What is proven |
|---|---|---|
| Authentication & RBAC | 11 | login, wrong password logged, lockout after 5 failures, unauthenticated rejection, permission enforcement, hotel scoping, logout & admin session revocation, full MFA enrolment and MFA-gated sign-in, suspension blocks login and is audited, privilege-escalation blocked, scrypt hashing |
| Reservations | 8 | creation & reference format, per-night quote with 10 % service charge + 7.5 % VAT, honest `not_configured` email status, same room cannot be double-booked (back-to-back allowed), category cannot be oversold without permission + reason, rate override needs permission, max occupancy, modify / cancel / no-show rules, availability decrements, duplicate-guest detection, identity masking |
| Front office & finance | 10 | full stay: walk-in → check-in → F&B charge (exact net/svc/tax) → blocked check-out with balance → payment → check-out → room dirty → housekeeping start/complete → staff cannot inspect → manager inspection → room available → trial balance & balance sheet balanced; check-in refuses uninspected room; payment idempotency & duplicate reference; online payment not faked (501); refund maker-checker; requester cannot self-approve; charge reversal; journal lines and audit logs cannot be modified (DB triggers); night audit posts one charge per in-house guest and refuses to run ahead of the calendar; room move & block rules; manual journal must balance |
| Booking engine & reports | 5 | public availability → booking (terms required, card payment refused without gateway, sold-out conflict), lookup by reference + email, guest cancellation; reports JSON/XLSX/CSV/PDF, invoice PDF, financial reports restricted; dashboard KPIs; inclusive and exclusive tax maths; OpenAPI + health + security headers |

## Browser end-to-end test — passed
`python frontend/e2e/smoke.py` (app running with demo data). Fails on any JavaScript error or error banner.

1. Administrator visits all 18 screens (dashboard, room board, front desk tabs, calendar, guests, housekeeping,
   accounting tabs incl. balanced balance sheet, reports with export, approvals, users, roles, hotel settings,
   rooms & rates, audit trail, profile).
2. Receptionist creates a walk-in in the UI, checks in, posts a restaurant charge, takes a POS payment (amount
   pre-filled with the due-at-check-out figure), sees "Settled — ready to check out", completes check-out.
3. Housekeeping manager passes an inspection.
4. Anonymous guest books through the public portal and receives a reference.
5. Housekeeper uses the mobile layout (390 px).

Defects found and fixed during testing: room picker listed uninspected rooms first (now ready rooms first,
others marked "not ready"); folio showed "guest in credit" during a stay before room nights were posted (added
a "Due at check-out" figure and hid the refund action in that case); dashboard occupancy wording clarified
("tonight", excluding departures).

## Not yet covered
External penetration test, load/performance test, accessibility audit with assistive technology, frontend
type-check against `@types/react` (runs in CI as advisory), and modules listed as planned in ROADMAP.md.
