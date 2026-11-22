"""Perpetual stock ledger shared by inventory, POS (recipe consumption) and procurement (goods received).

Valuation is weighted average cost per item per store. Each stock level carries both a quantity and a
carrying value, so the inventory sub-ledger always reconciles exactly to the Inventory GL account:
an outflow removes value in proportion to the quantity removed (all of it when the store is emptied).
Batches are depleted first-expiry-first-out (FEFO) for expiry tracking. Every change writes an
append-only stock_movements row (protected by database triggers)."""
from __future__ import annotations

import datetime as dt

from .db import Connection, now_iso
from .http import bad_request, conflict, not_found


def _round_div(a: int, b: int) -> int:
    q, r = divmod(abs(a), b)
    q += 1 if r * 2 >= b else 0
    return q if a >= 0 else -q


def get_item(c: Connection, hotel_id: int, item_id) -> dict:
    it = c.one("SELECT * FROM inventory_items WHERE id = ? AND hotel_id = ?", [int(item_id), hotel_id])
    if not it:
        raise not_found("Inventory item")
    return it


def get_store(c: Connection, hotel_id: int, store_id) -> dict:
    st = c.one("SELECT * FROM stores WHERE id = ? AND hotel_id = ?", [int(store_id), hotel_id])
    if not st:
        raise not_found("Store")
    if not st["active"]:
        raise bad_request(f"Store {st['name']} is inactive")
    return st


def level(c: Connection, item_id: int, store_id: int, lock: bool = False) -> dict:
    row = c.one("SELECT * FROM stock_levels WHERE item_id = ? AND store_id = ?", [item_id, store_id])
    if row is None:
        c.insert("stock_levels", {"item_id": item_id, "store_id": store_id, "quantity_milli": 0, "value": 0})
        row = c.one("SELECT * FROM stock_levels WHERE item_id = ? AND store_id = ?", [item_id, store_id])
    if lock and c.dialect == "postgresql":
        row = c.one("SELECT * FROM stock_levels WHERE id = ? FOR UPDATE", [row["id"]])
    return row


def outflow_value(c: Connection, item: dict, store: dict, qty_milli: int) -> int:
    """Carrying value that removing qty_milli would take out of the store (positive number).
    Raises if stock is insufficient and the store does not allow negative balances."""
    lv = level(c, item["id"], store["id"], lock=True)
    have = lv["quantity_milli"]
    if qty_milli > have and not store["allow_negative"]:
        raise conflict(f"Not enough {item['name']} in {store['name']}: {have / 1000:g} {item['unit']} available, "
                       f"{qty_milli / 1000:g} needed", {"code": "insufficient_stock", "item_id": item["id"], "available": have / 1000})
    if have <= 0:
        return _round_div(item["last_cost"] * qty_milli, 1000)
    if qty_milli >= have:
        extra = qty_milli - have
        return lv["value"] + _round_div(lv["value"] * extra, have)
    return _round_div(lv["value"] * qty_milli, have)


def apply_movement(c: Connection, hotel_id: int, item: dict, store: dict, movement_type: str, qty_milli: int, value: int | None,
                   source: str, source_ref: str | None, user_id: int | None, on: dt.date, *, department: str | None = None,
                   reason: str | None = None, batch_no: str | None = None, expiry_date: str | None = None,
                   journal_entry_id: int | None = None) -> tuple[int, int]:
    """Record a signed stock movement. For outflows (qty < 0) pass value=None to use the carrying value.
    Returns (movement_id, signed value)."""
    if qty_milli == 0:
        raise bad_request("Quantity cannot be zero")
    if qty_milli < 0:
        out_val = outflow_value(c, item, store, -qty_milli) if value is None else abs(value)
        value = -out_val
    elif value is None or value < 0:
        raise bad_request("Incoming stock needs a non-negative value")
    lv = level(c, item["id"], store["id"], lock=True)
    new_qty = lv["quantity_milli"] + qty_milli
    new_val = lv["value"] + value
    if new_qty == 0:
        new_val = 0 if abs(new_val) <= 1 else new_val
    c.execute("UPDATE stock_levels SET quantity_milli = ?, value = ? WHERE id = ?", [new_qty, new_val, lv["id"]])
    # batches (FEFO)
    if qty_milli > 0:
        c.insert("stock_batches", {"item_id": item["id"], "store_id": store["id"], "batch_no": batch_no, "expiry_date": expiry_date,
                                   "quantity_milli": qty_milli, "received_at": now_iso()})
    else:
        need = -qty_milli
        for b in c.all("SELECT * FROM stock_batches WHERE item_id = ? AND store_id = ? AND quantity_milli > 0 "
                       "ORDER BY CASE WHEN expiry_date IS NULL THEN 1 ELSE 0 END, expiry_date, received_at, id", [item["id"], store["id"]]):
            if need <= 0:
                break
            take = min(need, b["quantity_milli"])
            c.execute("UPDATE stock_batches SET quantity_milli = quantity_milli - ? WHERE id = ?", [take, b["id"]])
            need -= take
    if qty_milli > 0 and value:
        unit = _round_div(value * 1000, qty_milli)
        if movement_type in ("receipt", "opening"):
            c.execute("UPDATE inventory_items SET last_cost = ? WHERE id = ?", [unit, item["id"]])
    mid = c.insert("stock_movements", {
        "hotel_id": hotel_id, "item_id": item["id"], "store_id": store["id"], "movement_type": movement_type, "quantity_milli": qty_milli,
        "value": value, "balance_milli": new_qty, "balance_value": new_val, "source": source, "source_ref": source_ref,
        "department": department, "reason": (reason or "")[:300] or None, "batch_no": batch_no, "expiry_date": expiry_date,
        "journal_entry_id": journal_entry_id, "business_date": on.isoformat(), "created_by": user_id, "created_at": now_iso()})
    return mid, value
