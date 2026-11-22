"""Document store (FR-DOC-001..003): secure upload of files linked to guests, reservations, folios, employees,
suppliers, purchase orders, invoices, events, expenses, journals, assets, incidents, the hotel itself and
scheduled-report outputs.

Security model
* A document inherits the access rule of the record it belongs to (e.g. an employee document needs hr.view,
  a supplier document procurement.view) plus documents.view / documents.upload.
* Confidential and restricted documents also need documents.confidential; employee documents default to
  confidential and additionally need hr.records; documents on restricted security incidents need
  security.sensitive.
* Only whitelisted file types are accepted; the content is checked against the type's signature and the size
  limit (EHMS_MAX_UPLOAD_MB, default 10). Files are stored outside the web root under a random name
  (EHMS_DOCUMENT_DIR) with a SHA-256 checksum that is verified on every download.
* Every upload, view, download, replacement, metadata change, legal hold and deletion is written to
  document_access_log; documents cannot be deleted before their retention date or while on legal hold.
"""
from __future__ import annotations

import base64
import binascii
import datetime as dt
import hashlib
import os
import re
import secrets

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, conflict, forbidden, not_found, route
from ..services import business_date, get_hotel, parse_date

# entity type -> (table, how the hotel is found, permission to view the record, label)
ENTITIES: dict[str, tuple[str, str, str, str]] = {
    "hotel": ("hotels", "self", "documents.view", "Hotel (licences, policies, certificates)"),
    "guest": ("guests", "org", "guests.view", "Guest"),
    "reservation": ("reservations", "hotel", "reservations.view", "Reservation"),
    "folio": ("folios", "hotel", "folio.view", "Folio"),
    "employee": ("employees", "hotel", "hr.view", "Employee"),
    "supplier": ("suppliers", "org", "procurement.view", "Supplier"),
    "purchase_order": ("purchase_orders", "hotel", "procurement.view", "Purchase order"),
    "supplier_invoice": ("supplier_invoices", "hotel", "procurement.view", "Supplier invoice"),
    "event": ("events", "hotel", "events.view", "Event"),
    "expense_claim": ("expense_claims", "hotel", "accounting.view", "Expense claim"),
    "journal_entry": ("journal_entries", "hotel", "accounting.view", "Journal entry"),
    "asset": ("assets", "hotel", "maintenance.view", "Asset"),
    "incident": ("security_incidents", "hotel", "security.view", "Security incident"),
    "report": ("report_schedules", "hotel", "reports.view", "Scheduled report output"),
}
CATEGORIES = {
    "identity": 7, "contract": 10, "invoice": 7, "receipt": 7, "statement": 7, "licence": 10, "policy": 10, "certificate": 10,
    "hr_record": 10, "medical": 10, "quotation": 7, "photo": 3, "report": 2, "correspondence": 6, "other": 6,
}  # default retention in years (Nigerian practice: 6–7 years for financial records); configurable per hotel
ALLOWED = {
    "pdf": ("application/pdf", [b"%PDF-"]),
    "png": ("image/png", [b"\x89PNG\r\n\x1a\n"]),
    "jpg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "jpeg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", [b"PK\x03\x04"]),
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", [b"PK\x03\x04"]),
    "csv": ("text/csv", []),
    "txt": ("text/plain", []),
}


def storage_dir() -> str:
    d = os.environ.get("EHMS_DOCUMENT_DIR") or os.path.join(os.getcwd(), "data", "documents")
    os.makedirs(d, exist_ok=True)
    return d


def max_bytes() -> int:
    return int(float(os.environ.get("EHMS_MAX_UPLOAD_MB", "10")) * 1024 * 1024)


def _safe_name(name: str) -> str:
    base = os.path.basename(str(name or "").replace("\\", "/")).strip()
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base)[:150].strip(" .")
    return base or "document"


def validate_file(filename: str, data: bytes) -> tuple[str, str]:
    """Returns (safe filename, content type) or raises."""
    name = _safe_name(filename)
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if ext not in ALLOWED:
        raise bad_request(f"File type .{ext or '?'} is not allowed. Allowed: {', '.join(sorted(ALLOWED))}")
    if not data:
        raise bad_request("The file is empty")
    if len(data) > max_bytes():
        raise ApiError(413, "file_too_large", f"The file is larger than {max_bytes() // (1024 * 1024)} MB")
    ctype, sigs = ALLOWED[ext]
    if sigs and not any(data.startswith(s) for s in sigs):
        raise bad_request(f"The file content does not match a .{ext} file")
    if not sigs:
        try:
            data[:4096].decode("utf-8")
        except UnicodeDecodeError:
            raise bad_request(f"A .{ext} file must be plain UTF-8 text")
    return name, ctype


