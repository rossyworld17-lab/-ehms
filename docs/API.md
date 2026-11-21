# EHMS REST API reference

Generated from the route table. The live, machine-readable OpenAPI 3 spec is served at `/api/openapi.json`, with a browsable list at `/api/docs`.

**Conventions**

- Authenticate with `POST /api/auth/login`, then send `Authorization: Bearer <token>` on every request.
- Request and response bodies are JSON. Money values are **integers in minor units** (kobo for NGN): ₦45,000.00 is `4500000`.
- Dates are `YYYY-MM-DD`; timestamps are ISO-8601 UTC.
- Errors return `{"error": {"code", "message", "details"}}` with HTTP 400 (validation), 401 (sign-in), 403 (permission/scope), 404, 409 (conflict, e.g. double booking, unsettled balance), 423 (account locked), 429 (rate limit), 501 (integration not configured).
- Payments require an `idempotency_key`; repeating a request with the same key never creates a second payment.

Total endpoints: **94**

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

## Auth

| Method | Path | Purpose | Access |
|---|---|---|---|
| POST | `/api/auth/login` | Sign in with email and password | public |
| POST | `/api/auth/mfa/verify` | Complete sign-in with a 6-digit authenticator code | signed-in user |
| POST | `/api/auth/logout` | Sign out (revoke current session) | signed-in user |
| GET | `/api/auth/me` | Current user profile, roles, permissions and hotels | signed-in user |
| POST | `/api/auth/mfa/setup` | Start MFA enrolment (returns secret and otpauth URI) | signed-in user |
| POST | `/api/auth/mfa/enable` | Confirm MFA enrolment with a code from the authenticator app | signed-in user |
| POST | `/api/auth/mfa/disable` | Disable MFA (requires password and current code) | signed-in user |
| POST | `/api/auth/password` | Change own password | signed-in user |
| POST | `/api/auth/password-reset/request` | Request a password-reset link by email | public |
| POST | `/api/auth/password-reset/confirm` | Set a new password using a reset code | public |
| GET | `/api/auth/sessions` | List my active sessions | signed-in user |

## Booking Engine

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/public/hotels/{code}` | Public hotel profile and room categories | public |
| GET | `/api/public/hotels/{code}/availability` | Available room categories and total prices for dates | public |
| POST | `/api/public/hotels/{code}/bookings` | Submit an online booking (pay at hotel unless a payment gateway is configured) | public |
| GET | `/api/public/bookings/{reference}` | Look up a booking by reference and email | public |
| POST | `/api/public/bookings/{reference}/cancel` | Guest cancellation of a future booking (subject to hotel policy) | public |

## Dashboard

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/dashboard` | Executive dashboard KPIs and trends | `dashboard.view` |

## Finance

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/taxes` | Tax and levy rules | signed-in user |
| POST | `/api/hotels/{hotel_id}/taxes` | Add a tax rule (rate in basis points, e.g. 750 = 7.5%) | `admin.settings.manage` |
| PATCH | `/api/taxes/{tax_id}` | End-date or deactivate a tax rule | `admin.settings.manage` |
| GET | `/api/hotels/{hotel_id}/payment-methods` | Payment methods | signed-in user |
| POST | `/api/hotels/{hotel_id}/payment-methods` | Add a payment method | `admin.settings.manage` |

## Folio

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/folios/{folio_id}` | Guest folio with all lines and balance | `folio.view` |
| GET | `/api/reservations/{res_id}/folio` | Open (or create) the folio for a reservation | `folio.view` |
| POST | `/api/folios/{folio_id}/charges` | Post a charge (restaurant, minibar, laundry, transport …) to a folio | `folio.post_charge` |
| POST | `/api/folios/{folio_id}/adjustments` | Reverse a charge line, or grant an allowance (credit) with a reason | `folio.adjust` |

## Frontdesk

| Method | Path | Purpose | Access |
|---|---|---|---|
| POST | `/api/reservations/{res_id}/check-in` | Check a guest in | `frontdesk.checkin` |
| GET | `/api/reservations/{res_id}/checkout-preview` | Preview charges still to be posted and the balance due at check-out | `frontdesk.checkout` |
| POST | `/api/reservations/{res_id}/check-out` | Check a guest out (posts remaining room nights; balance must be settled) | `frontdesk.checkout` |
| POST | `/api/reservations/{res_id}/room-move` | Move an in-house guest to another room | `frontdesk.room_move` |
| POST | `/api/hotels/{hotel_id}/night-audit` | Night audit: post tonight's room charges for in-house guests and roll the business date | `frontdesk.night_audit` |

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

## Payments

| Method | Path | Purpose | Access |
|---|---|---|---|
| POST | `/api/folios/{folio_id}/payments` | Record a payment or deposit (cash, transfer, POS card, city ledger) | `payments.receive` |
| POST | `/api/folios/{folio_id}/refund-requests` | Request a refund (requires approval by a different authorised user) | `payments.refund_request` |
| GET | `/api/hotels/{hotel_id}/approvals` | Approval requests | `approvals.view` |
| POST | `/api/approvals/{approval_id}/decide` | Approve or reject a refund request (maker-checker) | `payments.refund_approve` |

## Property

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels` | Hotels the current user can access | signed-in user |
| GET | `/api/hotels/{hotel_id}` | Hotel profile and configuration | signed-in user |
| POST | `/api/hotels` | Register a hotel or branch | `property.manage` |
| PATCH | `/api/hotels/{hotel_id}` | Update hotel profile and policies | `admin.settings.manage` |
| POST | `/api/hotels/{hotel_id}/departments` | Add a department | `admin.settings.manage` |

## Reports

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/folios/{folio_id}/invoice.pdf` | Guest invoice / receipt as PDF | `folio.view` |
| GET | `/api/hotels/{hotel_id}/reports` | List available reports | `reports.view` |
| GET | `/api/hotels/{hotel_id}/reports/{name}` | Run a report (?format=json|csv|xlsx|pdf) | `reports.view` |

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

