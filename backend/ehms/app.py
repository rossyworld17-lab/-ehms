"""ASGI application entry point.

Run (development):  uvicorn ehms.app:app --reload --port 8000
"""
from __future__ import annotations

import contextlib
import logging
import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Mount, Route
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


def _frontend_routes() -> list:
    dist = os.path.abspath(settings.frontend_dist)
    if not os.path.isdir(dist):
        log.warning("Frontend build not found at %s — API only. Run `npm run build` in /frontend.", dist)
        return []
    index = os.path.join(dist, "index.html")

    async def spa(request: Request) -> Response:
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return [Mount("/assets", app=StaticFiles(directory=os.path.join(dist, "assets")), name="assets"),
            Route("/{path:path}", spa)]


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers += [(b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                            (b"referrer-policy", b"strict-origin-when-cross-origin"),
                            (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
                            (b"content-security-policy", b"default-src 'self'; img-src 'self' data: https:; style-src 'self' 'unsafe-inline'; "
                                                         b"script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'")]
                if settings.environment == "production":
                    headers.append((b"strict-transport-security", b"max-age=31536000; includeSubDomains"))
                message["headers"] = headers
            await send(message)
        await self.app(scope, receive, send_wrapper)


def create_app() -> Starlette:
    middleware = [Middleware(SecurityHeaders)]
    if settings.cors_origins:
        middleware.append(Middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"],
                                     allow_headers=["Authorization", "Content-Type"]))
    routes = [Route("/api/health", health), Route("/api/openapi.json", openapi), Route("/api/docs", api_docs)] + starlette_routes()
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
        yield

    return Starlette(routes=routes, middleware=middleware, lifespan=lifespan)


app = create_app()
