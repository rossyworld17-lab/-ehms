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
- Roles for modules not yet released (restaurant, stores, HR …) currently carry dashboard access only.

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
