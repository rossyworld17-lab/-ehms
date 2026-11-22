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

## Booking engine (guests)
Share `https://<your-domain>/#/book/<HOTEL_CODE>`. Guests check availability, see the full price including
taxes, book with "pay at hotel", and can look up or cancel their booking with the reference and email. Online
bookings arrive as **tentative** for staff to confirm.
