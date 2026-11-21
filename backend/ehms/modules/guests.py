"""Guest profiles and history (CRM foundation). (FR-CRM-001..003, FR-RES-006 duplicate detection)"""
from __future__ import annotations

from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, conflict, not_found, route

GUEST_FIELDS = ("first_name", "last_name", "email", "phone", "nationality", "address", "date_of_birth", "id_type", "id_number",
                "company", "preferences", "vip", "marketing_consent", "notes")
SENSITIVE = ("id_type", "id_number", "date_of_birth", "address")


def mask(ctx: Ctx, g: dict) -> dict:
    g = dict(g)
    if not ctx.can("guests.identity.view"):
        for f in SENSITIVE:
            if g.get(f):
                g[f] = "•••• restricted"
    g["vip"] = bool(g.get("vip"))
    g["marketing_consent"] = bool(g.get("marketing_consent"))
    return g


def find_duplicates(c, org_id: int, first: str, last: str, email: str | None, phone: str | None, exclude: int | None = None) -> list[dict]:
    conds, params = [], [org_id]
    if email:
        conds.append("lower(email) = ?")
        params.append(email.lower())
    if phone:
        conds.append("phone = ?")
        params.append(phone)
    conds.append("(lower(first_name) = ? AND lower(last_name) = ?)")
    params += [first.lower(), last.lower()]
    sql = f"SELECT id, first_name, last_name, email, phone FROM guests WHERE organisation_id = ? AND ({' OR '.join(conds)})"
    if exclude:
        sql += " AND id <> ?"
        params.append(exclude)
    return c.all(sql + " LIMIT 5", params)


def create_guest_row(c, ctx: Ctx, data: dict) -> int:
    for f in ("first_name", "last_name"):
        if not str(data.get(f) or "").strip():
            raise bad_request(f"'{f}' is required", {"field": f})
    row = {f: data.get(f) for f in GUEST_FIELDS if data.get(f) not in (None, "")}
    row["vip"] = 1 if data.get("vip") else 0
    row["marketing_consent"] = 1 if data.get("marketing_consent") else 0
    if row.get("email"):
        row["email"] = row["email"].strip().lower()
    gid = c.insert("guests", {"organisation_id": ctx.org_id, "created_at": now_iso(), **row})
    audit(c, ctx, "guest.created", "guest", gid, f"{row['first_name']} {row['last_name']}")
    return gid


@route("GET", "/api/guests", perm="guests.view", tag="guests", summary="Search guests by name, email, phone or company")
def list_guests(ctx: Ctx):
    s = (ctx.q("search") or "").strip().lower()
    sql = ("SELECT g.*, (SELECT COUNT(*) FROM reservations r WHERE r.guest_id = g.id AND r.status = 'checked_out') AS stays "
           "FROM guests g WHERE g.organisation_id = ?")
    params: list = [ctx.org_id]
    if s:
        sql += (" AND (lower(g.first_name || ' ' || g.last_name) LIKE ? OR lower(g.email) LIKE ? OR g.phone LIKE ? OR lower(g.company) LIKE ?)")
        params += [f"%{s}%"] * 4
    if ctx.q("vip") == "1":
        sql += " AND g.vip = 1"
    with get_db().tx() as c:
        rows = c.all(sql + " ORDER BY g.last_name, g.first_name LIMIT 200", params)
    return {"items": [mask(ctx, r) for r in rows]}


@route("POST", "/api/guests", perm="guests.manage", tag="guests", summary="Create a guest profile (warns about likely duplicates)")
def create_guest(ctx: Ctx):
    body = ctx.body or {}
    with get_db().tx() as c:
        dups = find_duplicates(c, ctx.org_id, str(body.get("first_name", "")), str(body.get("last_name", "")), body.get("email"), body.get("phone"))
        if dups and not body.get("force"):
            raise conflict("Possible duplicate guest profile(s) found", {"duplicates": dups})
        gid = create_guest_row(c, ctx, body)
        return mask(ctx, c.one("SELECT * FROM guests WHERE id = ?", [gid])) | {"_created": True}


@route("GET", "/api/guests/{guest_id:int}", perm="guests.view", tag="guests", summary="Guest profile with stay and spending history")
def get_guest(ctx: Ctx):
    with get_db().tx() as c:
        g = c.one("SELECT * FROM guests WHERE id = ? AND organisation_id = ?", [ctx.path["guest_id"], ctx.org_id])
        if not g:
            raise not_found("Guest")
        stays = c.all("SELECT r.id, r.reference, r.hotel_id, h.name AS hotel_name, r.arrival, r.departure, r.status, rm.number AS room_number, "
                      "rt.name AS room_type_name FROM reservations r JOIN hotels h ON h.id = r.hotel_id JOIN room_types rt ON rt.id = r.room_type_id "
                      "LEFT JOIN rooms rm ON rm.id = r.room_id WHERE r.guest_id = ? ORDER BY r.arrival DESC", [g["id"]])
        if ctx.hotel_ids is not None:
            stays = [s for s in stays if s["hotel_id"] in ctx.hotel_ids]
        spend = c.scalar("SELECT COALESCE(SUM(fl.total_amount), 0) FROM folio_lines fl JOIN folios f ON f.id = fl.folio_id "
                         "WHERE f.guest_id = ? AND fl.kind = 'charge'", [g["id"]])
    out = mask(ctx, g)
    out.update({"stays": stays, "total_spend": spend, "completed_stays": sum(1 for s in stays if s["status"] == "checked_out"),
                "repeat_guest": sum(1 for s in stays if s["status"] == "checked_out") > 1})
    return out


@route("PATCH", "/api/guests/{guest_id:int}", perm="guests.manage", tag="guests", summary="Update a guest profile")
def update_guest(ctx: Ctx):
    with get_db().tx() as c:
        g = c.one("SELECT * FROM guests WHERE id = ? AND organisation_id = ?", [ctx.path["guest_id"], ctx.org_id])
        if not g:
            raise not_found("Guest")
        data = {f: ctx.body[f] for f in GUEST_FIELDS if f in (ctx.body or {})}
        if any(f in data for f in SENSITIVE):
            ctx.require("guests.identity.view")
        for b in ("vip", "marketing_consent"):
            if b in data:
                data[b] = 1 if data[b] else 0
        c.update("guests", g["id"], data)
        audit(c, ctx, "guest.updated", "guest", g["id"], old={k: g[k] for k in data if k not in SENSITIVE},
              new={k: v for k, v in data.items() if k not in SENSITIVE} | ({"identity_fields_changed": True} if any(f in data for f in SENSITIVE) else {}))
        return mask(ctx, c.one("SELECT * FROM guests WHERE id = ?", [g["id"]]))
