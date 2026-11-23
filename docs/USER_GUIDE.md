# User guide

EHMS shows each person only the menus their role allows. Amounts are entered in naira (e.g. `45000` or
`45,000.50`); the system adds service charge and taxes automatically according to the hotel's settings.

## Signing in
- Enter your email and password. After 5 wrong attempts the account locks for 15 minutes.
- If two-step verification is on, enter the 6-digit code from your authenticator app.
- You are signed out after 30 minutes of inactivity. Use **My profile & security** to change your password,
  turn on MFA and see your active sessions.

## Dashboard
Occupancy tonight, arrivals, departures, in-house guests, revenue, ADR/RevPAR, outstanding balances, room
status, open housekeeping tasks, pending approvals, a 30-day trend and a 14-day forecast. Click a room-status
tile to open the room board.

## Room board
Every room as a colour-coded tile: available (green), reserved (blue), occupied (navy), dirty (red),
cleaning (violet), cleaned/awaiting inspection (teal), maintenance (orange), out of order/service, blocked,
VIP hold. Filter by status or floor. Click a room to change its housekeeping status or take it out of service
(a reason is required; occupied rooms and rooms with future bookings cannot be blocked).

## Reservations
1. **Front desk & reservations → New reservation.**
2. Choose dates, guests, booking type (walk-in, corporate …) and source. Availability per category appears
   immediately; sold-out categories are marked.
3. Pick a category and, optionally, a room (ready rooms are listed first).
4. Select an existing guest (type to search) or create a new profile. If a similar guest exists you will be
   asked to pick it to avoid duplicates.
5. Review the price breakdown and click **Create reservation**. A confirmation email is queued for the guest.

On the reservation page you can confirm, assign or change the room, modify dates/occupants, check in, move
rooms, check out, open the folio, take a deposit, mark a no-show (from the arrival date) or cancel (reason
required). Rate overrides, discounts and overbooking appear only for authorised roles.

## Check-in
Click **Check in**, confirm the room (only clean **and inspected** rooms can be used) and record the guest's
ID where required. A folio opens automatically.

## Folio, payments and check-out
- **Post charge**: restaurant, minibar, laundry, transport, events, spa or other. Enter the price before tax.
- **Take payment**: choose the method; bank transfers and POS payments need a reference (never type card
  numbers). The amount defaults to what is due at check-out, including room nights not yet posted.
- **Reverse** a wrong charge (a reversing entry is posted; the original stays for audit) or grant an
  **Allowance** (authorised roles).
- **Request refund** when the guest is in credit — another authorised person must approve it under **Approvals**.
- **Invoice PDF** prints or saves the invoice / receipt.
- **Check out** shows the balance due; it completes only when the balance is zero. The room becomes dirty
  and a cleaning task is created.

## Night audit
At the end of the day an authorised user clicks **Run night audit**. It posts tonight's room charge to every
in-house folio, lists arrivals that did not show and overstays, creates stay-over cleaning tasks and moves the
business date forward one day.

## Housekeeping
Tasks appear in columns: To do → In progress → Awaiting inspection → Done. Housekeepers see their own tasks
(works well on a phone): **Start**, then **Complete** (report any damaged or missing items). Supervisors assign
tasks and **Inspect**: pass makes the room available; fail sends it back with a note.

## Guests
Search profiles, see stay history and lifetime spend, edit preferences, VIP flag and marketing consent.
Identification details are visible only to authorised roles.

## Availability calendar
A room-by-day chart of bookings. Navigate by period; click a booking to open it; unassigned bookings are
listed below.

## Accounting and reports
Finance users see the trial balance, profit & loss, balance sheet, journal (click an entry to see its lines),
chart of accounts and can post manual journal entries (debits must equal credits). **Reports** lists the
reports for your role; run one and export it to Excel, CSV or PDF. Release 0.4 adds restaurant & bar sales by
outlet, stock valuation, low stock / reorder list, expiring stock, stock movements and supplier payables.
Exports are recorded in the audit trail.

