"""Per-user preferences (release 1.2): interface language."""
from __future__ import annotations

from ..db import get_db
from ..http import Ctx, audit, bad_request, route

LANGUAGES = {"en": "English", "fr": "Français"}


@route("GET", "/api/me/preferences", tag="auth", summary="Your interface language and the languages available")
def get_prefs(ctx: Ctx):
    return {"language": (ctx.user or {}).get("language") or "en", "languages": LANGUAGES}


@route("PUT", "/api/me/preferences", tag="auth", summary="Set your interface language: language (en | fr)")
def set_prefs(ctx: Ctx):
    lang = ctx.field("language", kind=str)
    if lang not in LANGUAGES:
        raise bad_request(f"language must be one of {', '.join(LANGUAGES)}")
    with get_db().tx() as c:
        c.update("users", ctx.user_id, {"language": lang})
        audit(c, ctx, "user.language", "user", ctx.user_id, old={"language": (ctx.user or {}).get("language")}, new={"language": lang})
    return {"language": lang}
