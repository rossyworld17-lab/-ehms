"""ASGI application entry point.

Run (development):  uvicorn ehms.app:app --reload --port 8000
"""
from __future__ import annotations

import asyncio
import datetime as dt
import contextlib
import hashlib
import logging
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.concurrency import run_in_threadpool
from starlette.staticfiles import StaticFiles

from . import __version__, modules  # noqa: F401  (registers routes)
from .config import settings
from .db import get_db
from .http import openapi_spec, starlette_routes
from .migrate import migrate

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("ehms")


async def health(request: Request) -> Response:
    try:
        with get_db().tx() as c:
            c.scalar("SELECT 1")
        return JSONResponse({"status": "ok", "version": __version__, "database": get_db().dialect})
    except Exception as e:  # pragma: no cover
        return JSONResponse({"status": "error", "detail": str(e)[:200]}, status_code=503)


async def openapi(request: Request) -> Response:
    return JSONResponse(openapi_spec())


async def api_docs(request: Request) -> Response:
    html = """<!doctype html><html><head><meta charset="utf-8"><title>EHMS API</title>
<style>body{font-family:system-ui,sans-serif;margin:2rem;color:#0f1f3d}h1{font-size:1.4rem}table{border-collapse:collapse;width:100%}
td,th{border-bottom:1px solid #e5e7eb;padding:.4rem .6rem;text-align:left;font-size:.9rem}code{background:#f3f4f6;padding:1px 4px;border-radius:4px}
.m{font-weight:700;font-family:monospace}.GET{color:#047857}.POST{color:#1d4ed8}.PATCH,.PUT{color:#b45309}.DELETE{color:#b91c1c}</style></head>
<body><h1>EHMS REST API</h1><p>Machine-readable spec: <a href="/api/openapi.json">/api/openapi.json</a> (OpenAPI 3). Authenticate with
<code>Authorization: Bearer &lt;token&gt;</code> from <code>POST /api/auth/login</code>. Money values are integers in minor units (kobo).</p>
<table id="t"><tr><th>Method</th><th>Path</th><th>Summary</th><th>Permission</th></tr></table>
<script>fetch('/api/openapi.json').then(r=>r.json()).then(s=>{const t=document.getElementById('t');
for(const[p,ops]of Object.entries(s.paths))for(const[m,o]of Object.entries(ops)){const tr=document.createElement('tr');
const perm=(o.description||'').replace('Requires permission ','').replace(/`/g,'').replace('.','')||(o.security?'signed in':'public');
tr.innerHTML=`<td class="m ${m.toUpperCase()}">${m.toUpperCase()}</td><td><code>${p}</code></td><td>${o.summary||''}</td><td>${perm}</td>`;t.appendChild(tr)}})</script>
</body></html>"""
    return Response(html, media_type="text/html")


def frontend_build_version(dist: str) -> str | None:
    """Version of the interface build in `dist` (written by frontend/build.mjs), or None for builds before 1.1.1."""
    import json
    try:
        with open(os.path.join(dist, "version.json"), encoding="utf-8") as fh:
            return str(json.load(fh).get("version"))
    except (OSError, ValueError):
        return None


STALE_BANNER = ('<div style="background:#b42318;color:#fff;padding:10px 16px;font:14px system-ui,sans-serif">'
                "<b>This screen is out of date.</b> The interface build (version {ui}) does not match the EHMS server "
                "(version {server}), so some modules and menus are missing. Stop the server and start it from the folder "
                "of the version you unpacked, or run <code>npm run build</code> in the <code>frontend</code> folder, "
                "then press Ctrl+F5.</div>")


async def assetlinks(request: Request) -> Response:
    """Digital Asset Links: lets the EHMS Android app (a trusted web activity) open this site without a browser bar.
    Set EHMS_ANDROID_PACKAGE and EHMS_ANDROID_SHA256 (comma-separated certificate fingerprints, incl. Play App Signing's)."""
    pkg = os.environ.get("EHMS_ANDROID_PACKAGE", "").strip()
    prints = [p.strip().upper() for p in os.environ.get("EHMS_ANDROID_SHA256", "").split(",") if p.strip()]
    body = [{"relation": ["delegate_permission/common.handle_all_urls"],
             "target": {"namespace": "android_app", "package_name": pkg, "sha256_cert_fingerprints": prints}}] if pkg and prints else []
    return JSONResponse(body, headers={"Cache-Control": "public, max-age=3600"})