## Point of sale (restaurant, bar, in-room dining)
1. Choose the outlet at the top. Cashiers **Open shift** and enter the cash float before the first payment.
2. Tap a free table (green) to open an order, or use **Takeaway** / **Room service** (pick the in-house guest
   by room number or name). Tables with an open order turn gold; a green dot means food is ready to serve.
3. Tap menu items to add them (tap again to add more). Use − / + to change quantities before sending.
4. **Send to kitchen**: items appear on the kitchen display for their station. Once sent, an item can only be
   removed with **Void** (needs authorisation and a reason).
5. **Print bill** for the guest. Other actions: **Discount** (reason required), **Split bill** (move chosen
   items to a new bill), **Merge** (join another open order), **Move table**, **Void order**.
6. **Settle**: choose cash, POS card (enter the slip reference), bank transfer (enter the reference) or
   **Charge to room**; use **+ Split payment** to combine tenders. Cash can exceed the bill (change is shown);
   other tenders cannot. Settling deducts recipe ingredients from stock automatically. If an ingredient has
   run out in the issuing store the sale is refused, and nothing is charged, until stock is replenished.
7. At the end of your shift click the shift chip → **Close shift**, count the drawer and enter the amount.
   Any difference from the expected cash needs an explanation.

## Kitchen display
Tickets show the table or room, waiter and minutes since sending (amber after 10 minutes, red after 20).
Filter by station. Kitchen staff tap **Start** and **Ready**; service staff tap **Served** (on the display or
in the POS). The page refreshes every 10 seconds.

## Menu & outlets (managers)
Create categories and items (price before service charge and exclusive taxes, preparation station, and the
store ingredients are issued from, e.g. drinks from the bar store). **Recipe** lists the ingredients per
portion; the estimated cost and food-cost percentage are shown. Mark items **Sold out** when the kitchen runs
out. Outlets need an issuing store; add tables per outlet. **Cashier shifts** shows every shift and its
variance; **Kitchen performance** shows preparation times by station.

## Inventory & stores
- **Stock by store** and **Item catalogue** show quantities and values at weighted average cost; click an item
  for its balances, batches and full movement history.
- **Request stock**: ask a store for items either for a department (e.g. housekeeping toiletries) or for another
  store. A different authorised person approves; the storekeeper then **Issue stock**. Issues to a department
  are charged to that department's expense account.
- **Transfer** moves stock between stores directly. **Adjust / write off** records wastage, damage, expiry,
  corrections or opening balances, always with a reason.
- **Stock counts**: start a count for a store, enter counted quantities, **Save**, then **Post count**; balances
  are set to the counted figures and the difference is posted to Inventory Shrinkage & Wastage.
- **Alerts** lists items at or below their reorder level and batches expiring within 30 days.

## Procurement
1. **Requisitions & quotes** → **New requisition**: department, items (or a description for services),
   quantities and estimated costs. An approver approves it (not the requester).
2. Procurement records **quotations** from suppliers; the comparison highlights the cheapest price per line.
   Raise the **PO** from the chosen quotation (or at the estimate).
3. **Purchase orders** above the high-value threshold (default ₦500,000) need a senior approver; nobody can
   approve their own PO.
4. **Receive goods** against an approved PO: enter quantities received and rejected, and batch/expiry for
   expiry-tracked items. Stock increases immediately; partial deliveries are allowed.
5. **Supplier invoices** → **Record invoice**: the system compares it with the goods received. A difference
   above the tolerance is flagged and the approver must explain it. Invoices without a PO (utilities, fuel) need
   an expense account.
6. After approval, **Pay** by bank transfer or cash. Withholding tax at the supplier's rate is deducted and the
   net amount to pay is shown.
The **Overview** tab shows items awaiting approval, open orders, payables ageing and spend by supplier.

