"""Regenerate docs/API.md from the route table:  cd backend && python -m ehms.apidoc > ../docs/API.md"""
from __future__ import annotations

from collections import defaultdict

from . import modules  # noqa: F401  (registers routes)
from .http import ROUTES

HEADER = """# EHMS REST API reference

Generated from the route table (`python -m ehms.apidoc`). The live, machine-readable OpenAPI 3 spec is served at `/api/openapi.json`, with a browsable list at `/api/docs`.

**Conventions**

- Authenticate with `POST /api/auth/login`, then send `Authorization: Bearer <token>` on every request.
- Request and response bodies are JSON. Money values are **integers in minor units** (kobo for NGN): ₦45,000.00 is `4500000`.
- Stock quantities are decimals in the item's unit with up to 3 decimal places (`0.25` kg); they are stored exactly as thousandths.
- Dates are `YYYY-MM-DD`; timestamps are ISO-8601 UTC.
- Errors return `{"error": {"code", "message", "details"}}` with HTTP 400 (validation), 401 (sign-in), 403 (permission/scope), 404, 409 (conflict, e.g. double booking, unsettled balance, insufficient stock), 423 (account locked), 429 (rate limit), 501 (integration not configured).
- Payments require an `idempotency_key`; repeating a request with the same key never creates a second payment.
"""


def main() -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for r in ROUTES:
        groups[r["tag"]].append(r)
    print(HEADER)
    print(f"Total endpoints: **{len(ROUTES)}**\n")
    for tag in sorted(groups):
        nice = {"pos": "POS (restaurant, bar, room service)", "booking-engine": "Booking engine (public)", "frontdesk": "Front desk"}
        print(f"## {nice.get(tag, tag.replace('_', ' ').replace('-', ' ').capitalize())}\n")
        print("| Method | Path | Purpose | Access |\n|---|---|---|---|")
        for r in groups[tag]:
            path = "/".join(("{" + p.strip("{}").split(":")[0] + "}") if p.startswith("{") else p for p in r["path"].split("/"))
            access = f"`{r['perm']}`" if r["perm"] else ("public" if r["public"] else "signed in")
            print(f"| {r['method']} | `{path}` | {r['summary'].replace('|', '/')} | {access} |")
        print()


if __name__ == "__main__":
    main()