def _entity(c, ctx: Ctx | None, etype: str, eid: int, org_id: int) -> dict:
    if etype not in ENTITIES:
        raise bad_request(f"entity_type must be one of: {', '.join(ENTITIES)}")
    table, scope, _, _ = ENTITIES[etype]
    row = c.one(f"SELECT * FROM {table} WHERE id = ?", [eid])  # table name comes from the fixed map above
    if not row:
        raise not_found(ENTITIES[etype][3])
    if scope == "self":
        hid, org = row["id"], row["organisation_id"]
    elif scope == "org":
        hid, org = None, row["organisation_id"]
    else:
        hid = row["hotel_id"]
        org = c.scalar("SELECT organisation_id FROM hotels WHERE id = ?", [hid])
    if org != org_id:
        raise not_found(ENTITIES[etype][3])
    if ctx is not None and hid is not None:
        ctx.check_hotel(hid)
    return {"hotel_id": hid, "row": row}


def can_access(ctx: Ctx, doc: dict, entity_row: dict | None) -> str | None:
    """Returns None if allowed, else the reason."""
    if not ctx.can("documents.view"):
        return "documents.view"
    need = ENTITIES[doc["entity_type"]][2]
    if not ctx.can(need):
        return need
    if doc["confidentiality"] != "internal" and not ctx.can("documents.confidential"):
        return "documents.confidential"
    if doc["entity_type"] == "employee" and doc["confidentiality"] != "internal" and not ctx.can("hr.records"):
        return "hr.records"
    if doc["entity_type"] == "incident" and entity_row and entity_row.get("restricted") and not ctx.can("security.sensitive"):
        return "security.sensitive"
    if doc["entity_type"] == "report" and entity_row:
        from .reports import REPORT_PERMS
        p = REPORT_PERMS.get(entity_row["report_code"])
        if p and not ctx.can(p):
            return p
    return None


def log_access(c, doc_id: int, user_id: int | None, action: str, detail: str | None = None, ip: str | None = None) -> None:
    c.insert("document_access_log", {"document_id": doc_id, "user_id": user_id, "action": action, "detail": detail, "ip": ip, "created_at": now_iso()})


def retention_years(c, hotel_id: int | None, category: str) -> int:
    if hotel_id:
        from ..services import hotel_setting
        v = hotel_setting(c, hotel_id, f"documents.retention.{category}")
        if v and v.isdigit():
            return int(v)
    return CATEGORIES.get(category, 6)


def store_document(c, *, org_id: int, hotel_id: int | None, entity_type: str, entity_id: int | None, category: str, title: str,
                   filename: str, data: bytes, confidentiality: str = "internal", user_id: int | None, notes: str | None = None,
                   replaces: dict | None = None, ip: str | None = None) -> int:
    name, ctype = validate_file(filename, data)
    key = secrets.token_hex(20)
    path = os.path.join(storage_dir(), key)
    with open(path, "wb") as fh:
        fh.write(data)
    today = dt.date.today()
    keep = retention_years(c, hotel_id, category)
    try:
        until = today.replace(year=today.year + keep)
    except ValueError:  # 29 February
        until = today.replace(year=today.year + keep, day=28)
    did = c.insert("documents", {
        "organisation_id": org_id, "hotel_id": hotel_id, "entity_type": entity_type, "entity_id": entity_id, "category": category,
        "title": title[:200], "filename": name, "content_type": ctype, "size_bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "storage_key": key, "confidentiality": confidentiality, "version": (replaces["version"] + 1) if replaces else 1,
        "replaces_id": replaces["id"] if replaces else None, "retention_until": until.isoformat(), "notes": notes,
        "uploaded_by": user_id, "created_at": now_iso()})
    log_access(c, did, user_id, "upload", f"{name} ({len(data)} bytes)" + (f", replaces version {replaces['version']}" if replaces else ""), ip)
    if replaces:
        c.execute("UPDATE documents SET status = 'superseded' WHERE id = ?", [replaces["id"]])
        log_access(c, replaces["id"], user_id, "superseded", f"by document {did}", ip)
    return did