## Laundry
**Guest laundry**: pick the in-house guest, add items from the price list (or describe them), note their
condition, tick Express if needed. Move the order through each stage; record any damaged or lost item with a
note (it is not charged). **Deliver & charge room** posts the laundry charge to the guest's folio.
**Linen batch**: internal laundry for a department (no charge). The daily summary lists revenue, batches and
any lost or damaged items.

## Maintenance
**Report a fault** from the Maintenance page (any staff member with access; housekeepers can also tick "report
to maintenance" when completing a room). Tick "take the room out of sale" for vacant rooms that cannot be sold.
Maintenance managers assign technicians, raise due preventive work, and **Verify & close** completed jobs —
verification puts a blocked room back in service (dirty, with a cleaning task). Technicians **Start work**,
add notes, **Issue spare part** from a store and **Complete** with what was done. The Assets tab holds the
register, schedules, history and costs; finance posts monthly depreciation from Performance.

## Security
**Report an incident** (when, where, category, severity). Assault/harassment and flagged cases are restricted to
senior security staff. Security logs visitors and contractors (sign in / sign out), keeps the lost-and-found
register (valuables go to the safe; returns need the claimant's details and, for valuables, an ID check; items
can be disposed of or donated only after the holding period), and maintains emergency contacts.

## Events & banqueting
**New enquiry** → add venues and quotation lines → **Hold (tentative)** or **Confirm** (venue clashes and
capacity are checked; confirmation opens an event folio). Send the **Quotation PDF**, take deposits on the
folio, record direct costs and allocate staff. Finance **Invoices** the event (all lines post to the folio
with taxes and service charge); then mark it completed. Revenue & profit shows the pipeline and margins.

## Guest relations
- **Complaints**: **New complaint** (guest, category, severity, description). The deadline follows the severity
  (urgent 2 h, high 8 h, normal 24 h, low 72 h). Assign it, add updates, and resolve it with what was done and
  whether the guest was satisfied. Overdue complaints are escalated to the guest-service manager automatically.
- **Feedback**: survey answers arrive by themselves (the check-out thank-you message carries a survey link);
  record reviews from booking sites or comment cards with **Add feedback**. A rating of 2 or less opens a
  complaint automatically.
- **Insights**: average rating, NPS, recurring themes, repeat-guest rate and complaint response times.
- **Loyalty**: enrol a guest (with their agreement) from their guest profile. Points are earned when the stay
  is settled at check-out; **Redeem points** on the folio turns them into a credit.
- **Campaigns**: choose a segment (only guests who agreed to marketing are counted), preview, then send.

## Sales & revenue
- **Accounts**: corporate, travel-agent and government accounts with credit limits and negotiated rates per
  room category. When you make a corporate, travel-agent or group booking, pick the account and its rate is
  applied. Open an account to see its bookings and statement.
- **Pricing**: seasons (e.g. festive +20 %), occupancy-based rules (proposed by sales, effective only once
  finance or the GM approves) and competitor rates. The price quoted when a booking is made is locked for
  that booking.
- **Targets** show achievement against room-night and revenue targets; the **Revenue dashboard** shows the next
  30 days on the books with pickup, ADR, competitor averages and suggestions.

## Human resources
The HR manager runs all staff activity from **Human resources**:
- **Dashboard**: active staff, who is on leave today, leave and staff requests waiting, appraisals not yet
  acknowledged, and alerts (probation ending in 30 days, contracts ending in 60 days, certificates expiring,
  logins without an employee record), birthdays, anniversaries and coming public holidays.
- **Employees**: add staff (with line manager, probation and contract end dates), view the full record and edit it.
  On a profile: **Promote / transfer / pay change** (kept as job history and applied to the record), **Add training**,
  **New appraisal**, **Adjust leave**, **Give system access** (creates the login with a non-admin role and a
  temporary password), confidential records and **Record exit** (suspends the login at once). Pay and bank details
  are visible only to HR and payroll staff; confidential records only to holders of `hr.records`.
- **Leave**: Requests (approve, reject with a reason, cancel or end early — never your own), Calendar, Balances and
  Public holidays (not counted as leave days). Approved leave appears in attendance automatically.
- **Requests**: staff requests. Approving a change of details updates the record, a shift swap swaps the shifts, a
  letter is issued as a PDF, an advance or loan goes to payroll to pay. Grievances are seen only by HR managers.
- **Performance**: appraisals (rate 1–5 per criterion, strengths, improvements, goals) saved as draft, then shared.
- **Training**: everyone's training and certificates; filter those expiring in 60 days.
- **Roster** and **Attendance**: choose a shift per person per day; record present/late/absent/leave/off, times and
  overtime ("Mark rostered staff present" fills the day quickly).

## My HR (all staff)
Every employee: clock in and out; **Apply for leave** (balances shown, holidays excluded) and cancel pending or
future leave; **New request** (letter, change of details, salary advance, loan, shift swap, grievance) and withdraw
it until decided; view your profile and job history; read and **Acknowledge** appraisals; see your training,
download payslips and approved letters, and see your attendance.

## Payroll
HR prepares the month (**Prepare payroll**), adds bonuses or deductions, and recalculates after attendance
changes. Finance approves (not the preparer) — this posts the salary journal and recovers loan instalments.
Accounts records the salary payment, exports the bank schedule and records PAYE, pension, NHF and other
remittances. **Statutory rules** shows the rates in force; finance can change them.

## Cancelling and no-shows
**Cancel** and **No-show** show the fee the booking's policy applies (for example, the first night if the guest
cancels less than 24 hours before arrival). The fee is posted to the folio automatically. Managers with the right
permission can tick **Waive the fee** and give a reason. Guests can cancel online only while cancellation is free.

