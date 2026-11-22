"""Communication centre: notification templates per event and channel, in-app notifications for staff,
delivery history with failed-message tracking and retry. (FR-NOT-001..003, section 23)"""
from __future__ import annotations

from collections import defaultdict

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route
from ..services import queue_notification

# code: (description, {channel: (subject, body)}) — placeholders in {braces}; unknown ones render empty
DEFAULT_TEMPLATES: dict[str, tuple[str, dict[str, tuple[str, str]]]] = {
    "booking_received": ("Online booking received", {
        "email": ("Booking received {reference} — {hotel}", "Dear {guest},\n\nThank you for booking with {hotel}. Your reference is {reference}.\n"
                  "Arrival {arrival}, departure {departure}, {room_type}.\nTotal: {total}.\n\n{hotel}")}),
    "checkin_reminder": ("Day-before arrival reminder", {
        "email": ("See you tomorrow at {hotel}", "Dear {guest},\n\nWe look forward to welcoming you tomorrow ({arrival}). Check-in is from {checkin_time}. "
                  "Please bring a valid ID.\nReservation: {reference}\n\n{hotel}"),
        "sms": ("", "{hotel}: we look forward to welcoming you tomorrow. Check-in from {checkin_time}. Ref {reference}."),
        "whatsapp": ("", "Hello {guest}, {hotel} looks forward to welcoming you tomorrow ({arrival}). Check-in is from {checkin_time}. Ref {reference}.")}),
    "checkout_thanks": ("Post check-out thank-you", {
        "email": ("Thank you for staying at {hotel}", "Dear {guest},\n\nThank you for staying with us. We hope to welcome you again soon.\n\n{hotel}")}),
    "payment_link": ("Online payment link", {
        "email": ("Payment request from {hotel}", "Please use the secure link below to pay {amount} for {folio}:\n{link}\n\n{hotel}"),
        "sms": ("", "{hotel}: pay {amount} securely here: {link}")}),
    "birthday": ("Guest birthday greeting (consenting guests)", {
        "email": ("Happy birthday from {hotel}", "Dear {guest},\n\nEveryone at {hotel} wishes you a very happy birthday!\n\n{hotel}")}),
    "order_ready": ("Kitchen order ready (staff)", {"in_app": ("Order ready", "{item} ready for {where}")}),
    "low_stock_digest": ("Daily low-stock digest (staff)", {"in_app": ("Low stock", "{count} item(s) are at or below their reorder level: {items}")}),
    "invoices_due": ("Supplier invoices due soon (staff)", {"in_app": ("Supplier invoices due", "{count} approved supplier invoice(s) are due within 3 days, total {total}.")}),
}


class _Safe(dict):
    def __missing__(self, key):
        return ""


def render(text: str, context: dict) -> str:
    try:
        return (text or "").format_map(_Safe({k: ("" if v is None else v) for k, v in context.items()}))
    except (ValueError, IndexError):
        return text or ""


def templates_for(c, hotel_id: int, code: str) -> dict[str, dict]:
    """Effective templates for an event: hotel overrides on top of the built-in defaults."""
    out = {ch: {"subject": s, "body": b, "active": 1} for ch, (s, b) in DEFAULT_TEMPLATES.get(code, ("", {}))[1].items()}
    for t in c.all("SELECT * FROM notification_templates WHERE hotel_id = ? AND code = ?", [hotel_id, code]):
        out[t["channel"]] = {"subject": t["subject"], "body": t["body"], "active": t["active"]}
    return out


def notify_template(c, hotel: dict, code: str, recipients: dict, context: dict, entity: str | None = None, entity_id=None) -> list[int]:
    """Queue one message per active channel that has a recipient (email, phone for sms/whatsapp, user_id for in_app)."""
    ctx = {"hotel": hotel["name"], "checkin_time": hotel.get("check_in_time"), **context}
    ids = []
    target = {"email": recipients.get("email"), "sms": recipients.get("phone"), "whatsapp": recipients.get("phone"),
              "in_app": str(recipients["user_id"]) if recipients.get("user_id") else None}
    for ch, t in templates_for(c, hotel["id"], code).items():
        if not t["active"] or not target.get(ch):
            continue
        nid = queue_notification(c, hotel["id"], ch, target[ch], render(t["subject"], ctx)[:200], render(t["body"], ctx), entity, entity_id)
        if nid:
            ids.append(nid)
    return ids


# ------------------------------------------------------------------ in-app notifications (any signed-in user)
@route("GET", "/api/notifications/mine", tag="messaging", summary="My in-app notifications (latest 50) and unread count")
def my_notifications(ctx: Ctx):
    with get_db().tx() as c:
        rows = c.all("SELECT id, hotel_id, subject, body, related_entity, related_id, created_at, read_at FROM notifications "
                     "WHERE channel = 'in_app' AND recipient = ? ORDER BY id DESC LIMIT 50", [str(ctx.user_id)])
        unread = c.scalar("SELECT COUNT(*) FROM notifications WHERE channel = 'in_app' AND recipient = ? AND read_at IS NULL", [str(ctx.user_id)])
    return {"items": rows, "unread": unread}


