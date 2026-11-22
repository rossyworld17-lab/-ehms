"""Shared domain services: numbering, business dates, tax calculation and double-entry posting."""
from __future__ import annotations

import datetime as dt
from typing import Iterable

from .db import Connection, now_iso
from .http import ApiError, bad_request, not_found

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore


# ------------------------------------------------------------------ dates
def parse_date(value: str, field: str = "date") -> dt.date:
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        raise bad_request(f"'{field}' must be a date in YYYY-MM-DD format", {"field": field})


def hotel_today(hotel: dict) -> dt.date:
    try:
        tz = ZoneInfo(hotel.get("timezone") or "Africa/Lagos") if ZoneInfo else None
    except Exception:
        tz = None
    now = dt.datetime.now(tz) if tz else dt.datetime.now(dt.timezone(dt.timedelta(hours=1)))
    return now.date()


def business_date(hotel: dict) -> dt.date:
    """The hotel's operational date. Set by night audit; falls back to today's date in the hotel's time zone."""
    if hotel.get("business_date"):
        return dt.date.fromisoformat(str(hotel["business_date"])[:10])
    return hotel_today(hotel)


def get_hotel(c: Connection, hotel_id: int) -> dict:
    h = c.one("SELECT * FROM hotels WHERE id = ?", [hotel_id])
    if not h:
        raise not_found("Hotel")
    return h


def nights_between(a: dt.date, b: dt.date) -> list[dt.date]:
    return [a + dt.timedelta(days=i) for i in range((b - a).days)]


# ------------------------------------------------------------------ numbering
def next_number(c: Connection, hotel_id: int, name: str, prefix: str, width: int = 6) -> str:
    row = c.one("SELECT id, next_value FROM sequences WHERE hotel_id = ? AND name = ?", [hotel_id, name])
    if row is None:
        c.insert("sequences", {"hotel_id": hotel_id, "name": name, "next_value": 1})
        row = c.one("SELECT id, next_value FROM sequences WHERE hotel_id = ? AND name = ?", [hotel_id, name])
    if c.dialect == "postgresql":
        row = c.one("SELECT id, next_value FROM sequences WHERE id = ? FOR UPDATE", [row["id"]])
    value = row["next_value"]
    c.execute("UPDATE sequences SET next_value = next_value + 1 WHERE id = ?", [row["id"]])
    hotel_code = c.scalar("SELECT code FROM hotels WHERE id = ?", [hotel_id]) or str(hotel_id)
    return f"{prefix}-{hotel_code}-{str(value).zfill(width)}"


# ------------------------------------------------------------------ money & tax
def to_minor(value, field: str = "amount") -> int:
    """Accepts integers in minor units. Rejects floats to avoid rounding errors."""
    if isinstance(value, bool):
        raise bad_request(f"'{field}' must be an integer amount in minor units (kobo)")
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().lstrip("-").isdigit():
        return int(value)
    raise bad_request(f"'{field}' must be an integer amount in minor units (kobo)", {"field": field})


def _round_div(a: int, b: int) -> int:
    """Integer division rounded half-up (for non-negative a)."""
    return (a * 2 + b) // (b * 2)


def applicable_taxes(c: Connection, hotel_id: int, department: str, on: dt.date) -> list[dict]:
    return c.all(
        "SELECT * FROM tax_rules WHERE hotel_id = ? AND active = 1 AND (applies_to = 'all' OR applies_to = ?) "
        "AND effective_from <= ? AND (effective_to IS NULL OR effective_to >= ?) ORDER BY id",
        [hotel_id, department, on.isoformat(), on.isoformat()])


SERVICE_CHARGE_DEPARTMENTS = {"room", "fnb"}


def price_breakdown(c: Connection, hotel: dict, department: str, amount: int, on: dt.date) -> dict:
    """Split a charge into net, tax and service charge using configured rules.

    Exclusive taxes are added on top of the net amount; inclusive taxes are backed out of it.
    Service charge (if configured for the hotel) applies to room and F&B net revenue.
    """
    taxes = applicable_taxes(c, hotel["id"], department, on)
    inclusive_bp = sum(t["rate_bp"] for t in taxes if t["is_inclusive"])
    exclusive_bp = sum(t["rate_bp"] for t in taxes if not t["is_inclusive"])
    net = _round_div(amount * 10000, 10000 + inclusive_bp) if inclusive_bp else amount
    inclusive_tax = amount - net
    sc_bp = hotel.get("service_charge_bp") or 0 if department in SERVICE_CHARGE_DEPARTMENTS else 0
    service = _round_div(net * sc_bp, 10000) if sc_bp else 0
    exclusive_tax = _round_div((net + service) * exclusive_bp, 10000) if exclusive_bp else 0
    tax = inclusive_tax + exclusive_tax
    return {"net": net, "tax": tax, "service_charge": service, "total": net + service + tax,
            "taxes": [{"code": t["code"], "name": t["name"], "rate_bp": t["rate_bp"], "inclusive": bool(t["is_inclusive"])} for t in taxes]}


