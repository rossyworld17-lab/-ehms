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
reports for your role; run one and export it to Excel, CSV or PDF.

## Booking engine (guests)
Share `https://<your-domain>/#/book/<HOTEL_CODE>`. Guests check availability, see the full price including
taxes, book with "pay at hotel", and can look up or cancel their booking with the reference and email. Online
bookings arrive as **tentative** for staff to confirm.