@route("POST", "/api/notifications/{notification_id:int}/read", tag="messaging", summary="Mark one of my notifications as read")
def mark_read(ctx: Ctx):
    with get_db().tx() as c:
        n = c.one("SELECT * FROM notifications WHERE id = ? AND channel = 'in_app' AND recipient = ?", [ctx.path["notification_id"], str(ctx.user_id)])
        if not n:
            raise not_found("Notification")
        c.execute("UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL", [now_iso(), n["id"]])
    return {"ok": True}


@route("POST", "/api/notifications/read-all", tag="messaging", summary="Mark all my notifications as read")
def mark_all_read(ctx: Ctx):
    with get_db().tx() as c:
        c.execute("UPDATE notifications SET read_at = ? WHERE channel = 'in_app' AND recipient = ? AND read_at IS NULL", [now_iso(), str(ctx.user_id)])
    return {"ok": True}


# ------------------------------------------------------------------ administration
@route("GET", "/api/hotels/{hotel_id:int}/notification-templates", perm="admin.notifications.manage", tag="messaging",
       summary="Notification templates per event and channel (built-in defaults plus hotel overrides)")
def list_templates(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    from ..notify import provider_for
    with get_db().tx() as c:
        items = []
        for code, (desc, _) in DEFAULT_TEMPLATES.items():
            for ch, t in templates_for(c, hid, code).items():
                items.append({"code": code, "description": desc, "channel": ch, **t, "provider_configured": provider_for(ch)})
    return {"items": items}


@route("PUT", "/api/hotels/{hotel_id:int}/notification-templates", perm="admin.notifications.manage", tag="messaging",
       summary="Save a template (code, channel, subject, body, active)")
def save_template(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    code, ch = ctx.field("code", kind=str), ctx.field("channel", kind=str)
    if code not in DEFAULT_TEMPLATES:
        raise bad_request("Unknown notification event")
    if ch not in ("email", "sms", "whatsapp", "in_app"):
        raise bad_request("Unknown channel")
    body = ctx.field("body", kind=str)
    subject = ctx.field("subject", required=False, default="", kind=str)
    active = 1 if ctx.field("active", required=False, default=True) else 0
    with get_db().tx() as c:
        row = c.one("SELECT * FROM notification_templates WHERE hotel_id = ? AND code = ? AND channel = ?", [hid, code, ch])
        data = {"subject": subject, "body": body, "active": active, "updated_by": ctx.user_id, "updated_at": now_iso()}
        if row:
            c.update("notification_templates", row["id"], data)
        else:
            c.insert("notification_templates", {"hotel_id": hid, "code": code, "channel": ch, **data})
        audit(c, ctx, "template.saved", "notification_template", f"{code}/{ch}", code, old=row, new=data, hotel_id=hid)
    return {"ok": True}


@route("GET", "/api/hotels/{hotel_id:int}/notifications", perm="admin.notifications.manage", tag="messaging",
       summary="Delivery history (?status=queued|sent|failed|not_configured, ?channel)")
def delivery_log(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    sql, params = "SELECT * FROM notifications WHERE hotel_id = ? AND channel <> 'in_app'", [hid]
    for k in ("status", "channel"):
        if ctx.q(k):
            sql += f" AND {k} = ?"
            params.append(ctx.q(k))
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY id DESC LIMIT 300", params)
        counts = {r["status"]: r["n"] for r in c.all("SELECT status, COUNT(*) AS n FROM notifications WHERE hotel_id = ? AND channel <> 'in_app' "
                                                     "GROUP BY status", [hid])}
    return {"items": rows, "counts": counts}


@route("POST", "/api/notifications/{notification_id:int}/retry", perm="admin.notifications.manage", tag="messaging",
       summary="Re-queue a failed or not-configured message (once its provider is configured)")
def retry(ctx: Ctx):
    from ..notify import provider_for
    with get_db().tx() as c:
        n = c.one("SELECT * FROM notifications WHERE id = ?", [ctx.path["notification_id"]])
        if not n or n["channel"] == "in_app":
            raise not_found("Message")
        ctx.check_hotel(n["hotel_id"])
        if n["status"] not in ("failed", "not_configured"):
            raise conflict("Only failed or not-configured messages can be retried")
        if not provider_for(n["channel"]):
            raise conflict(f"No {n['channel']} provider is configured yet")
        c.execute("UPDATE notifications SET status = 'queued', error = NULL, attempts = 0 WHERE id = ?", [n["id"]])
        audit(c, ctx, "notification.retry", "notification", n["id"], hotel_id=n["hotel_id"])
    return {"ok": True}


@route("POST", "/api/hotels/{hotel_id:int}/notifications/run-jobs", perm="admin.notifications.manage", tag="messaging",
       summary="Run scheduled jobs now (reminders, digests) and deliver queued messages")
def run_jobs_now(ctx: Ctx):
    ctx.check_hotel(ctx.path["hotel_id"])
    from ..worker import run_once
    return run_once()