# ------------------------------------------------------------------ accounting
REVENUE_KEYS = {"room": "rev_room", "fnb": "rev_fnb", "laundry": "rev_laundry", "minibar": "rev_fnb",
                "events": "rev_events", "transport": "rev_other", "spa": "rev_other", "other": "rev_other"}

DEFAULT_ACCOUNTS = [
    # code, name, type, system_key
    ("1000", "Cash on Hand", "asset", "cash"),
    ("1010", "Bank - Main Account", "asset", "bank"),
    ("1020", "POS Card Clearing", "asset", "card_clearing"),
    ("1030", "Online Payments Clearing", "asset", "online_clearing"),
    ("1100", "Guest Ledger (In-house Receivables)", "asset", "guest_ledger"),
    ("1110", "City Ledger (Corporate Receivables)", "asset", "city_ledger"),
    ("1200", "Inventory", "asset", "inventory"),
    ("2000", "Accounts Payable", "liability", "ap"),
    ("2010", "Goods Received Not Invoiced", "liability", "grni"),
    ("2100", "VAT Payable", "liability", "vat_payable"),
    ("2110", "Service Charge Payable", "liability", "service_charge_payable"),
    ("2120", "Withholding Tax Payable", "liability", "wht_payable"),
    ("2200", "Advance Deposits", "liability", "advance_deposits"),
    ("3000", "Owner's Equity", "equity", "equity"),
    ("3100", "Retained Earnings", "equity", "retained_earnings"),
    ("4000", "Room Revenue", "revenue", "rev_room"),
    ("4100", "Food & Beverage Revenue", "revenue", "rev_fnb"),
    ("4200", "Laundry Revenue", "revenue", "rev_laundry"),
    ("4300", "Events & Conference Revenue", "revenue", "rev_events"),
    ("4900", "Other Operating Revenue", "revenue", "rev_other"),
    ("4950", "Allowances & Rebates", "revenue", "allowances"),
    ("5000", "Salaries & Wages", "expense", "exp_salaries"),
    ("5100", "Utilities", "expense", "exp_utilities"),
    ("5200", "Fuel & Power", "expense", "exp_fuel"),
    ("5300", "Food Supplies", "expense", "exp_food"),
    ("5310", "Cost of Food & Beverage Sold", "expense", "cogs_fnb"),
    ("5320", "Housekeeping & Guest Supplies", "expense", "exp_supplies"),
    ("5400", "Repairs & Maintenance", "expense", "exp_maintenance"),
    ("5500", "Marketing", "expense", "exp_marketing"),
    ("5600", "Security", "expense", "exp_security"),
    ("5900", "General & Administrative", "expense", "exp_admin"),
    ("5950", "Inventory Shrinkage & Wastage", "expense", "inv_variance"),
    ("5960", "Purchase Price Variance", "expense", "ppv"),
]

# Expense account used when stock is issued to (consumed by) a department.
DEPARTMENT_EXPENSE_KEYS = {"kitchen": "exp_food", "fnb": "exp_food", "bar": "exp_food", "housekeeping": "exp_supplies",
                           "laundry": "exp_supplies", "front_office": "exp_admin", "maintenance": "exp_maintenance",
                           "security": "exp_security", "admin": "exp_admin", "marketing": "exp_marketing", "other": "exp_admin"}
EXPENSE_KEYS = ("exp_salaries", "exp_utilities", "exp_fuel", "exp_food", "exp_supplies", "exp_maintenance", "exp_marketing",
                "exp_security", "exp_admin")


def hotel_setting(c: Connection, hotel_id: int, key: str, default: str | None = None) -> str | None:
    v = c.scalar("SELECT value FROM system_settings WHERE hotel_id = ? AND key = ?", [hotel_id, key])
    return default if v is None else v


def set_hotel_setting(c: Connection, hotel_id: int, key: str, value: str) -> None:
    if c.one("SELECT id FROM system_settings WHERE hotel_id = ? AND key = ?", [hotel_id, key]):
        c.execute("UPDATE system_settings SET value = ? WHERE hotel_id = ? AND key = ?", [value, hotel_id, key])
    else:
        c.execute("INSERT INTO system_settings (hotel_id, key, value) VALUES (?, ?, ?)", [hotel_id, key, value])


