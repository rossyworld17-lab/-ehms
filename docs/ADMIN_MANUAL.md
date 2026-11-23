# Administrator manual

## First setup
1. Deploy (see DEPLOYMENT.md) and run the bootstrap command to create your organisation, first hotel and an
   Organisation Owner account. Sign in with the temporary password and change it immediately; turn on MFA.
2. **Hotel settings → Profile & policies**: legal name, RC number, address, contacts, check-in/out times,
   service charge %, cancellation and reservation policies, invoice terms.
3. **Hotel settings → Taxes & charges**: add VAT and any state levies with the correct rate and effective date.
   Rates are never hard-coded — confirm current rates with your tax adviser. To change a rate, end-date the old
   rule (deactivate) and add a new one effective from the change date.
4. **Hotel settings → Payment methods**: cash, transfer, POS and city ledger are created automatically. Add a
   method per bank account if you want separate reconciliation; each maps to an asset account.
5. **Rooms & rates**: create categories (standard, weekend Fri/Sat, corporate and extra-person rates) and rooms.
6. **Users & access**: create staff accounts, assign roles and hotels. New users receive a temporary password
   and must change it.
7. Additional properties: `POST /api/hotels` (organisation-wide administrators) — departments and payment
   methods are seeded automatically.

## Roles and permissions
29 role templates mirror the hotel organisation (Super Administrator … Guest). Open **Roles & permissions**
to view or adjust any role, or create custom roles. Safeguards:
- You can only grant permissions you hold yourself (prevents privilege escalation).
- Sensitive permissions: `guests.identity.view`, `reservations.override_rate`, `reservations.overbook`,
  `folio.adjust`, `payments.refund_approve`, `accounting.post_manual`, `admin.*`.
- Release 0.4 permissions: `pos.*` (view, order, settle, post_to_room, discount, void, shift, manage), `kitchen.view`,
  `kitchen.update`, `inventory.*` (view, manage, requisition, approve, issue, adjust) and `procurement.*` (view,
  suppliers, requisition, order, approve, approve_high, receive, invoice, invoice_approve, pay). Sensitive ones:
  `pos.void`, `pos.discount`, `inventory.adjust`, `procurement.approve_high`, `procurement.invoice_approve`,
  `procurement.pay`. The restaurant, kitchen, inventory, storekeeper and procurement role templates now carry them.
- Upgrading: when a new release adds permissions, existing **system** roles receive them once on first start-up;
  if you later remove one it is not re-added. Custom roles are never changed.
- Roles for modules not yet released (HR, maintenance, security …) carry dashboard access only.

## Restaurant, stores and procurement setup (release 0.4)
1. **Inventory → Stores**: create stores (main, kitchen, bar, housekeeping …). "Allow negative stock" lets sales
   continue when recipe stock runs out (stock goes negative and is corrected by the next count); it is off by
   default so that stock records stay accurate.
