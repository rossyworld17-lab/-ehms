"""Minimal synchronous ASGI test client (no external dependencies)."""
from __future__ import annotations

import asyncio
import json
from urllib.parse import urlencode


class Resp:
    def __init__(self, status: int, headers: dict, body: bytes):
        self.status_code, self.headers, self.content = status, headers, body

    def json(self):
        return json.loads(self.content or b"null")

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", "replace")


class Client:
    def __init__(self, app):
        self.app = app
        self.token: str | None = None
        self.loop = asyncio.new_event_loop()
        self._lifespan()

    def _lifespan(self):
        async def run():
            q_in: asyncio.Queue = asyncio.Queue()
            q_out: asyncio.Queue = asyncio.Queue()
            await q_in.put({"type": "lifespan.startup"})

            async def receive():
                return await q_in.get()

            async def send(m):
                await q_out.put(m)
            task = asyncio.ensure_future(self.app({"type": "lifespan", "asgi": {"version": "3.0"}, "state": {}}, receive, send))
            msg = await q_out.get()
            if msg["type"] != "lifespan.startup.complete":
                raise RuntimeError(msg)
            self._lifespan_task, self._lifespan_q = task, q_in
        self.loop.run_until_complete(run())

    def close(self):
        async def stop():
            await self._lifespan_q.put({"type": "lifespan.shutdown"})
            try:
                await asyncio.wait_for(self._lifespan_task, 5)
            except Exception:
                pass
        self.loop.run_until_complete(stop())
        self.loop.close()

    def request(self, method: str, path: str, json_body=None, params=None, token: str | None = "default", headers=None) -> Resp:
        if params:
            path += ("&" if "?" in path else "?") + urlencode(params)
        raw_path, _, qs = path.partition("?")
        body = json.dumps(json_body).encode() if json_body is not None else b""
        hdrs = [(b"content-type", b"application/json"), (b"user-agent", b"pytest")]
        tok = self.token if token == "default" else token
        if tok:
            hdrs.append((b"authorization", f"Bearer {tok}".encode()))
        for k, v in (headers or {}).items():
            hdrs.append((k.lower().encode(), v.encode()))
        scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http",
                 "path": raw_path, "raw_path": raw_path.encode(), "query_string": qs.encode(), "headers": hdrs,
                 "client": ("127.0.0.1", 5000), "server": ("testserver", 80), "root_path": ""}
        out = {"status": 500, "headers": {}, "body": b""}

        async def run():
            sent = False

            async def receive():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                await asyncio.sleep(3600)

            async def send(m):
                if m["type"] == "http.response.start":
                    out["status"] = m["status"]
                    out["headers"] = {k.decode(): v.decode() for k, v in m.get("headers", [])}
                elif m["type"] == "http.response.body":
                    out["body"] += m.get("body", b"")
            await self.app(scope, receive, send)
        self.loop.run_until_complete(run())
        return Resp(out["status"], out["headers"], out["body"])

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, json=None, **kw):
        return self.request("POST", path, json_body=json if json is not None else {}, **kw)

    def patch(self, path, json=None, **kw):
        return self.request("PATCH", path, json_body=json or {}, **kw)

    def put(self, path, json=None, **kw):
        return self.request("PUT", path, json_body=json or {}, **kw)

    def delete(self, path, **kw):
        return self.request("DELETE", path, **kw)

    def login(self, email: str, password: str = "Demo@12345") -> dict:
        r = self.post("/api/auth/login", {"email": email, "password": password}, token=None)
        assert r.status_code == 200, r.text
        self.token = r.json()["token"]
        return r.json()
