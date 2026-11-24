# EHMS REST API reference

Generated from the route table (`python -m ehms.apidoc`). The live, machine-readable OpenAPI 3 spec is served at `/api/openapi.json`, with a browsable list at `/api/docs`.

**Conventions**

- Authenticate with `POST /api/auth/login`, then send `Authorization: Bearer <token>` on every request.
- Request and response bodies are JSON. Money values are **integers in minor units** (kobo for NGN): ₦45,000.00 is `4500000`.
- Stock quantities are decimals in the item's unit with up to 3 decimal places (`0.25` kg); they are stored exactly as thousandths.
- Dates are `YYYY-MM-DD`; timestamps are ISO-8601 UTC.
- Errors return `{"error": {"code", "message", "details"}}` with HTTP 400 (validation), 401 (sign-in), 403 (permission/scope), 404, 409 (conflict, e.g. double booking, unsettled balance, insufficient stock), 423 (account locked), 429 (rate limit), 501 (integration not configured).
- Payments require an `idempotency_key`; repeating a request with the same key never creates a second payment.

Total endpoints: **469**

## Accounting

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/accounts` | Chart of accounts | `accounting.view` |
| POST | `/api/accounts` | Add a ledger account | `accounting.manage_accounts` |
| GET | `/api/hotels/{hotel_id}/journal` | Journal entries with lines | `accounting.view` |
| POST | `/api/hotels/{hotel_id}/journal` | Post a manual balanced journal entry (e.g. expenses, opening balances) | `accounting.post_manual` |
| POST | `/api/journal/{entry_id}/reverse` | Reverse a posted journal entry | `accounting.post_manual` |
| GET | `/api/reports/trial-balance` | Trial balance as at a date (hotel or consolidated) | `accounting.view` |
| GET | `/api/reports/profit-and-loss` | Profit and loss for a period | `reports.financial` |
| GET | `/api/reports/balance-sheet` | Balance sheet as at a date | `reports.financial` |

## Admin

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/admin/users` | List users | `admin.users.view` |
| POST | `/api/admin/users` | Create a user account | `admin.users.manage` |
| PATCH | `/api/admin/users/{user_id}` | Update a user, roles and hotel access | `admin.users.manage` |
| POST | `/api/admin/users/{user_id}/status` | Activate, suspend or deactivate a user | `admin.users.manage` |
| POST | `/api/admin/users/{user_id}/reset-password` | Issue a temporary password and end the user's sessions | `admin.users.manage` |
| GET | `/api/admin/users/{user_id}/sessions` | List a user's active sessions | `admin.sessions.manage` |
| POST | `/api/admin/sessions/{session_id}/revoke` | Revoke an active session | `admin.sessions.manage` |
| GET | `/api/admin/permissions` | Permission catalogue | `admin.users.view` |
| GET | `/api/admin/roles` | List roles with permissions | `admin.users.view` |
| POST | `/api/admin/roles` | Create a custom role | `admin.roles.manage` |
| PUT | `/api/admin/roles/{role_id}` | Update a role's name and permissions | `admin.roles.manage` |
| GET | `/api/admin/audit-logs` | Search the audit trail | `admin.audit.view` |
| GET | `/api/admin/login-attempts` | Login history including failed attempts | `admin.audit.view` |
| GET | `/api/hotels/{hotel_id}/notifications` | Outgoing notification log with delivery status | `admin.settings.manage` |
| GET | `/api/admin/backups` | Backup history, schedule and storage location | `admin.backups` |
| POST | `/api/admin/backups` | Back up the database and stored documents now | `admin.backups` |
| POST | `/api/admin/backups/{backup_id}/verify` | Verify a backup: checksums, row counts and a test restore into a temporary database | `admin.backups` |
| GET | `/api/admin/backups/{backup_id}/download` | Download a backup archive (logged) | `admin.backups` |
| PUT | `/api/admin/backups/schedule` | Automatic backups: enabled, hour_utc (0–23), retention_days (1–365, scheduled backups older than this are deleted) | `admin.backups` |
| POST | `/api/hotels/{hotel_id}/logo` | Upload the hotel logo: filename, content_base64 (PNG/JPEG/WebP, up to 1 MB) | `admin.settings.manage` |

## Ai

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/insights/forecast` | Explainable occupancy and room-revenue forecast (?days=30, max 90) | `bi.view` |
| GET | `/api/hotels/{hotel_id}/insights/anomalies` | Unusual-transaction flags (?status=open/reviewing/confirmed/dismissed) | `ai.anomalies.view` |
| POST | `/api/hotels/{hotel_id}/insights/anomalies/scan` | Run the unusual-transaction scan now (?days=7, max 90) | `ai.review` |
| POST | `/api/anomalies/{flag_id}/review` | Record the outcome of a review ({status: reviewing/confirmed/dismissed, note}); you cannot review a flag about yourself | `ai.review` |
| GET | `/api/hotels/{hotel_id}/insights/recommendations` | Rate recommendations (needs sales.view) and reorder recommendations (needs inventory.view), each with its reasoning | `ai.assistant` |
| POST | `/api/hotels/{hotel_id}/insights/recommendations/propose-rule` | Turn a suggested rule into a pricing rule awaiting approval ({name, min_occupancy_pct, max_occupancy_pct, adjustment_bp}) | `sales.pricing` |
| POST | `/api/hotels/{hotel_id}/insights/recommendations/requisition` | Create a draft purchase requisition from reorder recommendations ({item_ids}); it then follows normal approval | `procurement.requisition` |
| GET | `/api/assistant/status` | Which engine answers and what the user may ask about | `ai.assistant` |
| POST | `/api/assistant/ask` | Ask a question ({question, hotel_id}); answers use only data you are permitted to see | `ai.assistant` |
| GET | `/api/hotels/{hotel_id}/assistant/log` | Assistant questions asked (audit) | `admin.audit.view` |
| GET | `/api/hotels/{hotel_id}/insights/cancellation-risk` | Upcoming bookings scored for cancellation risk with the reasons (?days=30). A prediction only — nothing is changed | `reservations.view` |
| GET | `/api/hotels/{hotel_id}/insights/maintenance-risk` | Assets likely to fail next, from their repair history (mean time between failures) | `maintenance.view` |
| GET | `/api/hotels/{hotel_id}/insights/guests` | Guest demographics and preferences: nationality mix, preferred room categories, booking sources, stay length, repeat guests (?from, ?to) | `crm.view` |
| GET | `/api/hotels/{hotel_id}/insights/daily-summary` | Plain-language management summary of yesterday's business date and today's outlook, from recorded data | `dashboard.view` |

## Auth

| Method | Path | Purpose | Access |
|---|---|---|---|
| POST | `/api/auth/login` | Sign in with email and password | public |
| POST | `/api/auth/mfa/verify` | Complete sign-in with a 6-digit authenticator code | signed in |
| POST | `/api/auth/logout` | Sign out (revoke current session) | signed in |
| GET | `/api/auth/me` | Current user profile, roles, permissions and hotels | signed in |
| POST | `/api/auth/mfa/setup` | Start MFA enrolment (returns secret and otpauth URI) | signed in |
| POST | `/api/auth/mfa/enable` | Confirm MFA enrolment with a code from the authenticator app | signed in |
| POST | `/api/auth/mfa/disable` | Disable MFA (requires password and current code) | signed in |
| POST | `/api/auth/password` | Change own password | signed in |
| POST | `/api/auth/password-reset/request` | Request a password-reset link by email | public |
| POST | `/api/auth/password-reset/confirm` | Set a new password using a reset code | public |
| GET | `/api/auth/sessions` | List my active sessions | signed in |
| GET | `/api/me/preferences` | Your interface language and the languages available | signed in |
| PUT | `/api/me/preferences` | Set your interface language: language (en / fr) | signed in |

## Bi

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/bi/analytics` | Analytics (?hotel_ids=1,2&from&to&granularity=day/week/month/quarter/year&compare=previous_period/previous_year/none&department) | `bi.view` |
| GET | `/api/hotels/{hotel_id}/bi/occupancy-history` | Occupancy history by room category per day and nights/revenue per room (?from&to) | `bi.view` |
| GET | `/api/hotels/{hotel_id}/bi/hr` | HR analytics: headcount, joiners/leavers, turnover, attendance, lateness, overtime, leave and payroll cost (?from&to) | `bi.view` |
| GET | `/api/hotels/{hotel_id}/report-schedules` | Scheduled reports and eligible recipients | `bi.schedule` |
| POST | `/api/hotels/{hotel_id}/report-schedules` | Schedule a report (name, report_code, frequency daily/weekly/monthly, weekday 0-6, month_day 1-31, format, recipients [user ids], params) | `bi.schedule` |
| PATCH | `/api/report-schedules/{schedule_id}` | Pause or resume a schedule ({active}) | `bi.schedule` |
| POST | `/api/report-schedules/{schedule_id}/run` | Run a schedule now (does not change its next due date) | `bi.schedule` |