2. **Inventory → Item catalogue**: register items with unit, standard cost, reorder level/quantity, and tick
   "Track batches & expiry" for perishables. Post **opening balances** with *Adjust → Opening balance*
   (credited to Owner's Equity).
3. **Menu & outlets**: create outlets with an issuing store, tables, categories, items and recipes.
4. **Procurement → Suppliers**: enter suppliers, payment terms and withholding-tax rate (confirm the applicable
   rate for each supplier category with your tax adviser). Bank details are masked for users without
   `procurement.suppliers` or `procurement.pay`.
5. Approval settings (`PUT /api/hotels/{id}/procurement/settings`, requires `admin.settings.manage`):
   `high_value_threshold` (default ₦500,000 — POs above it need `procurement.approve_high`) and
   `invoice_tolerance_bp` (default 50 = 0.5 %, minimum ₦100).
6. New ledger accounts are added automatically: 2010 Goods Received Not Invoiced, 5310 Cost of Food & Beverage
   Sold, 5320 Housekeeping & Guest Supplies, 5950 Inventory Shrinkage & Wastage, 5960 Purchase Price Variance.

## Accounts and sessions
- **Suspend/Activate** a user; suspension ends their sessions immediately.
- **Reset password** issues a temporary password and signs the user out everywhere.
- **Sessions** shows a user's active devices; revoke any of them.
- Locked accounts unlock automatically after the lockout period or when an administrator resets the password.

## Audit and control
- **Audit trail** records every significant action with before/after values, user, time and IP. It is
  append-only at database level.
- **Sign-in history** shows successful and failed logins with reasons.
- Refunds require a second approver; overbooking and rate overrides require permission and are logged.
- The ledger cannot be edited; corrections are reversals that keep the original entry.

## Messaging
**Hotel settings → Message log** lists every booking confirmation, invoice and password-reset email with its
status. "Not configured" means no SMTP server is set; configure `EHMS_SMTP_*` and run the delivery worker
(see DEPLOYMENT.md).

## Security settings (environment variables)
`EHMS_SESSION_IDLE_MINUTES`, `EHMS_MAX_FAILED_LOGINS`, `EHMS_LOCKOUT_MINUTES`, `EHMS_MIN_PASSWORD_LENGTH`,
`EHMS_LOGIN_RATE_LIMIT`. Keep `EHMS_SECRET_KEY` secret and stable — changing it signs everyone out.

## Data protection (Nigeria Data Protection Act 2023)
Capture identification only where required, restrict `guests.identity.view` to front-office supervisors,
record marketing consent before campaigns, set backup retention to your policy, and handle access/erasure
requests through the guest profile. Appoint a data protection officer as your obligations require.

## Finance controls, promotions and messaging (release 0.5)
- New permissions: `finance.expenses.request / approve / pay`, `accounting.reconcile`, `accounting.budgets`,
  `accounting.close_period`, `promotions.manage`, `admin.notifications.manage`. Department managers can submit
  expense claims; the Finance Manager approves; the Accountant pays and reconciles.
- **Period close** (Finance operations → Periods): once a month is closed, nothing can be posted with a date in
  it — including night audit and late invoices. Reopening needs a reason and is audited.
- **Budgets**: enter monthly amounts per revenue or expense account; Budget vs actual shows variances.
- **Promotions**: promo codes apply to the room price on the online booking engine (dates refer to arrival).
- **Messaging**: templates per event (booking received, day-before reminder, payment link, birthday, staff
  alerts) and channel; turn any off. Delivery log shows every message with its status and provider error.
- Online payment and messaging provider settings are environment variables — see DEPLOYMENT.md.

## Laundry, HR and payroll (release 0.6)
- Permissions: `laundry.view/manage`, `hr.view`, `hr.manage`, `hr.records` (confidential), `hr.attendance`,
  `hr.leave.approve`, `payroll.view`, `payroll.run`, `payroll.approve`, `payroll.pay`. HR prepares payroll,
  the Finance Manager approves, the Accountant pays and remits; department managers keep rosters and attendance
  and approve leave for their teams.
- Link each employee to their user account so they can use **My HR** (self clock-in, leave, payslips).
- **Payroll rules** (Payroll → Statutory rules, `payroll.approve`): PAYE bands, rent relief, pension, NHF, NSITF,
  ITF, working days, overtime multiplier and minimum-wage warning. Defaults follow Nigerian rules as commonly
  applied from 2026 — confirm them with your tax and payroll advisers. Each run stores the rules it used.
- Leave types and entitlements: HR → Leave → Leave types. Laundry prices and express surcharge: Laundry → Price list.
- New ledger accounts are added automatically: 1300 Staff Loans & Advances, 2130 Salaries & Wages Payable,
  2140 PAYE Payable, 2150 Pension Payable, 2160 NHF Payable, 2170 Other Statutory Deductions Payable, 5010
  Employer Pension & Statutory Contributions.

## Maintenance, security and events (release 0.7)
- Permissions: `maintenance.report` (most operational staff), `maintenance.work` (technicians),
  `maintenance.manage` (maintenance manager), `maintenance.view`; `security.report`, `security.view`,
  `security.manage`, `security.sensitive` (restricted incidents), `lostfound.manage`; `events.view`,
  `events.manage` (sales), `events.invoice` (finance).
- Depreciation is posted by finance (`accounting.post_manual`) once per month; capitalise assets when you
  register them (existing assets as opening balance, new purchases against cash/bank).
- The worker raises preventive work orders three days before they fall due and notifies the assignee.
- Door-lock / key-card systems: set `EHMS_ACCESS_API_TOKEN` and have the vendor's gateway POST events to
  `/api/integrations/access-events` with header `X-EHMS-Integration-Token` (body: `hotel_code`, `source`,
  `events[{door, event, credential, person, occurred_at}]`).
- New ledger accounts: 1500 Property, Plant & Equipment, 1510 Accumulated Depreciation, 5410 Depreciation.

## Guest relations, sales and revenue (release 0.8)
- Permissions: `crm.view`, `crm.complaints` (front office and guest service can log and update complaints),
  `crm.manage` (loyalty rules and point adjustments), `crm.campaigns`; `sales.view`, `sales.manage` (accounts,
  targets, competitor rates), `sales.pricing` (propose seasons and rules), `sales.pricing_approve` (finance
  manager / GM — a person cannot approve a rule they proposed).
- Loyalty defaults (change with `PUT /api/hotels/{id}/loyalty/rules`): 1 point per ₦1,000 settled, a point is
  worth ₦10, minimum redemption 500 points, tiers bronze/silver (2,000)/gold (10,000)/platinum (30,000) with
  10/25/50 % bonus points. Redemptions post Dr Allowances, Cr Guest Ledger.
- Complaint SLA: urgent 2 h, high 8 h, normal 24 h, low 72 h. The worker escalates overdue complaints.
- Campaigns go only to guests with marketing consent; every message includes opt-out wording and opt-outs are
  recorded. Set the public URL (`EHMS_PUBLIC_URL`) so survey links in emails point to your server.
- Rates applied to a booking: negotiated account rate → weekend rate → season adjustment → approved occupancy
  rule. The result is stored per night on the reservation; changing prices later does not reprice it.

## Insights, assistant and documents (release 0.9)
- Permissions: `bi.view` (analytics, forecast, occupancy history; HR analytics also needs `hr.view`, profit figures
  `reports.financial`), `bi.schedule`; `ai.assistant`, `ai.anomalies.view` (auditors, accountants), `ai.review`
  (finance manager, GM); `documents.view`, `documents.upload`, `documents.manage` (retention, legal hold, deletion),
  `documents.confidential`. Employee documents marked confidential also need `hr.records`; documents on restricted
  security incidents need `security.sensitive`; report outputs need the report's own permission.
- Scheduled reports run as the person who created them: if that person is suspended or loses the permission, the
  schedule pauses itself. Recipients who lose access are skipped (shown in "last run").
- The anomaly scan runs once a day in the worker and notifies holders of `ai.review`. Thresholds are deliberately
  conservative; tell staff that a flag is a question, not a finding.
- Document retention defaults (years): identity 7, financial (invoice, receipt, statement, quotation) 7, contracts,
  licences, policies, certificates, HR and medical records 10, correspondence and other 6, photos 3, generated
  reports 2. Override per hotel with the setting `documents.retention.<category>`. Retention can only be extended;
  deletion erases the file but keeps the record and its access history. Back up the documents volume together with
  the database (the `backup` service does both).
- Ask EHMS uses the built-in engine unless you set `EHMS_AI_PROVIDER=anthropic` and `ANTHROPIC_API_KEY` and install
  the `anthropic` package. With it enabled, aggregated figures the asking user may see (no guest names, contacts or
  identity data) are sent to Anthropic to phrase the answer — record this in your data-protection register before
  enabling it. Questions are logged (`/api/hotels/{id}/assistant/log`, needs `admin.audit.view`).
- Inventory lead time for reorder suggestions: hotel setting `inventory.lead_time_days` (default 7).

## Groups, billing, currencies and recruitment (release 0.95)
- Permissions: `reservations.groups`, `reservations.waive_fee` (front office manager, finance manager), `folio.transfer`
  (reception), `finance.notes.request` (front office manager, accountant), `finance.notes.approve` (finance manager),
  `finance.exchange_rates` (accountant, finance manager), `hr.recruit` (HR).
- Cancellation policies: Hotel settings → Cancellation policies. Demo defaults: standard (free until 24 h, then first
  night), non-refundable (100 %), groups (free until 7 days, then 50 %). Each booking keeps the policy it was made
  under; a policy already used cannot be re-priced — create a new one.
- Exchange rates are entered daily (base-currency units per 1 foreign unit, up to 6 decimals) and never edited;
  a jump of more than 10 % triggers a warning. Foreign cash is booked to the payment method's account at its
  converted value; banking differences are posted as normal bank charges or a manual journal.
- Costing method: Hotel settings → Stock costing (needs `inventory.manage` and `accounting.view`). Change it at a
  period end with your auditors' agreement; batches received before release 0.95 are costed at the average.
- Recruitment data: anonymise unsuccessful applicants after closing an opening unless they agreed to be kept on file.

## Full HR suite (release 1.1)
- Permissions: `hr.requests.approve` (decide staff requests), `hr.performance` (appraisals) and `hr.accounts` (give
  employees a login). The HR manager role template receives all three on upgrade; add them to custom roles as needed.
- HR managers can issue logins only with roles that hold no administrator permissions; administrators remain the
  only people who create admin users.
- Recording an exit (or any non-active status) suspends the linked login and ends its sessions; reactivating the
  employee restores it.
- Public holidays: fixed Nigerian holidays are loaded for two years; add movable holidays (Eid, Easter) each year
  under Human resources → Leave → Public holidays. They are excluded from leave day counts.
- Salary advance limit is one month's basic pay; staff loan limit is six months' basic pay (up to 24 months).
  Approved advances and loans are paid by a holder of `payroll.pay`, who is notified.
- Every login that should use My HR needs an employee record; the HR dashboard lists logins without one.