## Groups & blocks
**New group block**: name, dates, cut-off date, rooms per category and the group rate. Held rooms are not sold to
other guests. Open the group and **Add rooming list** (paste or upload a CSV with first_name, last_name, email,
phone, room_type, arrival, departure, adults) to create the reservations. The allotment table shows pickup;
**Release unpicked rooms** gives rooms back (this also happens automatically after the cut-off date). Choose
"Rooms to master folio" billing and **Open master folio** to bill all room nights to one account.

## Splitting bills
On a folio, **New folio (split bill)** opens a second folio for the stay (e.g. "Company account"). **Transfer
charges** moves selected charges — or part of one — to it. Every folio of the stay must be settled before check-out.

## Credit and debit notes
**Credit / debit note** on a folio raises a note for approval. A finance approver (not you) approves it under
Finance → Credit & debit notes; it is then posted to the folio with tax and service charge, and printable as PDF.
A credit on a settled folio reopens it so you can request the refund.

## Foreign-currency payments
In **Take payment**, choose the currency (only currencies with a recorded rate are offered). The amount is
converted at the day's rate and both amounts are kept. Finance records rates under Finance → Exchange rates.

## Recruitment
HR → Recruitment: create an opening, add applicants, and move them through screening, interview (record scores),
offer (salary and start date) and **Hire**, which creates the employee record and moves the CV to it.

## Insights
- **Analytics**: choose the property (or all), dates, grouping and comparison, then **Apply**. Green/red arrows show
  the change against the comparison period. Profit figures come from the general ledger and appear only if your
  role includes financial reports.
- **Forecast**: rooms already booked plus the pickup this hotel usually receives; each night shows a range. Read
  "How this forecast works" before relying on it.
- **Occupancy history**: a heat map by room category and a table per room (nights sold, revenue, out-of-order jobs).
- **Unusual transactions**: flags are prompts for a check, not accusations. Open one, look at the record, and
  close it with **Dismiss — explained** or **Confirm issue** and a note. You cannot review a flag about yourself.
