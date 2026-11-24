"""Backups screen (release 1.2): back up now, schedule and retention, history with size and verification result,
test-restore verification, download, failure alerts. Whole-database backups are a platform function: they need the
admin.backups permission and access to all hotels."""
from __future__ import annotations

import datetime as dt
import json
import os

from starlette.responses import FileResponse

from .. import backup as bk
from ..db import get_db, now_iso
from ..http import Ctx, audit, bad_request, forbidden, not_found, route
from ..services import queue_notification

DEFAULT_SCHEDULE = {"enabled": True, "hour_utc": 1, "retention_days": 14}


def schedule(c) -> dict:
    raw = c.scalar("SELECT value FROM system_settings WHERE hotel_id IS NULL AND key = 'backup.schedule'")
    return {**DEFAULT_SCHEDULE, **(json.loads(raw) if raw else {})}


def _platform(ctx: Ctx) -> None:
    if not (ctx.user or {}).get("all_hotels"):
        raise forbidden("Whole-database backups need access to all hotels")


@route("GET", "/api/admin/backups", perm="admin.backups", tag="admin", summary="Backup history, schedule and storage location")
def list_backups(ctx: Ctx):
    _platform(ctx)
    with get_db().tx() as c:
        rows = c.all("SELECT b.*, u.full_name AS created_by_name FROM backups b LEFT JOIN users u ON u.id = b.created_by ORDER BY b.id DESC LIMIT 200")
        for b in rows:
            b["file_present"] = b["status"] == "ok" and os.path.isfile(os.path.join(bk.backup_dir(), os.path.basename(b["filename"])))
        return {"items": rows, "schedule": schedule(c), "directory": bk.backup_dir(), "dialect": get_db().dialect,
                "last_ok": next((b["created_at"] for b in rows if b["status"] == "ok"), None)}


@route("POST", "/api/admin/backups", perm="admin.backups", tag="admin", summary="Back up the database and stored documents now")
def backup_now(ctx: Ctx):
    _platform(ctx)
    row = bk.create_backup("manual", ctx.user_id)
    with get_db().tx() as c:
        audit(c, ctx, "admin.backup_created" if row["status"] == "ok" else "admin.backup_failed", "backup", row["id"], row["filename"],
              new={"size": row.get("size_bytes"), "error": row.get("error")})
    if row["status"] != "ok":
        raise bad_request(f"The backup failed: {row.get('error')}")
    return {**row, "_created": True}


@route("POST", "/api/admin/backups/{backup_id:int}/verify", perm="admin.backups", tag="admin",
       summary="Verify a backup: checksums, row counts and a test restore into a temporary database")
def verify_backup(ctx: Ctx):
    _platform(ctx)
    with get_db().tx() as c:
        b = c.one("SELECT * FROM backups WHERE id = ?", [ctx.path["backup_id"]])
    if not b or b["status"] != "ok":
        raise not_found("Backup")
    path = os.path.join(bk.backup_dir(), os.path.basename(b["filename"]))
    if not os.path.isfile(path):
        raise bad_request("The backup file is no longer in the backup folder")
    try:
        result = bk.verify(path)
        ok, err = True, None
    except Exception as e:
        result, ok, err = None, False, f"{type(e).__name__}: {e}"[:500]
    with get_db().tx() as c:
        c.update("backups", b["id"], {"verified": 1 if ok else -1, "error": err})
        audit(c, ctx, "admin.backup_verified" if ok else "admin.backup_verify_failed", "backup", b["id"], b["filename"], new={"ok": ok, "error": err})
    return {"ok": ok, "error": err, "result": result}


@route("GET", "/api/admin/backups/{backup_id:int}/download", perm="admin.backups", tag="admin", summary="Download a backup archive (logged)")
def download_backup(ctx: Ctx):
    _platform(ctx)
    with get_db().tx() as c:
        b = c.one("SELECT * FROM backups WHERE id = ?", [ctx.path["backup_id"]])
        if not b or b["status"] != "ok":
            raise not_found("Backup")
        path = os.path.join(bk.backup_dir(), os.path.basename(b["filename"]))
        if not os.path.isfile(path):
            raise not_found("Backup file")
        audit(c, ctx, "admin.backup_downloaded", "backup", b["id"], b["filename"])
    return FileResponse(path, media_type="application/zip" if b["filename"].endswith(".zip") else "application/octet-stream", filename=b["filename"])


@route("PUT", "/api/admin/backups/schedule", perm="admin.backups", tag="admin",
       summary="Automatic backups: enabled, hour_utc (0–23), retention_days (1–365, scheduled backups older than this are deleted)")
def set_schedule(ctx: Ctx):
    _platform(ctx)
    hour = int(ctx.field("hour_utc", kind=int))
    days = int(ctx.field("retention_days", kind=int))
    if not 0 <= hour <= 23 or not 1 <= days <= 365:
        raise bad_request("hour_utc must be 0–23 and retention_days 1–365")
    new = {"enabled": bool(ctx.field("enabled", required=False, default=True)), "hour_utc": hour, "retention_days": days}
    with get_db().tx() as c:
        old = schedule(c)
        if c.one("SELECT id FROM system_settings WHERE hotel_id IS NULL AND key = 'backup.schedule'"):
            c.execute("UPDATE system_settings SET value = ? WHERE hotel_id IS NULL AND key = 'backup.schedule'", [json.dumps(new)])
        else:
            c.execute("INSERT INTO system_settings (hotel_id, key, value) VALUES (NULL, 'backup.schedule', ?)", [json.dumps(new)])
        audit(c, ctx, "admin.backup_schedule", "system_settings", None, old=old, new=new)
    return new


def _admins(c) -> list[int]:
    return [r["id"] for r in c.all("SELECT DISTINCT u.id FROM users u JOIN user_roles ur ON ur.user_id = u.id JOIN role_permissions rp ON rp.role_id = ur.role_id "
                                   "WHERE rp.permission_code = 'admin.backups' AND u.status = 'active' AND u.all_hotels = 1")]


def scheduled_backup() -> str | None:
    """Worker: take the daily backup once, after the configured hour; verify it; apply retention; alert on failure."""
    from ..worker import _once
    db = get_db()
    now = dt.datetime.now(dt.timezone.utc)
    with db.tx() as c:
        sch = schedule(c)
        if not sch["enabled"] or now.hour < sch["hour_utc"] or not _once(c, "scheduled_backup", now.date().isoformat()):
            return None
    row = bk.create_backup("scheduled", None)
    err = row.get("error")
    if row["status"] == "ok":
        try:
            bk.verify(os.path.join(bk.backup_dir(), row["filename"]))
            verified = 1
        except Exception as e:  # verification failure is a backup failure
            verified, err = -1, f"Verification failed: {e}"[:500]
        with db.tx() as c:
            c.update("backups", row["id"], {"verified": verified, "error": err})
        bk.apply_retention(db, sch["retention_days"])
    if err:
        with db.tx() as c:
            for uid in _admins(c):
                queue_notification(c, None, "in_app", str(uid), "Automatic backup FAILED", f"{row['filename']}: {err}. Open Administration → Backups.", "backup", row["id"])
    return row["status"] if not err else "failed"
