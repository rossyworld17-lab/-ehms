"""Room-category photo gallery and videos (release 1.2). Photos (JPEG/PNG/WebP, size-limited, content-checked) are stored
on the server and served publicly so the booking engine can show them; videos are links to a hosted video (YouTube,
Vimeo or an https URL)."""
from __future__ import annotations

import base64
import binascii
import os
import re
import secrets

from starlette.responses import Response

from ..db import get_db, now_iso
from ..http import ApiError, Ctx, audit, bad_request, not_found, route
from .documents import storage_dir

PHOTO_TYPES = {"jpg": ("image/jpeg", b"\xff\xd8\xff"), "jpeg": ("image/jpeg", b"\xff\xd8\xff"), "png": ("image/png", b"\x89PNG"),
               "webp": ("image/webp", b"RIFF")}
MAX_PHOTO = 5 * 1024 * 1024
VIDEO_RE = re.compile(r"^https://[A-Za-z0-9.-]+(/[^\s<>\"']*)?$")


def media_dir() -> str:
    d = os.path.join(storage_dir(), "media")
    os.makedirs(d, exist_ok=True)
    return d


def public_media(c, room_type_id: int) -> list[dict]:
    return [{"id": m["id"], "kind": m["kind"], "caption": m["caption"],
             "url": f"/api/public/media/{m['id']}" if m["kind"] == "photo" else m["url"]}
            for m in c.all("SELECT * FROM room_type_media WHERE room_type_id = ? ORDER BY sort_order, id", [room_type_id])]


def _room_type(c, ctx: Ctx, rt_id) -> dict:
    rt = c.one("SELECT * FROM room_types WHERE id = ?", [int(rt_id)])
    if not rt:
        raise not_found("Room category")
    ctx.check_hotel(rt["hotel_id"])
    return rt


@route("GET", "/api/room-types/{rt_id:int}/media", perm="rooms.view", tag="rooms", summary="Photos and videos of a room category")
def list_media(ctx: Ctx):
    with get_db().tx() as c:
        rt = _room_type(c, ctx, ctx.path["rt_id"])
        return {"items": public_media(c, rt["id"])}


@route("POST", "/api/room-types/{rt_id:int}/media", perm="rooms.manage", tag="rooms",
       summary="Add a photo (filename, content_base64; JPEG/PNG/WebP up to 5 MB) or a video (kind=video, url) with a caption")
def add_media(ctx: Ctx):
    kind = ctx.field("kind", required=False, kind=str) or "photo"
    caption = (ctx.field("caption", required=False, kind=str) or "")[:150] or None
    with get_db().tx() as c:
        rt = _room_type(c, ctx, ctx.path["rt_id"])
        if c.scalar("SELECT COUNT(*) FROM room_type_media WHERE room_type_id = ?", [rt["id"]]) >= 20:
            raise bad_request("A room category can have up to 20 photos and videos")
        order = (c.scalar("SELECT COALESCE(MAX(sort_order),0) FROM room_type_media WHERE room_type_id = ?", [rt["id"]]) or 0) + 1
        row = {"room_type_id": rt["id"], "kind": kind, "caption": caption, "sort_order": order, "created_by": ctx.user_id, "created_at": now_iso()}
        if kind == "video":
            url = str(ctx.field("url", kind=str)).strip()
            if not VIDEO_RE.match(url) or len(url) > 500:
                raise bad_request("Enter an https:// link to the video (YouTube, Vimeo or your website)")
            row["url"] = url
        elif kind == "photo":
            name = str(ctx.field("filename", kind=str))
            ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
            if ext not in PHOTO_TYPES:
                raise bad_request("Photos must be JPEG, PNG or WebP")
            try:
                data = base64.b64decode(str(ctx.field("content_base64", kind=str)), validate=True)
            except (binascii.Error, ValueError):
                raise bad_request("content_base64 is not valid base64")
            ctype, sig = PHOTO_TYPES[ext]
            if not data or not data.startswith(sig) or (ext == "webp" and data[8:12] != b"WEBP"):
                raise bad_request("The file content is not a valid image of that type")
            if len(data) > MAX_PHOTO:
                raise ApiError(413, "file_too_large", "Photos must be 5 MB or smaller")
            stored = f"rt{rt['id']}-{secrets.token_hex(8)}.{'jpg' if ext == 'jpeg' else ext}"
            with open(os.path.join(media_dir(), stored), "wb") as fh:
                fh.write(data)
            row.update({"filename": stored, "content_type": ctype})
        else:
            raise bad_request("kind must be photo or video")
        mid = c.insert("room_type_media", row)
        if kind == "photo" and not rt.get("image_url"):
            c.update("room_types", rt["id"], {"image_url": f"/api/public/media/{mid}"})
        audit(c, ctx, "rooms.media_added", "room_type", rt["id"], rt["code"], new={"kind": kind, "caption": caption}, hotel_id=rt["hotel_id"])
    return {"id": mid, "_created": True}


@route("DELETE", "/api/media/{media_id:int}", perm="rooms.manage", tag="rooms", summary="Remove a photo or video")
def delete_media(ctx: Ctx):
    with get_db().tx() as c:
        m = c.one("SELECT * FROM room_type_media WHERE id = ?", [ctx.path["media_id"]])
        if not m:
            raise not_found("Media")
        rt = _room_type(c, ctx, m["room_type_id"])
        c.execute("DELETE FROM room_type_media WHERE id = ?", [m["id"]])
        if rt.get("image_url") == f"/api/public/media/{m['id']}":
            nxt = c.one("SELECT id FROM room_type_media WHERE room_type_id = ? AND kind = 'photo' ORDER BY sort_order, id", [rt["id"]])
            c.update("room_types", rt["id"], {"image_url": f"/api/public/media/{nxt['id']}" if nxt else None})
        audit(c, ctx, "rooms.media_removed", "room_type", rt["id"], rt["code"], old={"kind": m["kind"], "caption": m["caption"]}, hotel_id=rt["hotel_id"])
    if m["filename"]:
        try:
            os.remove(os.path.join(media_dir(), os.path.basename(m["filename"])))
        except OSError:
            pass
    return {"ok": True}


@route("GET", "/api/public/media/{media_id:int}", public=True, rate_limit=300, tag="booking-engine", summary="A room photo (public, for the booking engine)")
def serve_media(ctx: Ctx):
    with get_db().tx() as c:
        m = c.one("SELECT * FROM room_type_media WHERE id = ? AND kind = 'photo'", [ctx.path["media_id"]])
    if not m:
        raise not_found("Photo")
    path = os.path.join(media_dir(), os.path.basename(m["filename"]))
    if not os.path.isfile(path):
        raise not_found("Photo")
    with open(path, "rb") as fh:
        data = fh.read()
    return Response(data, media_type=m["content_type"], headers={"Cache-Control": "public, max-age=86400", "X-Content-Type-Options": "nosniff"})
