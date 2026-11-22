# Requirements traceability

Status of every functional requirement in *EHMS Software Requirements Specification v1* against release 0.9.

**Implemented** = working and covered by tests · **Partial** = core behaviour works, noted gaps planned · **Planned** = scheduled in ROADMAP.md

Summary: **119 implemented**, **8 partial**, **0 planned** (of 127).

| ID | Requirement | Status | Notes |
|---|---|---|---|
| FR-ADM-001 | Create, edit, deactivate and manage user accounts. | Implemented | admin.py users CRUD/suspend |
| FR-ADM-002 | Configure roles and permissions by module, action, property, branch and organisational scope. | Implemented | roles/permissions, hotel scope; branch=hotel |
| FR-ADM-003 | Support password policies, account lockout and multi-factor authentication. | Implemented | password policy, lockout, TOTP MFA |
| FR-ADM-004 | Configure hotel identity, contact details, room categories, facilities, services, outlets and departments. | Implemented | hotel profile, room categories, departments; restaurant/bar/room-service outlets with tables (0.4) |
| FR-ADM-005 | Configure currencies, exchange rates, taxes, service charges and payment methods. | Partial | taxes, service charge, payment methods; exchange rates planned |
| FR-ADM-006 | Maintain administrative audit logs and configurable notification templates and business rules. | Implemented | audit logs; notification templates per event & channel; business rules (thresholds, tolerances) configurable (0.5) |
| FR-PRP-001 | Register multiple hotel properties and branches, each with a unique identifier. | Implemented | multi-hotel |
| FR-PRP-002 | Maintain property-specific rooms, rates, departments, staff, outlets and operational settings. | Implemented | per-hotel rooms, rates, departments, staff scope |
| FR-PRP-003 | Provide consolidated organisation-level reports to authorised users. | Implemented | consolidated TB/P&L/BS |
| FR-PRP-004 | Restrict users to properties and records permitted by their assigned scope. | Implemented | check_hotel() scoping |
| FR-PRP-005 | Support property-specific currencies, taxes, time zones and business rules. | Partial | per-hotel currency/taxes/time zone stored; multi-currency conversion planned |
| FR-PMS-001 | Create room categories and rooms with unique identifiers, floor, capacity, facilities, description and rate plan. | Implemented |  |
| FR-PMS-002 | Support Available, Reserved, Occupied, Dirty, Clean, Inspected, Out of Order, Out of Service, Under Maintenance and Blocked statuses. | Implemented | occupancy × housekeeping × service status |
| FR-PMS-003 | Provide a visual room-status dashboard and occupancy history. | Implemented | live board; occupancy history by category (heat map) and by room (0.9) |
| FR-PMS-004 | Prevent overlapping confirmed room allocations unless an authorised overbooking policy applies. | Implemented | transactional overlap check + authorised overbooking |
| FR-PMS-005 | Allow authorised room blocks for maintenance and other approved purposes. | Implemented | room blocks with reason |
| FR-PMS-006 | Support room upgrades, transfers and changes with authorisation and audit records. | Implemented | room move / upgrade with audit |
| FR-PMS-007 | Calculate occupancy and provide room inventory reports. | Implemented | dashboard & occupancy report |
| FR-RES-001 | Create individual, group, corporate and walk-in reservations with guest, dates, room category, occupants, rate and special requests. | Implemented |  |
| FR-RES-002 | Generate unique booking references and display availability for requested dates. | Implemented |  |
| FR-RES-003 | Support Enquiry, Tentative, Confirmed, Checked In, Checked Out, Cancelled, No Show and Waitlisted statuses. | Implemented |  |
| FR-RES-004 | Support deposits, advance payments, modifications, cancellation policies and applicable fees. | Partial | deposits, modifications, cancellation; automatic fee calculation planned |
| FR-RES-005 | Generate booking confirmations and send configured notifications and reminders. | Implemented | confirmations by email; day-before reminders by email/SMS/WhatsApp via the background worker (0.5) |
| FR-RES-006 | Maintain reservation history, identify potential duplicates and support corporate or negotiated rates. | Implemented | history, duplicate detection, corporate rate |
| FR-RES-007 | Support group room blocks, rooming lists and reports by date, source, status and channel. | Partial | group/corporate bookings & reports; rooming lists planned |
| FR-BKG-001 | Provide a mobile-friendly online booking interface with date, room and guest search. | Implemented |  |
| FR-BKG-002 | Display room descriptions, images, amenities, rates and applicable charges. | Implemented |  |
| FR-BKG-003 | Allow guests to submit booking details, review total price and pay through approved gateways. | Implemented | pay at hotel or pay online through Paystack / Flutterwave hosted checkout; confirmed on verified payment (0.5) |
| FR-BKG-004 | Synchronise confirmed online bookings with central availability and reservations. | Implemented | shared inventory |
| FR-BKG-005 | Support promotional codes, discounts, policies, privacy notices and terms. | Implemented | promo codes (percent/amount, dates, minimum nights, usage limit, room category), policies, privacy, terms (0.5) |
| FR-FO-001 | Provide a front-office dashboard and reservation search by guest, reference, room or contact. | Implemented |  |
| FR-FO-002 | Support guest registration, lawful identification capture, walk-in registration and check-in. | Implemented |  |
| FR-FO-003 | Support early check-in, late check-out, room allocation and room changes under configured rules. | Implemented |  |
| FR-FO-004 | Generate guest folios and post room and approved service charges. | Implemented |  |
| FR-FO-005 | Support split bills, shared accounts, deposits, adjustments and authorised refunds. | Partial | deposits, adjustments, refunds; split bills planned |
| FR-FO-006 | Calculate outstanding balances, support check-out and issue invoices and receipts. | Implemented |  |
| FR-FO-007 | Update room status after check-out and maintain guest stay history. | Implemented |  |
| FR-CRM-001 | Maintain central guest profiles with contact details, preferences, booking history and communication preferences. | Implemented |  |
| FR-CRM-002 | Identify repeat guests and support loyalty categories, points and configurable rewards. | Implemented | repeat/VIP flags; loyalty points, tiers with bonuses, redemption as folio credit (0.8) |
| FR-CRM-003 | Record feedback, complaints and service preferences for authorised staff. | Implemented | complaints, feedback and surveys (0.8) |
| FR-CRM-004 | Support targeted campaigns subject to consent and applicable privacy rules. | Implemented | consent-only segments, preview, send, opt-out (0.8) |
| FR-CRM-005 | Provide guest satisfaction and retention reporting. | Implemented | CRM insights: rating, NPS, repeat rate, complaint times (0.8) |
| FR-POS-001 | Support multiple outlets, menu categories and items with prices, tax, availability and optional images. | Implemented | outlets, menu categories & items, price, station, availability/sold-out, optional image URL; tax via hotel rules (0.4) |
| FR-POS-002 | Support dine-in, takeaway, room service, table management, split bills and merged bills. | Implemented | dine-in tables, takeaway, room service; split bill by items, merge orders, move table (0.4) |
| FR-POS-003 | Create sales transactions and support multiple payment methods. | Implemented | settlement with split tenders: cash (with change), POS card, transfer, room charge (0.4) |
| FR-POS-004 | Post authorised room charges to guest folios and generate receipts. | Implemented | charge to in-house guest folio with net/service/tax split; 80 mm receipt PDF (0.4) |
| FR-POS-005 | Track cashier shifts, cash reconciliation, discounts and authorised voids. | Implemented | cashier shifts with float, expected vs counted cash and variance note; authorised discounts & voids with reasons (0.4) |
| FR-POS-006 | Provide outlet sales reports and record recipe-based stock consumption. | Implemented | outlet sales report; recipe-based stock consumption at settlement with cost of sales journal (0.4) |
| FR-KIT-001 | Transmit orders to the appropriate kitchen station and display pending orders. | Implemented | items routed to kitchen/grill/pastry/bar stations; kitchen display with station filter (0.4) |
| FR-KIT-002 | Allow kitchen staff to update order status, priority, preparation and completion times. | Implemented | sent → preparing → ready, rush priority, sent/started/ready/served timestamps (0.4) |
| FR-KIT-003 | Notify service staff when orders are ready and provide kitchen performance reports. | Implemented | ready items flagged on POS tables and orders, in-app notification record for the waiter; kitchen performance report (0.4) |
| FR-HSK-001 | Display rooms requiring cleaning and allow managers to assign tasks. | Implemented |  |
| FR-HSK-002 | Allow staff to update cleaning progress and managers to inspect and approve rooms. | Implemented |  |
| FR-HSK-003 | Update room readiness only after required cleaning and inspection. | Implemented |  |
| FR-HSK-004 | Record damaged or missing items, lost-and-found items, linen and laundry movements. | Implemented | damage/issue reporting (raises maintenance work orders), linen & laundry movements (0.6), lost-and-found register with claims and disposal (0.7) |
| FR-HSK-005 | Support laundry service orders, charges and housekeeping productivity reports. | Implemented | guest laundry orders with price list and express surcharge, billed to the folio on delivery; laundry summary (0.6) |
| FR-FIN-001 | Provide a configurable chart of accounts and double-entry accounting. | Implemented |  |
| FR-FIN-002 | Maintain a general ledger, accounts receivable, accounts payable, cashbook and bank accounts. | Implemented | GL, guest & city ledger, accounts payable via supplier invoices, cash/bank accounts (0.4) |
| FR-FIN-003 | Record income and expenses by department, property and category. | Implemented | income by department/property; expenses by department via expense claims, stock issues, GRN and supplier invoices (0.5) |
| FR-FIN-004 | Support budgets, budget-versus-actual analysis, payment allocation and reconciliation. | Implemented | monthly budgets, budget-vs-actual with variance; payment allocation; bank reconciliation with CSV import and auto-match (0.5) |
| FR-FIN-005 | Configure taxes, service charges, invoices, receipts, credit notes and debit notes. | Partial | taxes, service charge, invoices/receipts; credit/debit notes planned |
| FR-FIN-006 | Support financial approval workflows, bank reconciliation and financial period closing. | Implemented | maker-checker on refunds, requisitions, POs, invoices and expense claims; bank reconciliation; period close/reopen (0.5) |
| FR-FIN-007 | Generate trial balance, profit and loss, balance sheet, cash flow and departmental reports. | Implemented | trial balance, P&L, balance sheet, departmental revenue and direct-method cash-flow statement (0.5) |
| FR-FIN-008 | Prevent unauthorised changes to posted transactions; use controlled reversals or adjustments. | Implemented | DB triggers + reversals |
| FR-FIN-009 | Trace financial entries to originating operational transactions and preserve approval history. | Implemented | folio line → journal entry; approval history |
| FR-PAY-001 | Support cash, bank transfer, card and approved online gateway payments. | Implemented | cash, transfer, POS card, city ledger; online card/transfer via Paystack and Flutterwave (0.5) |
| FR-PAY-002 | Support deposits, partial payments, outstanding balances and authorised refunds. | Implemented |  |
| FR-PAY-003 | Verify payment status through trusted gateway responses or reconciliation. | Implemented | every online payment verified with the provider's verify API (signed webhooks + return page), amount & currency checked (0.5) |
| FR-PAY-004 | Prevent duplicate payment processing and maintain payment history. | Implemented | idempotency keys + duplicate reference check |
| FR-PAY-005 | Never store raw card security codes or sensitive card authentication data. | Implemented | no card data stored |
| FR-INV-001 | Maintain an item catalogue with codes, categories, units, costs, selling prices and reorder levels. | Implemented | item catalogue: code, barcode, category, unit, cost, sale price, reorder level & quantity (0.4) |
| FR-INV-002 | Support multiple stores, receipts, issues, transfers, adjustments and stocktaking. | Implemented | multiple stores; receipts (GRN), issues, transfers, adjustments, wastage, stock counts (0.4) |
| FR-INV-003 | Calculate stock balances and generate low-stock alerts. | Implemented | perpetual balances per store; low-stock alerts, dashboard count and reorder report (0.4) |
| FR-INV-004 | Support batches, expiry dates, FIFO and FEFO where configured. | Partial | batches & expiry dates with FEFO depletion and expiry alerts (0.4); valuation is weighted average (FIFO costing not offered) |
| FR-INV-005 | Record departmental consumption, valuation, variances and auditable stock movements. | Implemented | departmental issues, WAC valuation reconciled to the GL, count variances journalled, append-only movement ledger (0.4) |
| FR-PRO-001 | Maintain supplier records and performance history. | Implemented | supplier register (bank details masked without permission), on-time & rejection performance, balances (0.4) |
| FR-PRO-002 | Support requisitions, quotations, purchase orders and approval workflows. | Implemented | requisitions, quotations with price comparison, POs with standard/high-value approval and maker-checker (0.4) |
| FR-PRO-003 | Record goods received and compare orders, receipts and supplier invoices. | Implemented | GRN with rejections, batch & expiry; three-way match of invoice to goods received with tolerance (0.4) |
| FR-PRO-004 | Record supplier payments and generate procurement reports. | Implemented | supplier payments with withholding tax, idempotency; payables ageing, spend by supplier, payables report (0.4) |
| FR-HR-001 | Maintain employee records, departments, job positions and employment documents. | Implemented | employee register: personal, employment, department, position, pay, bank & statutory IDs, qualifications (0.6) |
| FR-HR-002 | Support recruitment, onboarding, separation and employee self-service. | Partial | onboarding & exit records, linked system logins and self-service (leave, payslips, clock-in) (0.6); recruitment pipeline planned |
| FR-HR-003 | Support attendance, configurable shifts, duty rosters and leave applications and approvals. | Implemented | shift templates & weekly rosters, attendance with overtime, self clock-in with lateness, leave types, balances and approval (0.6) |
| FR-HR-004 | Maintain training, performance, disciplinary and incident records with restricted access. | Implemented | training, appraisal, disciplinary, commendation, transfer, promotion records restricted to hr.records (0.6) |
| FR-HR-005 | Generate HR reports. | Implemented | headcount, attendance, leave balances (0.6); HR analytics: turnover, attendance, lateness, overtime, leave, payroll cost (0.9) |
| FR-PAYR-001 | Maintain salary structures including basic salary, allowances, bonuses and deductions. | Implemented | basic, housing, transport, other allowances, bonuses, deductions, staff loans (0.6) |
| FR-PAYR-002 | Calculate payroll using approved salary and attendance data. | Implemented | payroll from salary structure plus attendance (absence, overtime), unpaid leave and pro-rating for joiners/leavers (0.6) |
| FR-PAYR-003 | Support configurable statutory deductions and employer contributions. | Implemented | configurable PAYE bands, rent relief, pension, NHF, NSITF, ITF; rules stored with each run (0.6) |
| FR-PAYR-004 | Support payroll review, approval, payslips, summaries and bank export where supported. | Implemented | review, maker-checker approval, payslip PDFs, totals, bank schedule CSV, statutory remittances (0.6) |
| FR-PAYR-005 | Post approved payroll transactions to accounting and preserve restricted payroll history. | Implemented | approved payroll posts salary, employer contributions and statutory liabilities; restricted payroll history (0.6) |
| FR-MNT-001 | Maintain an asset register with identifiers, location, acquisition details, cost, warranty and status. | Implemented | asset register: code, category, location/room, serial, maker, supplier, cost, life, warranty, status; capitalisation and depreciation (0.7) |
| FR-MNT-002 | Register maintenance issues, generate work orders and assign technicians. | Implemented | fault reporting by any authorised staff (incl. from housekeeping), work orders, assignment with notifications, room blocking (0.7) |
| FR-MNT-003 | Support preventive maintenance schedules, progress tracking and completion verification. | Implemented | preventive schedules raising work orders automatically, progress notes, spare parts from stores, completion and independent verification (0.7) |
| FR-MNT-004 | Record downtime and maintenance costs and provide performance reports. | Implemented | downtime, parts/vendor/labour costs per order and asset, performance summary (0.7) |
| FR-EVT-001 | Maintain venue details, capacities and event facilities. | Implemented | venues with theatre/banquet/classroom capacities, area, rates and facilities (0.7) |
| FR-EVT-002 | Manage enquiries, bookings, dates, times, layouts, quotations, deposits and payment schedules. | Implemented | enquiry → tentative → confirmed, dates/times, layouts, quotations, deposits on the event folio (0.7) |
| FR-EVT-003 | Record catering, equipment and service requirements. | Implemented | catering, beverage, equipment, decoration, accommodation and service lines; staff allocation; direct costs (0.7) |
| FR-EVT-004 | Prevent conflicting confirmed bookings for the same venue and time. | Implemented | tentative/confirmed holds cannot overlap on a venue; capacity checked (0.7) |
| FR-EVT-005 | Generate event invoices, final bills and revenue reports. | Implemented | quotation/invoice PDF, invoicing to the event folio through the ledger, revenue & profitability summary (0.7) |
| FR-SAL-001 | Maintain corporate customer accounts and negotiated rates. | Implemented | accounts, negotiated rates, statements (0.8) |
| FR-SAL-002 | Support promotional campaigns, discount codes, sales targets and booking-source tracking. | Implemented | promo codes, source tracking (0.5); campaigns and sales targets (0.8) |
| FR-SAL-003 | Calculate ADR, RevPAR and occupancy percentage. | Implemented | revenue dashboard and reports (0.8) |
| FR-SAL-004 | Support historical performance comparisons and configurable rate plans. | Implemented | year-on-year comparison; seasons and approved occupancy rules (0.8) |
| FR-SEC-001 | Record incidents with date, time, location, category, description, persons involved and actions taken. | Implemented | incident register: time, location, category, severity, description, people, actions, police reference (0.7) |
| FR-SEC-002 | Restrict access to sensitive records and support investigation and resolution notes. | Implemented | restricted incidents (assault, harassment, flagged cases) only for security.sensitive; investigation notes and resolution (0.7) |
| FR-SEC-003 | Maintain lost-property records, emergency contacts and relevant access logs. | Implemented | lost-property register, emergency contacts, visitor/contractor log, access-control event intake and log (0.7) |
| FR-CS-001 | Register complaints with category, priority, assigned officer and status. | Implemented | complaints module (0.8) |
| FR-CS-002 | Support escalation rules and record response and resolution times. | Implemented | SLA by severity, automatic escalation, response/resolution times (0.8) |
| FR-CS-003 | Collect guest feedback and satisfaction surveys and report service quality. | Implemented | post-stay surveys and feedback reporting (0.8) |
| FR-BI-001 | Provide role-filtered dashboards for revenue, occupancy, ADR, RevPAR, rooms, reservations, cancellations, balances, expenses and departmenta | Implemented | executive dashboard; role-filtered analytics (financials need reports.financial, HR needs hr.view) (0.9) |
| FR-BI-002 | Provide daily, weekly, monthly, quarterly and annual reports. | Implemented | reports by day/week/month/quarter/year; scheduled daily/weekly/monthly reports (0.9) |
| FR-BI-003 | Support relevant filters by date, department, property and transaction. | Implemented | filters by date, property, department; transaction-level reports and exports (0.9) |
| FR-BI-004 | Export reports to PDF and spreadsheet formats. | Implemented | every report exports to PDF, Excel and CSV |
| FR-BI-005 | Compare periods and ensure financial reports use approved accounting records. | Implemented | previous period / previous year comparison; financials from posted journal entries only (0.9) |
| FR-BI-006 | Audit sensitive report exports. | Implemented | report exports are written to the audit trail (0.4) |
| FR-AI-001 | Provide an AI-assisted management interface for questions about data the user is authorised to access. | Implemented | Ask EHMS: permission-checked tools, built-in engine, optional Claude engine (0.9) |
| FR-AI-002 | Forecast room demand, revenue and occupancy from relevant historical and booking data. | Implemented | explainable pickup forecast with ranges (0.9) |
| FR-AI-003 | Identify unusual transaction patterns for human review. | Implemented | nine anomaly rules with human review queue (0.9) |
| FR-AI-004 | Recommend room-rate and inventory reorder opportunities. | Implemented | rate recommendations to proposed rules; reorder recommendations to requisitions (0.9) |
| FR-AI-005 | Analyse guest feedback and summarise recurring service issues. | Implemented | keyword sentiment & themes (0.8); assistant feedback summary with recurring issues (0.9) |
| FR-AI-006 | Explain recommendations and limitations, respect access permissions and tenant boundaries. | Implemented | methods and limitations stated; tools filtered by permission and hotel; refusals explained (0.9) |
| FR-AI-007 | Require human approval for sensitive financial, employment, cancellation and administrative decisions. | Implemented | assistant read-only; recommendations only create items awaiting approval; reviewers cannot review themselves (0.9) |
| FR-NOT-001 | Support in-application and email notifications; support SMS and WhatsApp Business where configured and available. | Implemented | in-app notification centre, email (SMTP), SMS (Termii) and WhatsApp Business Cloud API adapters (0.5) |
| FR-NOT-002 | Configure notifications by event and recipient for bookings, payments, reminders, approvals and tasks. | Implemented | templates per event and channel, on/off per event; reminders, digests and alerts by the scheduled worker (0.5) |
| FR-NOT-003 | Record delivery status where supported by the provider. | Implemented | delivery log with status, attempts and provider error; automatic retries; manual retry (0.5) |
| FR-DOC-001 | Securely upload and associate documents with guests, employees, suppliers, purchases, events and transactions. | Implemented | uploads linked to 14 record types; validation and size limits (0.9) |
| FR-DOC-002 | Apply access permissions, categorisation, retrieval and retention policies. | Implemented | record-based permissions, confidentiality levels, categories, search, retention and legal hold (0.9) |
| FR-DOC-003 | Maintain document access and modification history. | Implemented | access log incl. refused attempts; versions; integrity check (0.9) |

Non-functional highlights implemented: RBAC & scoping, MFA, lockout, session timeout/revocation, rate limiting, security headers/CSP, input validation, parameterised SQL, append-only audit trail, tamper-proof ledger, transactional integrity, automated backups with verification, OpenAPI documentation, responsive UI, automated API and browser tests.