## Booking engine (public)

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/public/hotels/{code}` | Public hotel profile and room categories | public |
| GET | `/api/public/hotels/{code}/availability` | Available room categories and total prices for dates | public |
| POST | `/api/public/hotels/{code}/bookings` | Submit an online booking (pay at hotel unless a payment gateway is configured) | public |
| GET | `/api/public/bookings/{reference}` | Look up a booking by reference and email | public |
| POST | `/api/public/bookings/{reference}/cancel` | Guest cancellation of a future booking (subject to hotel policy) | public |
| GET | `/api/public/payments/{reference}` | Return page: verify an online payment with the provider and show its outcome | public |
| POST | `/api/public/webhooks/paystack` | Paystack webhook (HMAC-SHA512 signed) | public |
| POST | `/api/public/webhooks/flutterwave` | Flutterwave webhook (verif-hash header) | public |
| GET | `/api/public/feedback/{token}` | Guest survey form details | public |
| POST | `/api/public/feedback/{token}` | Submit the post-stay survey (ratings 1–5, NPS 0–10, comments) | public |
| GET | `/api/public/media/{media_id}` | A room photo (public, for the booking engine) | public |
| GET | `/api/public/bookings/{reference}/confirmation.pdf` | Booking confirmation and pro-forma receipt (PDF) for a guest: ?email= | public |
| GET | `/api/public/hotels/{hotel_id}/logo` | The hotel logo (404 when none is set) | public |

## Crm

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/loyalty` | Loyalty members (?q, ?tier) and programme rules | `crm.view` |
| PUT | `/api/hotels/{hotel_id}/loyalty/rules` | Configure earning rate, point value, minimum redemption, tiers and tier bonuses | `crm.manage` |
| POST | `/api/guests/{guest_id}/loyalty/enrol` | Enrol a guest in the loyalty programme (with their agreement) | `guests.manage` |
| GET | `/api/guests/{guest_id}/loyalty` | A guest's loyalty account and statement | `guests.view` |
| POST | `/api/folios/{folio_id}/loyalty-redeem` | Redeem a member's points as a credit on their open folio (posted as an allowance) | `payments.receive` |
| POST | `/api/guests/{guest_id}/loyalty/adjust` | Manual points adjustment with a reason (audited) | `crm.manage` |
| GET | `/api/hotels/{hotel_id}/complaints` | Complaints (?status, ?category, ?open=1) with SLA flags | `crm.view` |
| POST | `/api/hotels/{hotel_id}/complaints` | Register a complaint (category, priority, description, guest/reservation/room); SLA due time set by priority | `crm.complaints` |
| GET | `/api/complaints/{complaint_id}` | Complaint with its update trail | `crm.view` |
| POST | `/api/complaints/{complaint_id}/update` | Respond: note, assign, status in_progress/resolved (resolution required)/closed, compensation, guest satisfied | `crm.complaints` |
| POST | `/api/hotels/{hotel_id}/feedback` | Record feedback received another way (comment card, online review: platform, ratings, comments) | `crm.complaints` |
| GET | `/api/hotels/{hotel_id}/feedback` | Feedback received (?from, ?to, ?sentiment) | `crm.view` |
| GET | `/api/hotels/{hotel_id}/crm/insights` | Satisfaction, NPS, recurring themes, complaints by category and department, response times, repeat-guest and retention figures (?from, ?to) | `crm.view` |
| GET | `/api/hotels/{hotel_id}/campaigns` | Marketing campaigns | `crm.view` |
| POST | `/api/hotels/{hotel_id}/campaigns/preview` | Count consenting guests matching a segment | `crm.campaigns` |
| POST | `/api/hotels/{hotel_id}/campaigns` | Create a draft campaign (name, channel, segment, subject, body, promo_code) | `crm.campaigns` |
| POST | `/api/campaigns/{campaign_id}/send` | Send a draft campaign to consenting guests in its segment (queues one message each; includes an opt-out line) | `crm.campaigns` |
| POST | `/api/guests/{guest_id}/unsubscribe` | Record a guest's marketing opt-out | `guests.manage` |
| GET | `/api/guests/{guest_id}/referral` | A guest's referral code and the guests they referred | `guests.view` |
| POST | `/api/guests/{guest_id}/referral` | Create (or return) the guest's personal referral code | `guests.manage` |
| POST | `/api/reservations/{res_id}/referral` | Record that a booking was referred: code | `reservations.modify` |
| GET | `/api/hotels/{hotel_id}/referrals` | Referral programme rules and referrals | `crm.view` |
| PUT | `/api/hotels/{hotel_id}/referrals/rules` | Configure the referral programme: enabled, points_referrer | `crm.manage` |

## Dashboard

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/dashboard` | Executive dashboard KPIs and trends | `dashboard.view` |

## Documents

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/documents/meta` | Document entity types, categories, default retention and allowed file types | `documents.view` |
| POST | `/api/documents` | Upload a document (JSON: entity_type, entity_id, category, title, filename, content_base64, confidentiality, notes) | `documents.upload` |
| GET | `/api/documents` | Documents for a record (?entity_type&entity_id) or search (?hotel_id&q&category); only those you may open are listed | `documents.view` |
| GET | `/api/documents/{doc_id}` | Document details, version history and access history | `documents.view` |
| GET | `/api/documents/{doc_id}/download` | Download the file (integrity-checked, logged) | `documents.view` |
| POST | `/api/documents/{doc_id}/replace` | Upload a new version (filename, content_base64, notes); the old version is kept as superseded | `documents.upload` |
| PATCH | `/api/documents/{doc_id}` | Change title, category, notes or confidentiality (raising confidentiality is always allowed; lowering needs documents.manage) | `documents.upload` |
| POST | `/api/documents/{doc_id}/legal-hold` | Place or lift a legal hold ({hold: true/false, reason}); held documents cannot be deleted | `documents.manage` |
| POST | `/api/documents/{doc_id}/retention` | Extend the retention date ({retention_until, reason}); retention can only be extended | `documents.manage` |
| DELETE | `/api/documents/{doc_id}` | Delete a document after its retention period ({reason}); the record and access history are kept, the file is erased | `documents.manage` |
| GET | `/api/hotels/{hotel_id}/documents/retention-due` | Documents past their retention date and not on hold (candidates for disposal) | `documents.manage` |
| GET | `/api/hotels/{hotel_id}/documents/access-log` | Recent document activity across the hotel (?action) | `documents.manage` |