async def security_txt(request: Request) -> Response:
    contact = os.environ.get("EHMS_SECURITY_CONTACT", "").strip()
    if not contact:
        return Response("Not found", status_code=404)
    url = os.environ.get("EHMS_PUBLIC_URL", "").rstrip("/")
    expires = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=180)).strftime("%Y-%m-%dT00:00:00Z")
    text = f"Contact: {contact if ':' in contact else 'mailto:' + contact}\nExpires: {expires}\nPreferred-Languages: en, fr\n" + (f"Canonical: {url}/.well-known/security.txt\n" if url else "")
    return Response(text, media_type="text/plain")


PRIVACY_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Privacy notice — {name}</title><meta name="robots" content="index"><style>
body{{font:16px/1.6 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:0;background:#f7f7f5;color:#1f2933}}
main{{max-width:760px;margin:0 auto;padding:32px 16px 64px}}h1{{font-size:1.8rem;margin:0 0 4px}}
.body{{white-space:pre-wrap;background:#fff;border:1px solid #e3e3df;border-radius:10px;padding:24px}}a{{color:#0b5c56}}
@media (prefers-color-scheme:dark){{body{{background:#14181b;color:#e6e6e3}}.body{{background:#1c2226;border-color:#2c343a}}a{{color:#6fd1c6}}}}
</style></head><body><main><p><a href="/">&larr; {name}</a></p><h1>Privacy notice</h1><p>{name}</p><div class="body">{text}</div></main></body></html>"""


async def privacy(request: Request) -> Response:
    """Public privacy notice (linked from the website footer, booking form and the Play Store listing)."""
    import html as _h
    from .modules.website import privacy_for_page
    try:
        name, text = await run_in_threadpool(privacy_for_page)
    except Exception:
        name, text = "Our hotel", "Our privacy notice will be published here shortly."
    page = PRIVACY_PAGE.format(name=_h.escape(name), text=_h.escape(text))
    return Response(page, media_type="text/html", headers={"Cache-Control": "no-cache"})


VERIFY_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex"><title>Staff ID check</title><style>
body{{font:16px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;margin:0;background:#f4f5f7;color:#1f2933}}
main{{max-width:420px;margin:0 auto;padding:24px 16px}}.card{{background:#fff;border-radius:14px;border:1px solid #e3e5e8;overflow:hidden}}
.band{{padding:18px 20px;color:#fff;font-weight:700;font-size:1.15rem}}.ok{{background:#14804a}}.bad{{background:#b42318}}
.body{{padding:20px;display:flex;gap:16px;align-items:flex-start}}img{{width:96px;height:120px;object-fit:cover;border-radius:8px;background:#eef0f3}}
h1{{font-size:1.2rem;margin:0 0 4px}}p{{margin:2px 0;color:#4b5563}}small{{display:block;margin-top:16px;color:#6b7280;text-align:center}}
@media (prefers-color-scheme:dark){{body{{background:#14181b;color:#e6e6e3}}.card{{background:#1c2226;border-color:#2c343a}}p,small{{color:#a3acb5}}}}
</style></head><body><main><div class="card"><div class="band {cls}">{icon} {message}</div><div class="body">{photo}<div>
<h1>{name}</h1><p>{position}</p><p>{department}</p><p>{hotel}</p><p>Card {card_no} &middot; expires {expiry}</p></div></div></div>
<small>Checked {checked}. Compare the photo with the person holding the card.</small></main></body></html>"""


async def verify_staff_card(request: Request) -> Response:
    """Page opened by scanning the QR code on a staff ID card."""
    import datetime as _dt
    import html as _h
    from .modules.idcards import verify_token
    token = request.path_params["token"]
    out = await run_in_threadpool(verify_token, token)
    if not out:
        return Response("<!doctype html><title>Unknown card</title><p style='font-family:sans-serif;padding:24px'>This is not a staff ID card of this hotel.</p>",
                        status_code=404, media_type="text/html", headers={"Cache-Control": "no-store"})
    e = {k: _h.escape(str(v)) for k, v in out.items()}
    photo = f'<img src="/api/public/staff-cards/{_h.escape(token)}/photo" alt="Photo of the card holder">' if out["has_photo"] else ""
    page = VERIFY_PAGE.format(cls="ok" if out["valid"] else "bad", icon="&#10004;" if out["valid"] else "&#10006;", message=e["message"], photo=photo,
                              name=e["name"], position=e["position"], department=e["department"], hotel=e["hotel"], card_no=e["card_no"],
                              expiry=e["expiry_date"], checked=_dt.datetime.now().strftime("%d %b %Y %H:%M"))
    return Response(page, media_type="text/html", headers={"Cache-Control": "no-store"})


async def manifest(request: Request) -> Response:
    """Web app manifest for the staff app (installable from the browser; required by the Android app)."""
    name = os.environ.get("EHMS_APP_NAME", "EHMS Staff")
    return JSONResponse({"name": name, "short_name": name[:12], "description": "Hotel management for staff", "id": "/staff",
                         "start_url": "/staff#/", "scope": "/", "display": "standalone", "orientation": "any",
                         "background_color": "#0f1f3d", "theme_color": "#0f1f3d", "lang": "en",
                         "icons": [{"src": "/assets/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any"},
                                   {"src": "/assets/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any"},
                                   {"src": "/assets/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"}]},
                        media_type="application/manifest+json", headers={"Cache-Control": "public, max-age=3600"})


def _frontend_routes() -> list:
    dist = os.path.abspath(settings.frontend_dist)
    if not os.path.isdir(dist):
        log.warning("Frontend build not found at %s — API only. Run `npm run build` in /frontend.", dist)
        return []
    index = os.path.join(dist, "index.html")
    ui = frontend_build_version(dist)
    stale = ui != __version__
    if stale:
        log.warning("Frontend build at %s is version %s but the server is %s — rebuild it (`npm run build` in /frontend).",
                    dist, ui or "unknown (older than 1.1.1)", __version__)

    with open(index, encoding="utf-8") as fh:
        html = fh.read()
    # Give the script and stylesheet an address that changes with their content, so a browser can never run a copy
    # cached from an earlier version (same file name, different code).
    for name in ("main.js", "main.css"):
        path = os.path.join(dist, "assets", name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                digest = hashlib.sha256(fh.read()).hexdigest()[:12]
            html = html.replace(f"/assets/{name}\"", f"/assets/{name}?v={digest}\"")
    if stale:
        banner = STALE_BANNER.format(ui=ui or "older than 1.1.1", server=__version__)
        html = html.replace("<body>", "<body>" + banner, 1) if "<body>" in html else banner + html

    async def spa(request: Request) -> Response:
        page = html
        if not request.url.path.startswith("/staff"):
            # the public website: the hotel's own title and description, for search engines and link previews
            from .modules.website import seo_for_index
            seo = await run_in_threadpool(seo_for_index)
            if seo:
                import html as _h
                title, desc, site = (_h.escape(x, quote=True) for x in seo)
                page = page.replace("<title>EHMS — Enterprise Hotel Management System</title>",
                                    f'<title>{title}</title><meta name="description" content="{desc}" />'
                                    f'<meta property="og:title" content="{title}" /><meta property="og:description" content="{desc}" />'
                                    f'<meta property="og:site_name" content="{site}" /><meta property="og:type" content="website" />', 1)
        return Response(page, media_type="text/html", headers={"Cache-Control": "no-cache"})

    class Assets(StaticFiles):
        # Asset names are not hashed, so browsers must revalidate them (ETag) or they keep an old interface.
        async def get_response(self, path, scope):
            resp = await super().get_response(path, scope)
            resp.headers["Cache-Control"] = "no-cache"
            return resp

    sw = os.path.join(dist, "sw.js")

    async def service_worker(request: Request) -> Response:
        if not os.path.isfile(sw):
            return Response("Not found", status_code=404)
        with open(sw, "rb") as fh:
            return Response(fh.read(), media_type="text/javascript", headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    return [Mount("/assets", app=Assets(directory=os.path.join(dist, "assets")), name="assets"),
            Route("/sw.js", service_worker), Route("/{path:path}", spa)]


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        # the interactive API page uses a small inline script; the application itself runs no inline scripts
        script = b"script-src 'self' 'unsafe-inline'" if scope.get("path") == "/api/docs" else b"script-src 'self'"

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                            (b"referrer-policy", b"strict-origin-when-cross-origin"),
                            (b"permissions-policy", b"camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()"),
                            (b"cross-origin-opener-policy", b"same-origin"), (b"cross-origin-resource-policy", b"same-origin"),
                            (b"x-permitted-cross-domain-policies", b"none"),
                            (b"content-security-policy", b"default-src 'self'; img-src 'self' data: blob: https:; style-src 'self' 'unsafe-inline'; "
                                                         + script + b"; connect-src 'self'; frame-src 'self' blob:; object-src 'none'; base-uri 'self'; "
                                                         b"form-action 'self'; frame-ancestors 'none'")]
                if settings.environment == "production":
                    headers.append((b"strict-transport-security", b"max-age=63072000; includeSubDomains; preload"))
                message["headers"] = headers
            await send(message)
        await self.app(scope, receive, send_wrapper)


def check_production_settings() -> None:
    """Refuse to start a production server while any go-live check fails (see `python -m ehms.preflight`)."""
    if settings.environment != "production":
        return
    from .preflight import errors
    problems = errors()
    if settings.seed_demo and os.environ.get("EHMS_ALLOW_DEMO_IN_PRODUCTION") == "1":
        problems = [p for p in problems if not p.startswith("Demo data")]
    if problems:
        raise RuntimeError("EHMS will not start in production until these are fixed:\n- " + "\n- ".join(problems))


def api_docs_enabled() -> bool:
    return os.environ.get("EHMS_API_DOCS", "0" if settings.environment == "production" else "1") == "1"


def create_app() -> Starlette:
    check_production_settings()
    middleware = [Middleware(SecurityHeaders)]
    if settings.cors_origins:
        middleware.append(Middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                                     allow_headers=["Authorization", "Content-Type"]))
    routes = [Route("/api/health", health)] + ([Route("/api/openapi.json", openapi), Route("/api/docs", api_docs)] if api_docs_enabled() else [])
    routes += [Route("/.well-known/assetlinks.json", assetlinks), Route("/.well-known/security.txt", security_txt), Route("/manifest.webmanifest", manifest),
               Route("/privacy", privacy), Route("/verify/staff/{token}", verify_staff_card)]
    routes += starlette_routes()
    routes += _frontend_routes()

    @contextlib.asynccontextmanager
    async def lifespan(app):
        applied = migrate()
        if applied:
            log.info("Applied migrations: %s", applied)
        from .rbac import apply_permission_upgrades
        from .services import seed_chart_of_accounts
        with get_db().tx() as c:
            for org in c.all("SELECT id FROM organisations"):
                seed_chart_of_accounts(c, org["id"])
                if apply_permission_upgrades(c, org["id"]):
                    log.info("Granted new release permissions to system roles for organisation %s", org["id"])
        if settings.seed_demo:
            from .seed import seed_demo
            seed_demo()
        from .crypto import encrypt_existing
        n = await asyncio.to_thread(encrypt_existing, get_db())
        if n:
            log.info("Encrypted %s sensitive values stored before release 1.4", n)
        from . import worker
        task = asyncio.create_task(worker.loop(int(os.environ.get("EHMS_WORKER_INTERVAL", "60")))) if worker.enabled() else None
        yield
        if task:
            task.cancel()

    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


app = create_app()