def _decode(ctx: Ctx) -> bytes:
    raw = ctx.field("content_base64", kind=str)
    if "," in raw[:100] and raw.startswith("data:"):
        raw = raw.split(",", 1)[1]
    if len(raw) > max_bytes() * 4 // 3 + 16:
        raise ApiError(413, "file_too_large", f"The file is larger than {max_bytes() // (1024 * 1024)} MB")
    try:
        return base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError):
        raise bad_request("content_base64 is not valid base64")


def _view(d: dict, users: dict) -> dict:
    out = {k: d[k] for k in ("id", "hotel_id", "entity_type", "entity_id", "category", "title", "filename", "content_type", "size_bytes",
                             "confidentiality", "version", "replaces_id", "retention_until", "legal_hold", "status", "notes", "created_at",
                             "deleted_at", "delete_reason")}
    out["uploaded_by_name"] = users.get(d["uploaded_by"])
    return out


@route("GET", "/api/documents/meta", perm="documents.view", tag="documents", summary="Document entity types, categories, default retention and allowed file types")
def meta(ctx: Ctx):
    return {"entities": [{"code": k, "label": v[3], "permission": v[2]} for k, v in ENTITIES.items()],
            "categories": [{"code": k, "retention_years": v} for k, v in CATEGORIES.items()],
            "allowed_types": sorted(ALLOWED), "max_mb": max_bytes() // (1024 * 1024)}


@route("POST", "/api/documents", perm="documents.upload", tag="documents",
       summary="Upload a document (JSON: entity_type, entity_id, category, title, filename, content_base64, confidentiality, notes)")
def upload(ctx: Ctx):
    etype = ctx.field("entity_type", kind=str)
    eid = ctx.field("entity_id", kind=int)
    category = ctx.field("category", required=False, kind=str) or "other"
    if category not in CATEGORIES:
        raise bad_request(f"category must be one of: {', '.join(CATEGORIES)}")
    conf = ctx.field("confidentiality", required=False, kind=str) or ("confidential" if etype == "employee" or category in ("medical", "hr_record", "identity") else "internal")
    if conf not in ("internal", "confidential", "restricted"):
        raise bad_request("confidentiality must be internal, confidential or restricted")
    data = _decode(ctx)
    filename = ctx.field("filename", kind=str)
    with get_db().tx() as c:
        ent = _entity(c, ctx, etype, eid, ctx.org_id)
        # Uploading needs access to the record; confidential documents are write-only for people without
        # documents.confidential (e.g. reception can file a guest's ID scan but not browse ID scans).
        probe = {"entity_type": etype, "confidentiality": "internal"}
        reason = can_access(ctx, probe, ent["row"])
        if reason:
            raise forbidden(f"Uploading this document requires {reason}")
        did = store_document(c, org_id=ctx.org_id, hotel_id=ent["hotel_id"], entity_type=etype, entity_id=eid, category=category,
                             title=ctx.field("title", required=False, kind=str) or filename, filename=filename, data=data,
                             confidentiality=conf, user_id=ctx.user_id, notes=ctx.field("notes", required=False, kind=str), ip=ctx.ip)
        audit(c, ctx, "document.uploaded", "document", did, filename, new={"entity": etype, "entity_id": eid, "category": category}, hotel_id=ent["hotel_id"])
    return {"id": did, "confidentiality": conf, "visible_to_you": conf == "internal" or ctx.can("documents.confidential"), "_created": True}


@route("GET", "/api/documents", perm="documents.view", tag="documents",
       summary="Documents for a record (?entity_type&entity_id) or search (?hotel_id&q&category); only those you may open are listed")
def list_documents(ctx: Ctx):
    etype, eid = ctx.q("entity_type"), ctx.q("entity_id")
    with get_db().tx() as c:
        params: list = [ctx.org_id]
        sql = "SELECT * FROM documents WHERE organisation_id = ? AND status <> 'deleted'"
        if not ctx.q("history"):
            sql += " AND status = 'active'"
        if etype:
            ent = _entity(c, ctx, etype, int(eid or 0), ctx.org_id)
            if etype in ENTITIES and not ctx.can(ENTITIES[etype][2]):
                raise forbidden(f"Documents on this record require {ENTITIES[etype][2]}")
            sql += " AND entity_type = ? AND entity_id = ?"
            params += [etype, int(eid)]
            rows_ent = {(etype, int(eid)): ent["row"]}
        else:
            hid = ctx.check_hotel(ctx.q("hotel_id"))
            sql += " AND (hotel_id = ? OR hotel_id IS NULL)"
            params.append(hid)
            rows_ent = {}
        if ctx.q("category"):
            sql += " AND category = ?"
            params.append(ctx.q("category"))
        if ctx.q("q"):
            sql += " AND (LOWER(title) LIKE ? OR LOWER(filename) LIKE ?)"
            like = f"%{str(ctx.q('q')).lower()}%"
            params += [like, like]
        docs = c.all(sql + " ORDER BY created_at DESC, id DESC LIMIT 300", params)
        users = {u["id"]: u["full_name"] for u in c.all("SELECT id, full_name FROM users WHERE organisation_id = ?", [ctx.org_id])}
        out, hidden = [], 0
        for d in docs:
            key = (d["entity_type"], d["entity_id"])
            if key not in rows_ent:
                table = ENTITIES[d["entity_type"]][0]
                rows_ent[key] = c.one(f"SELECT * FROM {table} WHERE id = ?", [d["entity_id"]]) if d["entity_id"] else None
            ent_row = rows_ent[key]
            if ent_row is not None and "hotel_id" in ent_row and ctx.hotel_ids is not None and ent_row["hotel_id"] not in ctx.hotel_ids:
                continue
            if can_access(ctx, d, ent_row):
                hidden += 1
                continue
            out.append(_view(d, users))
    return {"items": out, "hidden_count": hidden}


class _Denied(ApiError):
    """A refusal that must be recorded in the access log even though the request's transaction rolls back."""
    def __init__(self, doc_id, user_id, detail, ip, message, action="denied", status=403, code="forbidden"):
        super().__init__(status, code, message)
        self.log = (doc_id, user_id, action, detail, ip)


def _logs_denials(fn):
    """FR-DOC-003: refused attempts are recorded too, in their own transaction (the refusal rolls back the request's)."""
    import functools

    @functools.wraps(fn)
    def wrapper(ctx):
        try:
            return fn(ctx)
        except _Denied as e:
            with get_db().tx() as c:
                doc_id, user_id, action, detail, ip = e.log
                log_access(c, doc_id, user_id, action, detail, ip)
            raise
    return wrapper


def _load(c, ctx: Ctx, doc_id: int, action: str) -> dict:
    d = c.one("SELECT * FROM documents WHERE id = ? AND organisation_id = ?", [doc_id, ctx.org_id])
    if not d or d["status"] == "deleted":
        raise not_found("Document")
    if d["hotel_id"]:
        ctx.check_hotel(d["hotel_id"])
    ent_row = c.one(f"SELECT * FROM {ENTITIES[d['entity_type']][0]} WHERE id = ?", [d["entity_id"]]) if d["entity_id"] else None
    reason = can_access(ctx, d, ent_row)
    if reason:
        raise _Denied(d["id"], ctx.user_id, f"{action}: missing {reason}", ctx.ip, f"This document requires {reason}")
    return d


@route("GET", "/api/documents/{doc_id:int}", perm="documents.view", tag="documents", summary="Document details, version history and access history")
@_logs_denials
def get_document(ctx: Ctx):
    with get_db().tx() as c:
        d = _load(c, ctx, ctx.path["doc_id"], "view")
        log_access(c, d["id"], ctx.user_id, "view", None, ctx.ip)
        users = {u["id"]: u["full_name"] for u in c.all("SELECT id, full_name FROM users WHERE organisation_id = ?", [ctx.org_id])}
        versions, cur = [], d
        while cur and cur["replaces_id"]:
            cur = c.one("SELECT * FROM documents WHERE id = ?", [cur["replaces_id"]])
            if cur:
                versions.append(_view(cur, users))
        later = c.all("SELECT * FROM documents WHERE replaces_id = ?", [d["id"]])
        log = c.all("SELECT * FROM document_access_log WHERE document_id = ? ORDER BY id DESC LIMIT 200", [d["id"]])
    out = _view(d, users)
    out["previous_versions"] = versions
    out["replaced_by"] = [x["id"] for x in later]
    out["access_log"] = [{"at": r["created_at"], "user": users.get(r["user_id"], "system"), "action": r["action"], "detail": r["detail"], "ip": r["ip"]} for r in log]
    return out


@route("GET", "/api/documents/{doc_id:int}/download", perm="documents.view", tag="documents", summary="Download the file (integrity-checked, logged)")
@_logs_denials
def download(ctx: Ctx):
    with get_db().tx() as c:
        d = _load(c, ctx, ctx.path["doc_id"], "download")
        path = os.path.join(storage_dir(), d["storage_key"])
        if not os.path.exists(path):
            raise ApiError(410, "file_missing", "The stored file is missing; restore it from backup")
        with open(path, "rb") as fh:
            data = fh.read()
        if hashlib.sha256(data).hexdigest() != d["sha256"]:
            raise _Denied(d["id"], ctx.user_id, "checksum mismatch", ctx.ip, "The stored file failed its integrity check and was not released",
                          action="integrity_failed", status=409, code="integrity_failed")
        log_access(c, d["id"], ctx.user_id, "download", None, ctx.ip)
    disp = "inline" if d["content_type"] in ("application/pdf", "image/png", "image/jpeg") else "attachment"
    return Response(data, media_type=d["content_type"], headers={"Content-Disposition": f'{disp}; filename="{d["filename"]}"',
                                                                  "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store"})


@route("POST", "/api/documents/{doc_id:int}/replace", perm="documents.upload", tag="documents",
       summary="Upload a new version (filename, content_base64, notes); the old version is kept as superseded")
@_logs_denials
def replace(ctx: Ctx):
    data = _decode(ctx)
    with get_db().tx() as c:
        d = _load(c, ctx, ctx.path["doc_id"], "replace")
        if d["status"] != "active":
            raise conflict("Only the current version can be replaced")
        did = store_document(c, org_id=d["organisation_id"], hotel_id=d["hotel_id"], entity_type=d["entity_type"], entity_id=d["entity_id"],
                             category=d["category"], title=d["title"], filename=ctx.field("filename", kind=str), data=data,
                             confidentiality=d["confidentiality"], user_id=ctx.user_id, notes=ctx.field("notes", required=False, kind=str), replaces=d, ip=ctx.ip)
        audit(c, ctx, "document.replaced", "document", did, d["title"], old={"id": d["id"]}, hotel_id=d["hotel_id"])
    return {"id": did, "_created": True}


@route("PATCH", "/api/documents/{doc_id:int}", perm="documents.upload", tag="documents",
       summary="Change title, category, notes or confidentiality (raising confidentiality is always allowed; lowering needs documents.manage)")
@_logs_denials
def update(ctx: Ctx):
    body = ctx.body or {}
    with get_db().tx() as c:
        d = _load(c, ctx, ctx.path["doc_id"], "update")
        ch = {}
        for k in ("title", "notes"):
            if k in body:
                ch[k] = str(body[k] or "")[:2000] or (d[k] if k == "title" else None)
        if "category" in body:
            if body["category"] not in CATEGORIES:
                raise bad_request("Unknown category")
            ch["category"] = body["category"]
        if "confidentiality" in body:
            order = ["internal", "confidential", "restricted"]
            if body["confidentiality"] not in order:
                raise bad_request("confidentiality must be internal, confidential or restricted")
            if order.index(body["confidentiality"]) < order.index(d["confidentiality"]) and not ctx.can("documents.manage"):
                raise forbidden("Lowering confidentiality requires documents.manage")
            ch["confidentiality"] = body["confidentiality"]
        if not ch:
            raise bad_request("Nothing to change")
        c.update("documents", d["id"], ch)
        log_access(c, d["id"], ctx.user_id, "update", ", ".join(f"{k}: {d[k]} → {v}" for k, v in ch.items()), ctx.ip)
        audit(c, ctx, "document.updated", "document", d["id"], d["title"], old={k: d[k] for k in ch}, new=ch, hotel_id=d["hotel_id"])
    return {"ok": True}


@route("POST", "/api/documents/{doc_id:int}/legal-hold", perm="documents.manage", tag="documents",
       summary="Place or lift a legal hold ({hold: true|false, reason}); held documents cannot be deleted")
@_logs_denials
def legal_hold(ctx: Ctx):
    hold = bool(ctx.field("hold", kind=bool))
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        d = _load(c, ctx, ctx.path["doc_id"], "legal_hold")
        c.update("documents", d["id"], {"legal_hold": 1 if hold else 0})
        log_access(c, d["id"], ctx.user_id, "legal_hold" if hold else "hold_lifted", reason, ctx.ip)
        audit(c, ctx, "document.legal_hold" if hold else "document.hold_lifted", "document", d["id"], reason, hotel_id=d["hotel_id"])
    return {"ok": True}


@route("POST", "/api/documents/{doc_id:int}/retention", perm="documents.manage", tag="documents",
       summary="Extend the retention date ({retention_until, reason}); retention can only be extended")
@_logs_denials
def extend_retention(ctx: Ctx):
    until = parse_date(ctx.field("retention_until", kind=str), "retention_until")
    reason = ctx.field("reason", kind=str)
    with get_db().tx() as c:
        d = _load(c, ctx, ctx.path["doc_id"], "retention")
        if d["retention_until"] and until.isoformat() <= d["retention_until"]:
            raise bad_request("Retention can only be extended")
        c.update("documents", d["id"], {"retention_until": until.isoformat()})
        log_access(c, d["id"], ctx.user_id, "retention", f"{d['retention_until']} → {until}: {reason}", ctx.ip)
    return {"ok": True}


@route("DELETE", "/api/documents/{doc_id:int}", perm="documents.manage", tag="documents",
       summary="Delete a document after its retention period ({reason}); the record and access history are kept, the file is erased")
@_logs_denials
def delete(ctx: Ctx):
    reason = ctx.field("reason", kind=str)
    if len(reason) < 5:
        raise bad_request("Give a reason for the deletion")
    with get_db().tx() as c:
        d = _load(c, ctx, ctx.path["doc_id"], "delete")
        if d["legal_hold"]:
            raise conflict("This document is on legal hold")
        hotel = get_hotel(c, d["hotel_id"]) if d["hotel_id"] else None
        today = business_date(hotel) if hotel else dt.date.today()
        if d["retention_until"] and d["retention_until"] > today.isoformat():
            raise conflict(f"This document must be kept until {d['retention_until']} (retention policy)")
        c.update("documents", d["id"], {"status": "deleted", "deleted_at": now_iso(), "deleted_by": ctx.user_id, "delete_reason": reason})
        log_access(c, d["id"], ctx.user_id, "delete", reason, ctx.ip)
        audit(c, ctx, "document.deleted", "document", d["id"], d["title"], old={"filename": d["filename"], "sha256": d["sha256"]}, hotel_id=d["hotel_id"])
    try:
        os.remove(os.path.join(storage_dir(), d["storage_key"]))
    except OSError:
        pass
    return {"ok": True}


@route("GET", "/api/hotels/{hotel_id:int}/documents/retention-due", perm="documents.manage", tag="documents",
       summary="Documents past their retention date and not on hold (candidates for disposal)")
def retention_due(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        today = business_date(get_hotel(c, hid)).isoformat()
        rows = c.all("SELECT * FROM documents WHERE organisation_id = ? AND (hotel_id = ? OR hotel_id IS NULL) AND status <> 'deleted' "
                     "AND legal_hold = 0 AND retention_until <= ? ORDER BY retention_until", [ctx.org_id, hid, today])
        users = {u["id"]: u["full_name"] for u in c.all("SELECT id, full_name FROM users WHERE organisation_id = ?", [ctx.org_id])}
    return {"items": [_view(d, users) for d in rows]}


@route("GET", "/api/hotels/{hotel_id:int}/documents/access-log", perm="documents.manage", tag="documents",
       summary="Recent document activity across the hotel (?action)")
def access_log(ctx: Ctx):
    hid = ctx.check_hotel(ctx.path["hotel_id"])
    with get_db().tx() as c:
        sql = ("SELECT l.*, d.title, d.filename, u.full_name FROM document_access_log l JOIN documents d ON d.id = l.document_id "
               "LEFT JOIN users u ON u.id = l.user_id WHERE d.organisation_id = ? AND (d.hotel_id = ? OR d.hotel_id IS NULL)")
        params: list = [ctx.org_id, hid]
        if ctx.q("action"):
            sql += " AND l.action = ?"
            params.append(ctx.q("action"))
        rows = c.all(sql + " ORDER BY l.id DESC LIMIT 300", params)
    return {"items": [{"at": r["created_at"], "user": r["full_name"] or "system", "action": r["action"], "document_id": r["document_id"],
                       "title": r["title"], "detail": r["detail"], "ip": r["ip"]} for r in rows]}