## Events

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/venues` | Venues | `events.view` |
| POST | `/api/hotels/{hotel_id}/venues` | Add or edit a venue (by code) | `events.manage` |
| GET | `/api/hotels/{hotel_id}/venues/calendar` | Venue bookings between ?from and ?to (dates) | `events.view` |
| GET | `/api/hotels/{hotel_id}/events` | Events (?status, ?from, ?to) | `events.view` |
| POST | `/api/hotels/{hotel_id}/events` | Create an enquiry/booking: title, event_type, client, start_at, end_at, expected_guests, venues[{venue_id, start_at, end_at}], status | `events.manage` |
| GET | `/api/events/{event_id}` | Event with venues, quotation items, totals, costs, staff and folio | `events.view` |
| PATCH | `/api/events/{event_id}` | Edit event details (not after invoicing) | `events.manage` |
| POST | `/api/events/{event_id}/venues` | Book another venue slot for the event | `events.manage` |
| DELETE | `/api/event-venues/{slot_id}` | Remove a venue slot | `events.manage` |
| POST | `/api/events/{event_id}/items` | Add a quotation line (kind venue/catering/beverage/equipment/decoration/accommodation/service/other, description, quantity, unit_price) | `events.manage` |
| DELETE | `/api/event-items/{item_id}` | Remove a quotation line (before invoicing) | `events.manage` |
| POST | `/api/events/{event_id}/status` | Move an event: tentative / confirmed (checks venue clashes and capacity; opens the event folio) / cancelled (reason) / completed | `events.manage` |
| POST | `/api/events/{event_id}/invoice` | Post every quotation line to the event folio (with taxes and service charge); deposits already taken are credited | `events.invoice` |
| POST | `/api/events/{event_id}/costs` | Record a direct event cost (for profitability) | `events.manage` |
| POST | `/api/events/{event_id}/staff` | Allocate an employee to the event (employee_id, role) | `events.manage` |
| GET | `/api/events/{event_id}/quotation.pdf` | Quotation / proforma invoice PDF | `events.view` |
| GET | `/api/hotels/{hotel_id}/events/summary` | Events revenue and profitability for a period (?from, ?to) | `events.view` |

## Finance

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/taxes` | Tax and levy rules | signed in |
| POST | `/api/hotels/{hotel_id}/taxes` | Add a tax rule (rate in basis points, e.g. 750 = 7.5%) | `admin.settings.manage` |
| PATCH | `/api/taxes/{tax_id}` | End-date or deactivate a tax rule | `admin.settings.manage` |
| GET | `/api/hotels/{hotel_id}/payment-methods` | Payment methods | signed in |
| POST | `/api/hotels/{hotel_id}/payment-methods` | Add a payment method | `admin.settings.manage` |
| GET | `/api/hotels/{hotel_id}/expenses` | Expense claims (?status); requesters see their own unless they approve or pay | `finance.expenses.request` |
| POST | `/api/hotels/{hotel_id}/expenses` | Submit an expense claim (department, expense account, amount, description, receipt reference) | `finance.expenses.request` |
| POST | `/api/expenses/{claim_id}/decide` | Approve or reject an expense claim (not your own) | `finance.expenses.approve` |
| POST | `/api/expenses/{claim_id}/pay` | Pay an approved claim from cash or bank (posts Dr expense / Cr cash or bank) | `finance.expenses.pay` |
| GET | `/api/hotels/{hotel_id}/bank-reconciliation` | Reconciliation workspace for an account (?account_id, ?as_at): statement lines, unreconciled book lines, balances | `accounting.reconcile` |
| POST | `/api/hotels/{hotel_id}/bank-reconciliation/import` | Import bank statement lines: account_id, lines[{date, description, reference, amount}] (+ money in, − money out) | `accounting.reconcile` |
| POST | `/api/hotels/{hotel_id}/bank-reconciliation/auto-match` | Match statement lines to book lines with the same amount within ±5 days (one-to-one) | `accounting.reconcile` |
| POST | `/api/bank-statement-lines/{line_id}/match` | Manually match (journal_line_id), unmatch (null) or ignore (ignore=true) a statement line | `accounting.reconcile` |
| GET | `/api/hotels/{hotel_id}/budgets` | Budget vs actual for revenue and expense accounts (?year, ?month for one month else year to date) | `accounting.view` |
| PUT | `/api/hotels/{hotel_id}/budgets` | Set a year's budget: year, lines[{account_id, months: [12 amounts in kobo]}] | `accounting.budgets` |
| GET | `/api/hotels/{hotel_id}/cash-flow` | Cash-flow statement, direct method, for cash, bank and clearing accounts (?from, ?to) | `reports.financial` |
| GET | `/api/hotels/{hotel_id}/accounting/periods` | Accounting periods and their status | `accounting.view` |
| POST | `/api/hotels/{hotel_id}/accounting/periods/{period}/close` | Close a past accounting period (no further postings dated in it) | `accounting.close_period` |
| POST | `/api/hotels/{hotel_id}/accounting/periods/{period}/reopen` | Reopen a closed period (reason required; audited) | `accounting.close_period` |
| GET | `/api/exchange-rates` | Latest exchange rates per currency and recent history | `payments.receive` |
| POST | `/api/exchange-rates` | Record an exchange rate (currency, rate = base units per 1 foreign unit as a decimal string, rate_date, source) | `finance.exchange_rates` |
| POST | `/api/folios/{folio_id}/notes` | Raise a credit or debit note on a folio (kind credit/debit, department, description, net_amount, reason) — needs approval | `finance.notes.request` |
| GET | `/api/hotels/{hotel_id}/notes` | Credit and debit notes (?status) | `folio.view` |
| POST | `/api/notes/{note_id}/decide` | Approve or reject a credit/debit note ({decision, note}); approval posts it to the folio and the ledger | `finance.notes.approve` |
| GET | `/api/notes/{note_id}/pdf` | Credit or debit note as PDF | `folio.view` |
| GET | `/api/hotels/{hotel_id}/petty-cash` | Petty cash funds with balances, and recent vouchers and top-ups (?fund_id) | `finance.petty_cash` |
| POST | `/api/hotels/{hotel_id}/petty-cash/funds` | Open a petty cash fund: name, custodian_id, imprest, voucher_limit, source_method_id (the float is paid in from cash or bank) | `finance.petty_cash.manage` |
| POST | `/api/petty-cash/funds/{fund_id}/top-up` | Replenish a fund: source_method_id, amount (default: back up to the float) | `finance.petty_cash.manage` |
| POST | `/api/petty-cash/funds/{fund_id}/vouchers` | Pay out from petty cash: payee, description, expense_account_id, department, amount (over the fund's limit → needs approval) | `finance.petty_cash` |
| POST | `/api/petty-cash/vouchers/{entry_id}/decide` | Approve (posts) or reject a petty cash voucher above the limit: decision approve / reject, note | `finance.petty_cash.approve` |
| GET | `/api/vouchers/{kind}/{voucher_id}` | Payment voucher PDF for a petty cash entry, a paid expense claim or a supplier payment | signed in |

## Folio

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/folios/{folio_id}` | Guest folio with all lines and balance | `folio.view` |
| GET | `/api/reservations/{res_id}/folio` | Open (or create) the folio for a reservation | `folio.view` |
| POST | `/api/folios/{folio_id}/charges` | Post a charge (restaurant, minibar, laundry, transport …) to a folio | `folio.post_charge` |
| POST | `/api/folios/{folio_id}/adjustments` | Reverse a charge line, or grant an allowance (credit) with a reason | `folio.adjust` |
| POST | `/api/reservations/{res_id}/folios` | Open an additional folio for a stay (window_name, bill_to: guest/company, corporate_account_id) | `folio.transfer` |
| POST | `/api/folios/{folio_id}/transfer` | Move charges to another open folio of the same hotel (line_ids, target_folio_id, reason); optional amount to move part of one line | `folio.transfer` |

## Front desk

| Method | Path | Purpose | Access |
|---|---|---|---|
| POST | `/api/reservations/{res_id}/check-in` | Check a guest in | `frontdesk.checkin` |
| GET | `/api/reservations/{res_id}/checkout-preview` | Preview charges still to be posted and the balance due at check-out | `frontdesk.checkout` |
| POST | `/api/reservations/{res_id}/check-out` | Check a guest out (posts remaining room nights; balance must be settled) | `frontdesk.checkout` |
| POST | `/api/reservations/{res_id}/room-move` | Move an in-house guest to another room | `frontdesk.room_move` |
| POST | `/api/hotels/{hotel_id}/night-audit` | Night audit: post tonight's room charges for in-house guests and roll the business date | `frontdesk.night_audit` |
| GET | `/api/hotels/{hotel_id}/wake-up-calls` | Wake-up calls for a date (?date, default today) with guest and room | `frontdesk.checkin` |
| POST | `/api/reservations/{res_id}/wake-up-calls` | Book a wake-up call for an in-house (or arriving) guest: call_date, call_time (HH:MM), note | `frontdesk.checkin` |
| POST | `/api/wake-up-calls/{call_id}/status` | Record the outcome of a wake-up call: status done / missed / cancelled | `frontdesk.checkin` |
| GET | `/api/hotels/{hotel_id}/stay-fees` | Early check-in and late check-out fees | `reservations.view` |
| PUT | `/api/hotels/{hotel_id}/stay-fees` | Set the early check-in and late check-out fees (amounts in the hotel currency; 0 = free) | `admin.settings.manage` |
| POST | `/api/reservations/{res_id}/early-late` | Grant early check-in or late check-out: kind early_check_in / late_check_out, until (HH:MM, late check-out), waive_reason (needs reservations.waive_fee to waive the fee) | `reservations.modify` |
| GET | `/api/reservations/{res_id}/registration-card.pdf` | Guest registration card (PDF) to print and sign at check-in | `frontdesk.checkin` |

## Groups

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/groups` | Group blocks with pickup (?status) | `reservations.view` |
| POST | `/api/hotels/{hotel_id}/groups` | Create a group block (name, arrival, departure, cutoff_date, rooms[{room_type_id, rooms, rate}], corporate_account_id, contact guest, billing) | `reservations.groups` |
| GET | `/api/groups/{block_id}` | Group block with allotment, pickup, rooming list and master folio | `reservations.view` |
| PATCH | `/api/groups/{block_id}` | Change status, cut-off date, billing, notes or allotment (rooms[{room_type_id, rooms}] — never below rooms picked up) | `reservations.groups` |
| POST | `/api/groups/{block_id}/release` | Release rooms not yet picked up back to general sale | `reservations.groups` |
| POST | `/api/groups/{block_id}/rooming-list` | Create reservations from a rooming list: rows[{first_name, last_name, email, phone, room_type (code) or room_type_id, arrival, departure, adults, children, special_requests}] or csv text | `reservations.groups` |
| GET | `/api/groups/{block_id}/rooming-list.csv` | Rooming list as CSV | `reservations.view` |
| POST | `/api/groups/{block_id}/master-folio` | Open the group master folio (room nights are billed to it when billing is master_room or master_all) | `reservations.groups` |

## Guests

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/guests` | Search guests by name, email, phone or company | `guests.view` |
| POST | `/api/guests` | Create a guest profile (warns about likely duplicates) | `guests.manage` |
| GET | `/api/guests/{guest_id}` | Guest profile with stay and spending history | `guests.view` |
| PATCH | `/api/guests/{guest_id}` | Update a guest profile | `guests.manage` |

## Housekeeping

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/housekeeping/tasks` | Housekeeping tasks (filter by status, assignee, 'mine') | `housekeeping.view` |
| POST | `/api/hotels/{hotel_id}/housekeeping/tasks` | Create a housekeeping task | `housekeeping.assign` |
| POST | `/api/housekeeping/tasks/{task_id}/assign` | Assign a task to a staff member | `housekeeping.assign` |
| POST | `/api/housekeeping/tasks/{task_id}/start` | Start cleaning | `housekeeping.update` |
| POST | `/api/housekeeping/tasks/{task_id}/complete` | Mark cleaning complete (room awaits inspection); optionally report issues / damaged items | `housekeeping.update` |
| POST | `/api/housekeeping/tasks/{task_id}/inspect` | Inspect a cleaned room: pass makes it available, fail sends it back | `housekeeping.inspect` |

## Hr

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/employees` | Employees (?status, ?department, ?q) | `hr.view` |
| POST | `/api/hotels/{hotel_id}/employees` | Register an employee (employee number generated) | `hr.manage` |
| GET | `/api/employees/{employee_id}` | Employee profile with leave balances, records (if permitted) and payslips | `hr.view` |
| PATCH | `/api/employees/{employee_id}` | Edit an employee; status changes (resigned, terminated…) record an exit | `hr.manage` |
| POST | `/api/employees/{employee_id}/records` | Add a training, appraisal, disciplinary, commendation, transfer or promotion record | `hr.records` |
| GET | `/api/hotels/{hotel_id}/roster` | Weekly roster (?start=YYYY-MM-DD, Monday) and shift templates | `hr.view` |
| POST | `/api/hotels/{hotel_id}/shift-templates` | Create a shift template (name, start_time, end_time HH:MM) | `hr.attendance` |
| PUT | `/api/hotels/{hotel_id}/roster` | Save roster cells: assignments[{employee_id, date, shift_id/null}] | `hr.attendance` |
| GET | `/api/hotels/{hotel_id}/attendance` | Attendance sheet for a date (?date) with rostered shift | `hr.view` |
| PUT | `/api/hotels/{hotel_id}/attendance` | Record attendance: date, rows[{employee_id, status, clock_in, clock_out, overtime_minutes, note}] | `hr.attendance` |
| GET | `/api/hotels/{hotel_id}/leave` | Leave requests (?status) and leave types | `hr.view` |
| POST | `/api/employees/{employee_id}/leave` | Record a leave request on behalf of an employee | `hr.manage` |
| POST | `/api/leave/{leave_id}/decide` | Approve or reject a leave request (not your own); approval marks attendance as leave | `hr.leave.approve` |
| POST | `/api/hotels/{hotel_id}/leave-types` | Add or update a leave type (code, name, days_per_year, paid) | `hr.manage` |
| GET | `/api/me/employee` | My employee profile, leave balances, requests, attendance this month and payslips | signed in |
| POST | `/api/me/leave` | Request leave for myself | signed in |
| POST | `/api/me/clock` | Clock in or out (action=in/out); late if more than 15 minutes after the rostered start | signed in |
| GET | `/api/hotels/{hotel_id}/recruitment` | Job openings with applicant counts per stage | `hr.view` |
| POST | `/api/hotels/{hotel_id}/recruitment` | Open a position (title, department, employment_type, positions, salary_min, salary_max, description, closing_date) | `hr.recruit` |
| PATCH | `/api/recruitment/{opening_id}` | Change an opening's status (open, on_hold, filled, closed), positions or closing date | `hr.recruit` |
| GET | `/api/recruitment/{opening_id}` | Opening with applicants | `hr.view` |
| POST | `/api/recruitment/{opening_id}/applicants` | Add an applicant (first_name, last_name, email, phone, source, expected_salary, consent_to_retain) | `hr.recruit` |
| GET | `/api/applicants/{applicant_id}` | Applicant with stage history, interviews and notes | `hr.view` |
| POST | `/api/applicants/{applicant_id}/stage` | Move to the next stage ({stage, note, offered_salary, start_date}); rejection needs a note | `hr.recruit` |
| POST | `/api/applicants/{applicant_id}/notes` | Add a note or an interview record ({kind: note/interview, note, interview_at, score 1-5}) | `hr.recruit` |
| POST | `/api/applicants/{applicant_id}/hire` | Hire an applicant with an accepted offer: creates the employee record (position, hire_date, basic_salary and other HR fields); needs hr.manage | `hr.recruit` |
| POST | `/api/recruitment/{opening_id}/anonymise` | Anonymise unsuccessful applicants who did not consent to be kept on file (opening must be filled or closed) | `hr.recruit` |
| GET | `/api/hotels/{hotel_id}/hr/dashboard` | HR dashboard: headcount, who is on leave, pending approvals, probation/contract/certification alerts, birthdays, staff without logins | `hr.view` |
| POST | `/api/employees/{employee_id}/history` | Record a promotion, transfer, pay change, title change, demotion or confirmation (kind, effective_date, position, department, basic_salary, line_manager_id, note); the change is applied to the record | `hr.manage` |
| POST | `/api/employees/{employee_id}/trainings` | Record training, a certification or licence (kind, title, provider, completed_on, expires_on, notes) | `hr.manage` |
| GET | `/api/hotels/{hotel_id}/hr/trainings` | Training and certification register (?expiring=days) | `hr.view` |
| POST | `/api/employees/{employee_id}/appraisals` | Start an appraisal (period, criteria[{name, rating 1-5, comment}], strengths, improvements, goals) as a draft | `hr.performance` |
| PATCH | `/api/appraisals/{appraisal_id}` | Edit a draft appraisal | `hr.performance` |
| POST | `/api/appraisals/{appraisal_id}/share` | Share a draft appraisal with the employee for acknowledgement | `hr.performance` |
| GET | `/api/hotels/{hotel_id}/hr/appraisals` | Appraisals (?status, ?period) | `hr.performance` |
| POST | `/api/me/appraisals/{appraisal_id}/acknowledge` | Acknowledge my appraisal with an optional comment | signed in |
| POST | `/api/me/requests` | Make an HR request: kind salary_advance/loan/letter/data_change/shift_swap/grievance/other, subject, details, amount, months, data | signed in |
| GET | `/api/me/requests` | My HR requests | signed in |
| POST | `/api/me/requests/{request_id}/cancel` | Withdraw one of my requests that has not been decided | signed in |
| GET | `/api/hotels/{hotel_id}/hr/requests` | Staff requests (?status, ?kind); grievances need hr.records | `hr.view` |
| POST | `/api/hr/requests/{request_id}/decide` | Approve or reject a staff request ({decision, note}); approval applies detail changes and shift swaps, issues letters, and sends advances/loans to payroll | `hr.requests.approve` |
| POST | `/api/hr/requests/{request_id}/complete` | Mark an approved advance or loan as paid out | `payroll.pay` |
| GET | `/api/hr/requests/{request_id}/letter.pdf` | Employment confirmation letter for an approved letter request (the employee, or HR) | signed in |
| POST | `/api/me/leave/{leave_id}/cancel` | Cancel my pending leave, or approved leave that has not started | signed in |
| POST | `/api/leave/{leave_id}/cancel` | Cancel or end an approved leave early ({reason}); future leave days are returned | `hr.leave.approve` |
| GET | `/api/hotels/{hotel_id}/hr/leave-calendar` | Who is on (or has asked for) leave between two dates (?from&to, ?department) | `hr.view` |
| GET | `/api/hotels/{hotel_id}/hr/leave-balances` | Leave balances of every active employee (?year) | `hr.view` |
| POST | `/api/employees/{employee_id}/leave-adjustments` | Add or remove leave days for a year (leave_type_id, days ±, year, reason), e.g. carry-over or long-service days | `hr.manage` |
| GET | `/api/hotels/{hotel_id}/holidays` | Public holidays (?year) | `hr.view` |
| POST | `/api/hotels/{hotel_id}/holidays` | Add a public holiday (holiday_date, name); it is not counted as a leave day | `hr.manage` |
| DELETE | `/api/holidays/{holiday_id}` | Remove a public holiday | `hr.manage` |
| GET | `/api/hr/assignable-roles` | Roles HR may give to staff logins (no administrator roles) | `hr.accounts` |
| POST | `/api/employees/{employee_id}/account` | Give an employee a system login (email, role_id); administrator roles are excluded; returns a temporary password | `hr.accounts` |
| GET | `/api/me/hr` | My full HR file: profile, line manager, leave, requests, appraisals, training, roster this week, holidays | signed in |
| POST | `/api/employees/{employee_id}/welfare` | Record welfare support given to an employee: kind, support_date, amount (optional), description (confidential) | `hr.records` |
| GET | `/api/hotels/{hotel_id}/hr/welfare` | Welfare register (?year) | `hr.records` |
| POST | `/api/integrations/attendance-events` | Fingerprint / biometric clocks push clock-ins and outs (header X-EHMS-Integration-Token): hotel_code, events[{employee_no, action in/out, occurred_at}] | public |

## Inventory

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/stores` | Stores / storage locations | `inventory.view` |
| POST | `/api/hotels/{hotel_id}/stores` | Create a store | `inventory.manage` |
| PATCH | `/api/stores/{store_id}` | Edit a store | `inventory.manage` |
| GET | `/api/hotels/{hotel_id}/inventory/items` | Item catalogue with on-hand quantity, value and low-stock flag (?q, category, low=1) | `inventory.view` |
| POST | `/api/hotels/{hotel_id}/inventory/items` | Register an inventory item | `inventory.manage` |
| PATCH | `/api/inventory/items/{item_id}` | Edit an inventory item | `inventory.manage` |
| GET | `/api/inventory/items/{item_id}` | Item detail: balances per store, batches and recent movements | `inventory.view` |
| GET | `/api/hotels/{hotel_id}/inventory/stock` | Stock balances by store and item (?store_id, low=1) | `inventory.view` |
| GET | `/api/hotels/{hotel_id}/inventory/movements` | Stock movement history (?item_id, store_id, type, from, to) | `inventory.view` |
| GET | `/api/hotels/{hotel_id}/inventory/alerts` | Low-stock items and batches expiring within ?days (default 30) | `inventory.view` |
| POST | `/api/hotels/{hotel_id}/inventory/adjustments` | Stock adjustment (direction in/out), wastage, damaged or expired stock write-off, or opening balance | `inventory.adjust` |
| POST | `/api/hotels/{hotel_id}/inventory/transfers` | Transfer stock between stores (lines: item_id, quantity) | `inventory.issue` |
| GET | `/api/hotels/{hotel_id}/inventory/requisitions` | Stock requisitions (?status) | `inventory.view` |
| POST | `/api/hotels/{hotel_id}/inventory/requisitions` | Request stock from a store, either for another store or for consumption by a department | `inventory.requisition` |
| POST | `/api/inventory/requisitions/{req_id}/decide` | Approve or reject a stock requisition (not your own) | `inventory.approve` |
| POST | `/api/inventory/requisitions/{req_id}/issue` | Issue an approved requisition (optional per-line quantities: lines[{line_id, quantity}]) | `inventory.issue` |
| GET | `/api/hotels/{hotel_id}/inventory/counts` | Stock counts (stocktaking) | `inventory.view` |
| POST | `/api/hotels/{hotel_id}/inventory/counts` | Start a stock count for a store (snapshots current balances; optional category) | `inventory.adjust` |
| GET | `/api/inventory/counts/{count_id}` | Stock count sheet | `inventory.view` |
| PUT | `/api/inventory/counts/{count_id}/lines` | Record counted quantities: lines[{item_id, counted}] | `inventory.adjust` |
| POST | `/api/inventory/counts/{count_id}/post` | Post a stock count: adjusts balances to counted quantities and journals the variance | `inventory.adjust` |
| GET | `/api/hotels/{hotel_id}/inventory/costing` | Stock costing method (wac or fifo) | `inventory.view` |
| PUT | `/api/hotels/{hotel_id}/inventory/costing` | Choose weighted-average (wac) or FIFO costing ({method, reason}); applies to issues from now on and needs accounting.view | `inventory.manage` |

## Kitchen

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/kitchen/tickets` | Kitchen display tickets: open orders' items that are sent, preparing or ready (?station, ?outlet_id) | `kitchen.view` |
| POST | `/api/kitchen/items/{item_id}/status` | Move a kitchen item to preparing / ready (kitchen staff) or served (service staff) | `kitchen.view` |
| GET | `/api/hotels/{hotel_id}/kitchen/performance` | Kitchen performance: items, average and slowest preparation time per station (?from, ?to) | `kitchen.view` |

## Laundry

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/laundry/prices` | Laundry price list and express surcharge | `laundry.view` |
| POST | `/api/hotels/{hotel_id}/laundry/prices` | Add or update a price (item, service, price) | `laundry.manage` |
| GET | `/api/hotels/{hotel_id}/laundry/orders` | Laundry orders (?status, ?kind, ?open=1 for everything not yet delivered) | `laundry.view` |
| POST | `/api/hotels/{hotel_id}/laundry/orders` | Register a laundry order: guest (reservation_id) or internal (department); items[{price_id / description+service, quantity, condition_note}] | `laundry.manage` |
| GET | `/api/laundry/orders/{order_id}` | Laundry order with items | `laundry.view` |
| POST | `/api/laundry/items/{item_id}/outcome` | Record an item as ok, damaged or lost (note required); damaged/lost items are not charged | `laundry.manage` |
| POST | `/api/laundry/orders/{order_id}/status` | Advance an order (washing → drying → ironing → quality_check → ready → delivered) or cancel it; delivery bills guest orders | `laundry.manage` |
| GET | `/api/hotels/{hotel_id}/laundry/summary` | Laundry summary for a date range: orders, pieces, revenue, lost & damaged, internal linen by department | `laundry.view` |
| GET | `/api/hotels/{hotel_id}/laundry/in-house` | Checked-in guests for a laundry order (?q room or name) | `laundry.manage` |

## Maintenance

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/assets` | Asset register (?category, ?status, ?q) | `maintenance.view` |
| POST | `/api/hotels/{hotel_id}/assets` | Register an asset; optionally capitalise it (funding: method_id paid now, or 'opening' for existing assets) | `maintenance.manage` |
| PATCH | `/api/assets/{asset_id}` | Edit an asset | `maintenance.manage` |
| GET | `/api/assets/{asset_id}` | Asset with schedules, maintenance history, costs and depreciation | `maintenance.view` |
| POST | `/api/assets/{asset_id}/schedules` | Add a preventive maintenance schedule (title, frequency_days, next_due, checklist, assigned_to) | `maintenance.manage` |
| POST | `/api/hotels/{hotel_id}/maintenance/raise-preventive` | Create work orders now for preventive schedules due within 3 days (the worker also does this daily) | `maintenance.manage` |
| POST | `/api/hotels/{hotel_id}/assets/depreciate` | Post straight-line depreciation for a month (period YYYY-MM) for all capitalised assets (once per asset per month) | `accounting.post_manual` |
| GET | `/api/hotels/{hotel_id}/work-orders` | Work orders (?status, ?mine=1, ?open=1); reporters see the faults they reported | `maintenance.report` |
| POST | `/api/hotels/{hotel_id}/work-orders` | Report a fault / raise a work order (asset_id or room_id, title, description, priority, blocks_room) | `maintenance.report` |
| GET | `/api/work-orders/{wo_id}` | Work order with notes and parts used | `maintenance.report` |
| POST | `/api/work-orders/{wo_id}/assign` | Assign a technician and/or external service provider | `maintenance.manage` |
| POST | `/api/work-orders/{wo_id}/status` | Move a work order: in_progress / on_hold / completed (assignee or manager), verified (manager, not the person who did the work), cancelled | `maintenance.view` |
| POST | `/api/work-orders/{wo_id}/notes` | Add a progress note | `maintenance.view` |
| POST | `/api/work-orders/{wo_id}/parts` | Issue spare parts from a store to the work order (Dr Repairs & Maintenance / Cr Inventory) | `maintenance.work` |
| GET | `/api/hotels/{hotel_id}/maintenance/summary` | Maintenance performance: open/overdue orders, completed this period, average completion time, costs, upcoming preventive work | `maintenance.view` |

## Messaging

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/notifications/mine` | My in-app notifications (latest 50) and unread count | signed in |
| POST | `/api/notifications/{notification_id}/read` | Mark one of my notifications as read | signed in |
| POST | `/api/notifications/read-all` | Mark all my notifications as read | signed in |
| GET | `/api/hotels/{hotel_id}/notification-templates` | Notification templates per event and channel (built-in defaults plus hotel overrides) | `admin.notifications.manage` |
| PUT | `/api/hotels/{hotel_id}/notification-templates` | Save a template (code, channel, subject, body, active) | `admin.notifications.manage` |
| GET | `/api/hotels/{hotel_id}/notifications` | Delivery history (?status=queued/sent/failed/not_configured, ?channel) | `admin.notifications.manage` |
| POST | `/api/notifications/{notification_id}/retry` | Re-queue a failed or not-configured message (once its provider is configured) | `admin.notifications.manage` |
| POST | `/api/hotels/{hotel_id}/notifications/run-jobs` | Run scheduled jobs now (reminders, digests) and deliver queued messages | `admin.notifications.manage` |

## Payments

| Method | Path | Purpose | Access |
|---|---|---|---|
| POST | `/api/folios/{folio_id}/payments` | Record a payment or deposit (cash, transfer, POS card, city ledger) | `payments.receive` |
| POST | `/api/folios/{folio_id}/refund-requests` | Request a refund (requires approval by a different authorised user) | `payments.refund_request` |
| GET | `/api/hotels/{hotel_id}/approvals` | Approval requests | `approvals.view` |
| POST | `/api/approvals/{approval_id}/decide` | Approve or reject a refund request (maker-checker) | `payments.refund_approve` |
| GET | `/api/payments/gateway-status` | Which online payment providers are configured | signed in |
| POST | `/api/folios/{folio_id}/payment-link` | Create an online payment link for a folio amount and (optionally) email it to the guest | `payments.receive` |
| GET | `/api/hotels/{hotel_id}/gateway-transactions` | Online payment transactions and integration log | `accounting.view` |
| POST | `/api/gateway-transactions/{tx_id}/verify` | Re-check a pending online payment with the provider | `payments.receive` |

## Payroll

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/payroll/rules` | Statutory payroll rules in force (defaults + hotel overrides) | `payroll.view` |
| PUT | `/api/hotels/{hotel_id}/payroll/rules` | Override statutory payroll rules (audited) | `payroll.approve` |
| GET | `/api/hotels/{hotel_id}/payroll/runs` | Payroll runs | `payroll.view` |
| POST | `/api/hotels/{hotel_id}/payroll/runs` | Prepare a payroll run for a month (period YYYY-MM) | `payroll.run` |
| GET | `/api/payroll/runs/{run_id}` | Payroll run with payslips, adjustments and statutory totals | `payroll.view` |
| POST | `/api/payroll/runs/{run_id}/adjustments` | Add a bonus or one-off deduction to a draft run (recalculates) | `payroll.run` |
| POST | `/api/payroll/runs/{run_id}/recalculate` | Recalculate a draft run (after attendance or salary changes) | `payroll.run` |
| POST | `/api/payroll/runs/{run_id}/approve` | Approve a draft run (not by its preparer): posts the payroll journal and applies loan repayments | `payroll.approve` |
| POST | `/api/payroll/runs/{run_id}/pay` | Record payment of net salaries from a bank account | `payroll.pay` |
| POST | `/api/payroll/runs/{run_id}/remit` | Record remittance of PAYE, pension, NHF or other statutory amounts for an approved run | `payroll.pay` |
| GET | `/api/payroll/runs/{run_id}/bank-schedule.csv` | Bank payment schedule (CSV) for a run | `payroll.pay` |
| GET | `/api/payslips/{slip_id}` | Payslip PDF (payroll staff, or the employee for their own approved payslip) | signed in |
| POST | `/api/employees/{employee_id}/loans` | Grant a staff loan or salary advance (paid out now, recovered monthly through payroll) | `payroll.pay` |

## POS (restaurant, bar, room service)

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/pos/outlets` | Outlets with tables and open-order counts | `pos.view` |
| POST | `/api/hotels/{hotel_id}/pos/outlets` | Create an outlet (restaurant, bar, room service…) | `pos.manage` |
| PATCH | `/api/pos/outlets/{outlet_id}` | Edit an outlet | `pos.manage` |
| POST | `/api/pos/outlets/{outlet_id}/tables` | Add a table to an outlet | `pos.manage` |
| PATCH | `/api/pos/tables/{table_id}` | Edit or deactivate a table | `pos.manage` |
| GET | `/api/hotels/{hotel_id}/pos/menu` | Menu categories and items (?outlet_id narrows to items sold there; ?all=1 includes inactive) | `pos.view` |
| POST | `/api/hotels/{hotel_id}/pos/menu-categories` | Create a menu category | `pos.manage` |
| POST | `/api/hotels/{hotel_id}/pos/menu-items` | Create a menu item | `pos.manage` |
| PATCH | `/api/pos/menu-items/{item_id}` | Edit a menu item (price, availability…) | `pos.manage` |
| POST | `/api/pos/menu-items/{item_id}/availability` | Mark a menu item available / sold out (service staff, e.g. when the kitchen runs out) | `pos.order` |
| PUT | `/api/pos/menu-items/{item_id}/recipe` | Replace a menu item's recipe: lines[{item_id, quantity}] in each ingredient's stock unit per portion | `pos.manage` |
| GET | `/api/hotels/{hotel_id}/pos/shifts` | Cashier shifts (?mine=1, ?outlet_id, ?status); managers see all | `pos.view` |
| POST | `/api/hotels/{hotel_id}/pos/shifts` | Open a cashier shift with an opening float | `pos.shift` |
| GET | `/api/pos/shifts/{shift_id}` | Shift summary: tenders, expected cash, discounts, voids | `pos.view` |
| POST | `/api/pos/shifts/{shift_id}/close` | Close a shift: declare counted cash; the system records expected cash and the variance | `pos.shift` |
| GET | `/api/hotels/{hotel_id}/pos/in-house` | In-house guests for room service / charge to room (?q room number or name) | `pos.view` |
| GET | `/api/hotels/{hotel_id}/pos/orders` | Orders (?outlet_id, ?status=open/settled/voided, ?date) | `pos.view` |
| POST | `/api/hotels/{hotel_id}/pos/orders` | Open an order (dine-in, takeaway or room service) | `pos.order` |
| GET | `/api/pos/orders/{order_id}` | Order with items, totals (tax & service charge) and payments | `pos.view` |
| POST | `/api/pos/orders/{order_id}/items` | Add a menu item to an order | `pos.order` |
| PATCH | `/api/pos/order-items/{item_id}` | Change quantity or notes of an item not yet sent to the kitchen | `pos.order` |
| DELETE | `/api/pos/order-items/{item_id}` | Remove an item that has not been sent to the kitchen | `pos.order` |
| POST | `/api/pos/order-items/{item_id}/void` | Void an item already sent to the kitchen (reason required) | `pos.void` |
| POST | `/api/pos/orders/{order_id}/send` | Send new items to the kitchen / bar display | `pos.order` |
| POST | `/api/pos/orders/{order_id}/discount` | Apply a discount (amount in minor units or percent) with a reason; 0 removes it | `pos.discount` |
| POST | `/api/pos/orders/{order_id}/split` | Split the bill: move the listed items (item_ids) to a new order for separate payment | `pos.order` |
| POST | `/api/pos/orders/{order_id}/merge` | Merge another open order (source_order_id) into this one, e.g. when tables are joined | `pos.order` |
| POST | `/api/pos/orders/{order_id}/move-table` | Move an order to another table | `pos.order` |
| POST | `/api/pos/orders/{order_id}/void` | Void an unsettled order (reason required) | `pos.void` |
| POST | `/api/pos/orders/{order_id}/settle` | Settle an order with one or more tenders: [{tender:'method', method_id, amount, reference} / {tender:'room', reservation_id, amount}] | `pos.settle` |
| GET | `/api/pos/orders/{order_id}/receipt.pdf` | Order receipt / bill as PDF (80 mm) | `pos.view` |
| GET | `/api/hotels/{hotel_id}/table-reservations` | Table reservations for a date (?date, ?outlet_id) | `pos.view` |
| POST | `/api/hotels/{hotel_id}/table-reservations` | Book a table: outlet_id, table_id (optional), guest_name, phone, party_size, reserved_date, reserved_time, duration_min, reservation_id (in-house guest), notes | `pos.order` |
| POST | `/api/table-reservations/{booking_id}/status` | Change a table booking: status seated / completed / cancelled / no_show; table_id when seating an unassigned booking | `pos.order` |

## Procurement

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/procurement/settings` | Procurement approval settings | `procurement.view` |
| PUT | `/api/hotels/{hotel_id}/procurement/settings` | Set the high-value PO approval threshold and invoice matching tolerance | `admin.settings.manage` |
| GET | `/api/hotels/{hotel_id}/procurement/suppliers` | Suppliers with balance owed by this hotel and delivery performance | `procurement.view` |
| POST | `/api/hotels/{hotel_id}/procurement/suppliers` | Register a supplier | `procurement.suppliers` |
| PATCH | `/api/procurement/suppliers/{supplier_id}` | Edit or deactivate a supplier | `procurement.suppliers` |
| GET | `/api/hotels/{hotel_id}/procurement/requisitions` | Purchase requisitions (?status) | `procurement.view` |
| POST | `/api/hotels/{hotel_id}/procurement/requisitions` | Raise a purchase requisition: lines[{item_id or description, quantity, est_unit_cost}] | `procurement.requisition` |
| GET | `/api/procurement/requisitions/{req_id}` | Requisition with lines, quotations and a price comparison (cheapest supplier per line) | `procurement.view` |
| POST | `/api/procurement/requisitions/{req_id}/decide` | Approve or reject a purchase requisition (not your own) | `procurement.approve` |
| POST | `/api/procurement/requisitions/{req_id}/quotes` | Record a supplier quotation against an approved requisition: lines[{requisition_line_id, unit_cost}] | `procurement.order` |
| GET | `/api/hotels/{hotel_id}/procurement/purchase-orders` | Purchase orders (?status, ?supplier_id) | `procurement.view` |
| POST | `/api/hotels/{hotel_id}/procurement/purchase-orders` | Raise a purchase order (from a quotation, a requisition, or direct lines[{item_id/description, quantity, unit_cost, expense_key}]) | `procurement.order` |
| GET | `/api/procurement/purchase-orders/{po_id}` | Purchase order with lines, goods received and invoices | `procurement.view` |
| POST | `/api/procurement/purchase-orders/{po_id}/decide` | Approve or reject a purchase order; orders above the high-value threshold need procurement.approve_high | `procurement.approve` |
| POST | `/api/procurement/purchase-orders/{po_id}/cancel` | Cancel a purchase order (nothing received), or close a partially received order short | `procurement.order` |
| POST | `/api/procurement/purchase-orders/{po_id}/receive` | Goods received note: lines[{po_line_id, quantity, rejected, batch_no, expiry_date}] — stock lines go into the PO's store | `procurement.receive` |
| GET | `/api/hotels/{hotel_id}/procurement/invoices` | Supplier invoices (?status, ?supplier_id) with outstanding amounts | `procurement.view` |
| POST | `/api/hotels/{hotel_id}/procurement/invoices` | Record a supplier invoice; it is matched against the order and goods received (three-way match) | `procurement.invoice` |
| POST | `/api/procurement/invoices/{invoice_id}/decide` | Approve a supplier invoice for payment (posts it to Accounts Payable) or reject it | `procurement.invoice_approve` |
| POST | `/api/procurement/invoices/{invoice_id}/payments` | Pay an approved supplier invoice (cash or bank transfer); withholding tax is deducted at the supplier's rate | `procurement.pay` |
| GET | `/api/hotels/{hotel_id}/procurement/summary` | Procurement dashboard: open orders, awaiting approval, payables ageing and spend by supplier (?from, ?to) | `procurement.view` |
| GET | `/api/procurement/grns/{grn_id}` | Goods received note with lines, quantities already returned and returns made | `procurement.view` |
| GET | `/api/hotels/{hotel_id}/procurement/grns` | Goods received notes (?q = GRN or PO number) | `procurement.view` |
| GET | `/api/hotels/{hotel_id}/procurement/returns` | Purchase returns | `procurement.view` |
| POST | `/api/procurement/grns/{grn_id}/returns` | Return goods to the supplier: lines[{grn_line_id, quantity}], reason, invoice_id (if the supplier already invoiced them) | `procurement.return` |

## Property

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels` | Hotels the current user can access | signed in |
| GET | `/api/hotels/{hotel_id}` | Hotel profile and configuration | signed in |
| POST | `/api/hotels` | Register a hotel or branch | `property.manage` |
| PATCH | `/api/hotels/{hotel_id}` | Update hotel profile and policies | `admin.settings.manage` |
| POST | `/api/hotels/{hotel_id}/departments` | Add a department | `admin.settings.manage` |

## Reports

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/folios/{folio_id}/invoice.pdf` | Guest invoice / receipt as PDF | `folio.view` |
| GET | `/api/hotels/{hotel_id}/reports` | List available reports | `reports.view` |
| GET | `/api/hotels/{hotel_id}/reports/{name}` | Run a report (?format=json/csv/xlsx/pdf) | `reports.view` |

## Reservations

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/availability` | Availability by room category for a date range | `reservations.view` |
| GET | `/api/hotels/{hotel_id}/calendar` | Room-by-day occupancy calendar | `reservations.view` |
| POST | `/api/hotels/{hotel_id}/quote` | Price a stay (per night, taxes, total) | `reservations.view` |
| GET | `/api/hotels/{hotel_id}/reservations` | Search reservations (by status, dates, guest, reference, room) | `reservations.view` |
| POST | `/api/hotels/{hotel_id}/reservations` | Create a reservation (individual, group, corporate, walk-in …) | `reservations.create` |
| GET | `/api/reservations/{res_id}` | Reservation detail with folio balance and history | `reservations.view` |
| PATCH | `/api/reservations/{res_id}` | Modify dates, room category, occupants, rate or notes | `reservations.modify` |
| POST | `/api/reservations/{res_id}/assign-room` | Assign or change the room for a future reservation | `reservations.modify` |
| POST | `/api/reservations/{res_id}/confirm` | Confirm a tentative/waitlisted reservation | `reservations.modify` |
| POST | `/api/reservations/{res_id}/cancel` | Cancel a reservation with a reason | `reservations.cancel` |
| POST | `/api/reservations/{res_id}/no-show` | Mark a reservation as no-show | `reservations.cancel` |
| GET | `/api/hotels/{hotel_id}/cancellation-policies` | Cancellation policies | `reservations.view` |
| POST | `/api/hotels/{hotel_id}/cancellation-policies` | Create a cancellation policy (name, free_until_hours, fee_type none/first_night/percent/fixed, fee_value, no_show_fee_type, no_show_fee_value, is_default) | `admin.settings.manage` |
| PATCH | `/api/cancellation-policies/{policy_id}` | Change a cancellation policy (applies to bookings made afterwards) | `admin.settings.manage` |
| GET | `/api/reservations/{res_id}/cancellation-fee` | Fee that would apply if the booking were cancelled now (?kind=cancel/no_show) | `reservations.view` |

## Rooms

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/room-types` | List room categories | `rooms.view` |
| POST | `/api/hotels/{hotel_id}/room-types` | Create a room category | `rooms.manage` |
| PATCH | `/api/room-types/{type_id}` | Update a room category and its rates | `rooms.manage` |
| GET | `/api/hotels/{hotel_id}/rooms` | Room-status board | `rooms.view` |
| POST | `/api/hotels/{hotel_id}/rooms` | Create a room | `rooms.manage` |
| PATCH | `/api/rooms/{room_id}` | Edit room details | `rooms.manage` |
| POST | `/api/rooms/{room_id}/housekeeping-status` | Set room housekeeping status (dirty / clean / inspected) | `rooms.status.update` |
| POST | `/api/rooms/{room_id}/service-status` | Block a room / set out of order, out of service, maintenance, VIP hold, or return to service | `rooms.block` |
| GET | `/api/room-types/{rt_id}/media` | Photos and videos of a room category | `rooms.view` |
| POST | `/api/room-types/{rt_id}/media` | Add a photo (filename, content_base64; JPEG/PNG/WebP up to 5 MB) or a video (kind=video, url) with a caption | `rooms.manage` |
| DELETE | `/api/media/{media_id}` | Remove a photo or video | `rooms.manage` |

## Sales

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/promo-codes` | Promotional codes | `promotions.manage` |
| POST | `/api/hotels/{hotel_id}/promo-codes` | Create a promotional code | `promotions.manage` |
| PATCH | `/api/promo-codes/{promo_id}` | Edit or deactivate a promotional code | `promotions.manage` |
| GET | `/api/hotels/{hotel_id}/accounts/corporate` | Corporate, travel-agent and government accounts with production | `sales.view` |
| GET | `/api/hotels/{hotel_id}/accounts/active` | Active accounts for booking (id, name, kind) | `reservations.create` |
| POST | `/api/hotels/{hotel_id}/accounts/corporate` | Create an account (lead, prospect or active) | `sales.manage` |
| PATCH | `/api/accounts/corporate/{account_id}` | Edit an account | `sales.manage` |
| GET | `/api/accounts/corporate/{account_id}` | Account with negotiated rates, recent bookings and city-ledger balance | `sales.view` |
| POST | `/api/accounts/corporate/{account_id}/rates` | Add a negotiated rate (hotel_id, room_type_id, rate, valid_from, valid_to) | `sales.manage` |
| GET | `/api/hotels/{hotel_id}/sales/targets` | Sales targets and achievement for a year (?year) | `sales.view` |
| PUT | `/api/hotels/{hotel_id}/sales/targets` | Set a target (period YYYY-MM, metric, target, owner_id) | `sales.manage` |
| GET | `/api/hotels/{hotel_id}/revenue/pricing` | Seasons, dynamic pricing rules and competitor rates | `sales.view` |
| POST | `/api/hotels/{hotel_id}/revenue/seasons` | Add a seasonal adjustment (name, start_date, end_date, adjustment_bp e.g. 2000 = +20 %, optional room_type_id) | `sales.pricing` |
| POST | `/api/revenue/seasons/{season_id}/toggle` | Activate or deactivate a season | `sales.pricing` |
| POST | `/api/hotels/{hotel_id}/revenue/rules` | Propose an occupancy-based rule (name, min/max_occupancy_pct, adjustment_bp, room_type_id); a second person must approve it | `sales.pricing` |
| POST | `/api/revenue/rules/{rule_id}/decide` | Approve (activate), reject, or deactivate a dynamic pricing rule — never your own proposal | `sales.pricing_approve` |
| POST | `/api/hotels/{hotel_id}/revenue/competitor-rates` | Record competitor rates: rows[{competitor, stay_date, room_category, rate, source}] | `sales.pricing` |
| GET | `/api/hotels/{hotel_id}/revenue/dashboard` | Forward 30 days on the books with pickup and recommendations; KPIs for the period and year-on-year by month | `sales.view` |

## Security

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/incidents` | Security incidents (?status, ?category); restricted cases only for security.sensitive | `security.view` |
| POST | `/api/hotels/{hotel_id}/incidents` | Record an incident (occurred_at, location, category, severity, description, persons_involved, actions_taken, restricted) | `security.report` |
| GET | `/api/incidents/{incident_id}` | Incident with investigation notes | `security.view` |
| POST | `/api/incidents/{incident_id}/update` | Investigate: add a note, assign, set status (investigating / resolved needs resolution / closed) | `security.manage` |
| GET | `/api/hotels/{hotel_id}/visitors` | Visitor & contractor log (?date, ?on_site=1) | `security.view` |
| POST | `/api/hotels/{hotel_id}/visitors` | Sign a visitor, contractor or delivery in | `security.manage` |
| POST | `/api/visitors/{visitor_id}/sign-out` | Sign a visitor out | `security.manage` |
| GET | `/api/hotels/{hotel_id}/lost-found` | Lost & found register (?status, ?q) | `lostfound.manage` |
| POST | `/api/hotels/{hotel_id}/lost-found` | Log a found item (description, category, location, room_id, valuable, stored_location); kept 90 days (180 if valuable) | `lostfound.manage` |
| POST | `/api/lost-found/{item_id}/release` | Return an item to its owner (claimant name & contact, ID checked required for valuables) or dispose/donate after the holding period | `lostfound.manage` |
| GET | `/api/hotels/{hotel_id}/emergency-contacts` | Emergency contacts (any signed-in staff member) | signed in |
| PUT | `/api/hotels/{hotel_id}/emergency-contacts` | Replace the emergency contact list: items[{name, role, phone, notes}] | `security.manage` |
| POST | `/api/integrations/access-events` | Door-lock, key-card, access-control and CCTV systems push events here (header X-EHMS-Integration-Token); CCTV sends source=cctv, door=camera name, event=motion/tamper/alarm and an optional https clip_url | public |
| GET | `/api/hotels/{hotel_id}/access-events` | Access-control event log (?door, ?date) | `security.view` |

## Website

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/public/site` | Published website of the main hotel (?hotel=CODE for another property) | public |
| GET | `/api/public/website-media/{media_id}` | A website image | public |
| POST | `/api/public/site/enquiries` | Contact form: hotel (code, optional), kind general/rooms/dining/event, name, email, phone, subject, message, event_date, guests, marketing_consent | public |
| GET | `/api/hotels/{hotel_id}/website` | Website editor: draft and published content, images, status and the editable fields | `website.manage` |
| PUT | `/api/hotels/{hotel_id}/website` | Save the website draft (content document; validated) | `website.manage` |
| POST | `/api/hotels/{hotel_id}/website/publish` | Publish the saved draft to the public website | `website.manage` |
| POST | `/api/hotels/{hotel_id}/website/discard` | Throw away unpublished changes (draft goes back to the published version) | `website.manage` |
| POST | `/api/hotels/{hotel_id}/website/preview` | What the public site would look like with this content (not saved) | `website.manage` |
| POST | `/api/hotels/{hotel_id}/website/media` | Upload a website image: filename, content_base64 (JPEG/PNG/WebP up to 5 MB), caption | `website.manage` |
| PATCH | `/api/website/media/{media_id}` | Change an image's caption | `website.manage` |
| DELETE | `/api/website/media/{media_id}` | Remove an image (refused while the published website or the draft uses it) | `website.manage` |
| GET | `/api/hotels/{hotel_id}/website/enquiries` | Enquiries sent from the website (?status) | signed in |
| POST | `/api/website/enquiries/{enquiry_id}/status` | Record handling of an enquiry: status replied / closed / spam, note | signed in |