- **Recommendations**: suggested rate changes (turn into a pricing rule that someone else must approve) and items
  to reorder (tick them and **Raise requisition** — it goes for normal approval).
- **Scheduled reports**: pick a report, frequency, format and recipients (only people allowed to see that report
  are listed). Files appear in **Documents** and recipients get a notification.

## Ask EHMS
Type a question such as "How full are we tonight?", "What was revenue last month?", "What do guests complain
about?" or "What needs reordering?". Answers use only data your role may see and name their source. The assistant
cannot approve, refund, cancel or change anything — it tells you where to do that.

## Documents
Every guest, employee, supplier, reservation and event has a **Documents** section; **Upload** a PDF, image, Word,
Excel, CSV or text file (up to 10 MB). Identity, medical, HR and employee files are confidential by default — you
may be able to file them without being able to open them afterwards. Open a document to download it, upload a
new version, and see who viewed or downloaded it. The **Documents** page searches across the hotel; managers also
see documents past their retention date and the activity log.

## Notifications
The bell at the top right shows your in-app notifications (for example "order ready" for waiters, low-stock
digests for inventory managers, supplier invoices due for accountants). Click one to mark it read.

## Online payment links
On a folio, **Payment link** creates a secure Paystack/Flutterwave link for any amount and emails it to the
guest. The payment appears on the folio automatically once the provider confirms it.

## Finance operations
- **Expense claims**: submit a claim with the account, amount and receipt number; an approver (not you) approves;
  the accountant pays it from cash or bank.
- **Bank reconciliation**: choose the bank (or card/online clearing) account, import the statement CSV, click
  **Auto-match**, then match or ignore the rest. The difference must be zero.
- **Budget vs actual**, **Cash flow** and **Periods** (close a month once its books are final).
- **Online payments**: every gateway transaction and the integration log; **Re-check** a pending payment.

## Booking engine (guests)
Share `https://<your-domain>/#/book/<HOTEL_CODE>`. Guests check availability, see the full price including
taxes, enter a promo code, book with "pay at hotel" or (when a gateway is configured) **pay now online** —
prepaid bookings are confirmed automatically — and can look up or cancel their booking with the reference and email. Online
bookings arrive as **tentative** for staff to confirm.

## New in 1.2
- **Language**: click your name (top right) → Language → English or Français.
- **Breadcrumb and Help**: the line above each page title shows where you are; *Help & support* (under your name or at
  the bottom of the menu) explains the screens you can use.
- **Wake-up calls**: on a booking, *Wake-up call* → date and time. Front desk & reservations → *Wake-up calls* lists the
  day's calls; mark each *Done* or *No answer*. You get a reminder 10 minutes before.
- **Early check-in / late check-out**: on the booking, the button posts the fee from Hotel settings to the folio.
- **Registration card**: on the booking, *Registration card* opens a PDF for the guest to sign.
- **Assign rooms by dragging**: Room board → drag a guest from *Arrivals without a room* onto a free room (or click the
  guest, then the room).
- **Table bookings**: Point of sale → *Table bookings* → New booking; seat, complete, cancel or mark no-show.
- **Returns to suppliers**: Procurement → *Goods received & returns* → open the GRN → enter quantities and the reason.
- **Referrals**: a guest's profile shows their referral code; new guests enter it on the booking engine or the front
  desk records it on the booking. Points reach the referrer after the new guest checks out.
- **Petty cash**: Finance operations → Petty cash → *Pay out* (custodian) or *Top up* (finance); *Voucher* prints a
  payment voucher. Paid expense claims and supplier payments also have a *Voucher* button.
- **Welfare** (HR managers): an employee's profile → *Record support*; Human resources → Welfare lists the year.
- **Insights**: Daily summary, Cancellation risk, Equipment failures and Guest insights tabs.
- **Backups** (IT administrator): Administration → Backups.