# ------------------------------------------------------------------ quantities
def to_milli(value, field: str = "quantity", allow_zero: bool = False) -> int:
    """Convert a decimal quantity (number or string, up to 3 decimals) to integer thousandths."""
    import decimal
    if isinstance(value, bool) or value in (None, ""):
        raise bad_request(f"'{field}' is required", {"field": field})
    try:
        d = decimal.Decimal(str(value).strip())
    except decimal.InvalidOperation:
        raise bad_request(f"'{field}' must be a number", {"field": field})
    if d != d.quantize(decimal.Decimal("0.001")):
        raise bad_request(f"'{field}' allows at most 3 decimal places", {"field": field})
    m = int(d * 1000)
    if m < 0 or (m == 0 and not allow_zero):
        raise bad_request(f"'{field}' must be greater than zero", {"field": field})
    return m


def from_milli(m: int | None) -> float:
    return 0.0 if m is None else m / 1000



def seed_chart_of_accounts(c: Connection, organisation_id: int) -> None:
    for code, name, typ, key in DEFAULT_ACCOUNTS:
        if not c.one("SELECT id FROM accounts WHERE organisation_id = ? AND code = ?", [organisation_id, code]):
            c.insert("accounts", {"organisation_id": organisation_id, "code": code, "name": name, "type": typ, "system_key": key})


def account_id(c: Connection, organisation_id: int, key: str) -> int:
    aid = c.scalar("SELECT id FROM accounts WHERE organisation_id = ? AND system_key = ? AND active = 1", [organisation_id, key])
    if not aid:
        raise ApiError(500, "account_missing", f"System account '{key}' is not configured in the chart of accounts")
    return int(aid)


def post_journal(c: Connection, hotel_id: int, entry_date: dt.date | str, description: str, source: str,
                 source_ref: str | None, lines: Iterable[tuple], user_id: int | None, reversal_of: int | None = None) -> int:
    """Post a balanced journal entry. lines: (account_id, debit, credit, department, memo)."""
    lines = [l for l in lines if (l[1] or 0) > 0 or (l[2] or 0) > 0]
    if not lines:
        raise bad_request("A journal entry needs at least one non-zero line")
    total_dr = sum(int(l[1] or 0) for l in lines)
    total_cr = sum(int(l[2] or 0) for l in lines)
    if total_dr != total_cr:
        raise bad_request(f"Journal entry is not balanced (debits {total_dr} vs credits {total_cr})")
    period = str(entry_date)[:7]
    if c.one("SELECT id FROM accounting_periods WHERE hotel_id = ? AND period = ? AND status = 'closed'", [hotel_id, period]):
        raise ApiError(409, "period_closed", f"The accounting period {period} is closed; post in an open period or ask finance to reopen it")
    number = next_number(c, hotel_id, "journal", "JE")
    entry_id = c.insert("journal_entries", {
        "hotel_id": hotel_id, "number": number, "entry_date": str(entry_date), "description": description[:300],
        "source": source, "source_ref": source_ref, "reversal_of": reversal_of, "created_by": user_id, "created_at": now_iso()})
    for acc, dr, cr, dept, memo in lines:
        c.insert("journal_lines", {"entry_id": entry_id, "account_id": acc, "debit": int(dr or 0), "credit": int(cr or 0),
                                   "department": dept, "memo": (memo or "")[:300]})
    return entry_id


def reverse_journal(c: Connection, entry_id: int, entry_date: dt.date | str, reason: str, user_id: int | None) -> int:
    je = c.one("SELECT * FROM journal_entries WHERE id = ?", [entry_id])
    if not je:
        raise not_found("Journal entry")
    if c.one("SELECT id FROM journal_entries WHERE reversal_of = ?", [entry_id]):
        raise bad_request("This journal entry has already been reversed")
    lines = c.all("SELECT * FROM journal_lines WHERE entry_id = ?", [entry_id])
    return post_journal(c, je["hotel_id"], entry_date, f"Reversal of {je['number']}: {reason}", "reversal", je["number"],
                        [(l["account_id"], l["credit"], l["debit"], l["department"], l["memo"]) for l in lines], user_id, reversal_of=entry_id)


# ------------------------------------------------------------------ notifications
def queue_notification(c: Connection, hotel_id: int | None, channel: str, recipient: str | None, subject: str, body: str,
                       entity: str | None = None, entity_id=None) -> int | None:
    """Records an outgoing message. Without a configured provider the message is stored as
    'not_configured' — the system never reports a message as sent when it was not."""
    if not recipient:
        return None
    from .notify import provider_for
    status, err = ("queued", None) if provider_for(channel) else ("not_configured", f"No {channel} provider configured")
    return c.insert("notifications", {"hotel_id": hotel_id, "channel": channel, "recipient": recipient, "subject": subject,
                                      "body": body, "status": status, "error": err, "related_entity": entity,
                                      "related_id": None if entity_id is None else str(entity_id), "created_at": now_iso()})
