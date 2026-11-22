"""Simple load test (no extra dependencies).

    python tools/loadtest.py --base http://localhost:8000 --users 20 --seconds 60

Signs in a few demo accounts, then runs N concurrent virtual users for the given time. Each user repeats a mix of
typical requests (dashboard, room board, arrivals, availability, a folio, reservations search, an occupancy report,
BI analytics, an assistant question, a POS order list) with a short think time, and the script reports throughput,
error count and response-time percentiles per request type. Use it against a staging copy, never production data.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
import threading
import time
import urllib.error
import urllib.request
from collections import defaultdict


def call(base: str, method: str, path: str, token: str | None = None, body: dict | None = None) -> tuple[int, float, bytes]:
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {token}"} if token else {})})
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            return r.status, time.perf_counter() - t, data
    except urllib.error.HTTPError as e:
        return e.code, time.perf_counter() - t, e.read()
    except Exception:
        return 0, time.perf_counter() - t, b""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=20)
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--think", type=float, default=0.2, help="seconds between a user's requests")
    ap.add_argument("--password", default="Demo@12345")
    a = ap.parse_args()

    tokens = []
    for email in ("gm@demo.ehms", "admin@demo.ehms"):
        st, _, data = call(a.base, "POST", "/api/auth/login", body={"email": email, "password": a.password})
        if st != 200:
            raise SystemExit(f"login failed for {email}: {st} {data[:200]!r}")
        tokens.append(json.loads(data)["token"])
    st, _, data = call(a.base, "GET", "/api/hotels", tokens[0])
    hid = json.loads(data)["items"][0]["id"]
    st, _, data = call(a.base, "GET", f"/api/hotels/{hid}/reservations?status=checked_in", tokens[0])
    items = json.loads(data).get("items", [])
    res_id = items[0]["id"] if items else None
    import datetime as dt
    today = dt.date.today().isoformat()
    later = (dt.date.today() + dt.timedelta(days=2)).isoformat()
    mix = [
        ("dashboard", "GET", f"/api/hotels/{hid}/dashboard", None, 3),
        ("room board", "GET", f"/api/hotels/{hid}/rooms", None, 3),
        ("arrivals", "GET", f"/api/hotels/{hid}/reservations?arrival={today}", None, 2),
        ("availability", "GET", f"/api/hotels/{hid}/availability?arrival={today}&departure={later}", None, 3),
        ("reservations search", "GET", f"/api/hotels/{hid}/reservations?q=a", None, 2),
        ("occupancy report", "GET", f"/api/hotels/{hid}/reports/occupancy", None, 1),
        ("bi analytics", "GET", "/api/bi/analytics?granularity=week", None, 1),
        ("assistant", "POST", "/api/assistant/ask", {"question": "How full are we tonight?", "hotel_id": hid}, 1),
        ("pos orders", "GET", f"/api/hotels/{hid}/pos/orders?status=open", None, 1),
    ]
    if res_id:
        mix.append(("folio", "GET", f"/api/reservations/{res_id}/folio", None, 2))
    weighted = [m for m in mix for _ in range(m[4])]
    times: dict[str, list[float]] = defaultdict(list)
    errors: dict[str, int] = defaultdict(int)
    lock = threading.Lock()
    stop = time.time() + a.seconds

    def user(i: int) -> None:
        tok = tokens[i % len(tokens)]
        while time.time() < stop:
            name, method, path, body, _ = random.choice(weighted)
            st, dt, _ = call(a.base, method, path, tok, body)
            with lock:
                times[name].append(dt)
                if st >= 400 or st == 0:
                    errors[f"{name} ({st})"] += 1
            time.sleep(a.think * random.uniform(0.5, 1.5))

    threads = [threading.Thread(target=user, args=(i,)) for i in range(a.users)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - t0
    total = sum(len(v) for v in times.values())
    allt = sorted(x for v in times.values() for x in v)

    def pct(v: list[float], p: float) -> float:
        return sorted(v)[min(len(v) - 1, int(len(v) * p))] * 1000

    print(f"{a.users} users, {elapsed:.0f} s: {total} requests, {total / elapsed:.1f} req/s, {sum(errors.values())} errors")
    print(f"{'request':22} {'n':>6} {'p50 ms':>8} {'p95 ms':>8} {'p99 ms':>8}")
    for name in sorted(times):
        v = times[name]
        print(f"{name:22} {len(v):>6} {statistics.median(v) * 1000:>8.0f} {pct(v, .95):>8.0f} {pct(v, .99):>8.0f}")
    print(f"{'ALL':22} {total:>6} {statistics.median(allt) * 1000:>8.0f} {pct(allt, .95):>8.0f} {pct(allt, .99):>8.0f}")
    if errors:
        print("errors:", dict(errors))


if __name__ == "__main__":
    main()
