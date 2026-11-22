# EHMS REST API reference

Generated from the route table (`python -m ehms.apidoc`). The live, machine-readable OpenAPI 3 spec is served at `/api/openapi.json`, with a browsable list at `/api/docs`.

**Conventions**

- Authenticate with `POST /api/auth/login`, then send `Authorization: Bearer <token>` on every request.
- Request and response bodies are JSON. Money values are **integers in minor units** (kobo for NGN): ₦45,000.00 is `4500000`.
- Stock quantities are decimals in the item's unit with up to 3 decimal places (`0.25` kg); they are stored exactly as thousandths.
- Dates are `YYYY-MM-DD`; timestamps are ISO-8601 UTC.
- Errors return `{"error": {"code", "message", "details"}}` with HTTP 400 (validation), 401 (sign-in), 403 (permission/scope), 404, 409 (conflict, e.g. double booking, unsettled balance, insufficient stock), 423 (account locked), 429 (rate limit), 501 (integration not configured).
- Payments require an `idempotency_key`; repeating a request with the same key never creates a second payment.

Total endpoints: **170**

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

## Booking engine (public)

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
| GET | `/api/hotels/{hotel_id}/taxes` | Tax and levy rules | signed in |
| POST | `/api/hotels/{hotel_id}/taxes` | Add a tax rule (rate in basis points, e.g. 750 = 7.5%) | `admin.settings.manage` |
| PATCH | `/api/taxes/{tax_id}` | End-date or deactivate a tax rule | `admin.settings.manage` |
| GET | `/api/hotels/{hotel_id}/payment-methods` | Payment methods | signed in |
| POST | `/api/hotels/{hotel_id}/payment-methods` | Add a payment method | `admin.settings.manage` |

## Folio

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/folios/{folio_id}` | Guest folio with all lines and balance | `folio.view` |
| GET | `/api/reservations/{res_id}/folio` | Open (or create) the folio for a reservation | `folio.view` |
| POST | `/api/folios/{folio_id}/charges` | Post a charge (restaurant, minibar, laundry, transport …) to a folio | `folio.post_charge` |
| POST | `/api/folios/{folio_id}/adjustments` | Reverse a charge line, or grant an allowance (credit) with a reason | `folio.adjust` |

## Front desk

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

## Kitchen

| Method | Path | Purpose | Access |
|---|---|---|---|
| GET | `/api/hotels/{hotel_id}/kitchen/tickets` | Kitchen display tickets: open orders' items that are sent, preparing or ready (?station, ?outlet_id) | `kitchen.view` |
| POST | `/api/kitchen/items/{item_id}/status` | Move a kitchen item to preparing / ready (kitchen staff) or served (service staff) | `kitchen.view` |
| GET | `/api/hotels/{hotel_id}/kitchen/performance` | Kitchen performance: items, average and slowest preparation time per station (?from, ?to) | `kitchen.view` |

## Payments

| Method | Path | Purpose | Access |
|---|---|---|---|
| POST | `/api/folios/{folio_id}/payments` | Record a payment or deposit (cash, transfer, POS card, city ledger) | `payments.receive` |
| POST | `/api/folios/{folio_id}/refund-requests` | Request a refund (requires approval by a different authorised user) | `payments.refund_request` |
| GET | `/api/hotels/{hotel_id}/approvals` | Approval requests | `approvals.view` |
| POST | `/api/approvals/{approval_id}/decide` | Approve or reject a refund request (maker-checker) | `payments.refund_approve` |

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

