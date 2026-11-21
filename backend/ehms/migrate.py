"""Applies SQL migrations in /backend/migrations in filename order.

Run:  python -m ehms.migrate            (uses DATABASE_URL)
      python -m ehms.migrate --render postgresql > schema.sql   (print rendered DDL)
"""
from __future__ import annotations

import os
import re
import sys

from .db import Database, get_db, now_iso

MIGRATIONS_DIR = os.path.join(os.path.dirname(__file__), "..", "migrations")

TOKENS = {
    "sqlite": {"{PK}": "INTEGER PRIMARY KEY AUTOINCREMENT", "{REF}": "INTEGER", "{DATE}": "TEXT",
               "{TS}": "TEXT", "{MONEY}": "INTEGER"},
    "postgresql": {"{PK}": "BIGSERIAL PRIMARY KEY", "{REF}": "BIGINT", "{DATE}": "DATE",
                   "{TS}": "TIMESTAMPTZ", "{MONEY}": "BIGINT"},
}


def render(sql: str, dialect: str) -> str:
    # keep only the blocks for this dialect (blocks start with "-- @dialect name")
    if "-- @dialect" in sql:
        parts = re.split(r"^-- @dialect (\w+)\s*$", sql, flags=re.M)
        head, rest = parts[0], parts[1:]
        chosen = [head]
        for i in range(0, len(rest), 2):
            if rest[i] == dialect:
                chosen.append(rest[i + 1])
        sql = "\n".join(chosen)
    for k, v in TOKENS[dialect].items():
        sql = sql.replace(k, v)
    return sql


def migration_files() -> list[str]:
    return sorted(f for f in os.listdir(MIGRATIONS_DIR) if re.match(r"^\d{4}_.*\.sql$", f))


def migrate(db: Database | None = None) -> list[str]:
    db = db or get_db()
    db.executescript("CREATE TABLE IF NOT EXISTS schema_migrations (version VARCHAR(100) PRIMARY KEY, applied_at VARCHAR(40) NOT NULL);")
    with db.tx() as c:
        done = {r["version"] for r in c.all("SELECT version FROM schema_migrations")}
    applied = []
    for f in migration_files():
        if f in done:
            continue
        with open(os.path.join(MIGRATIONS_DIR, f), encoding="utf-8") as fh:
            sql = render(fh.read(), db.dialect)
        db.executescript(sql)
        with db.tx() as c:
            c.execute("INSERT INTO schema_migrations (version, applied_at) VALUES (?, ?)", [f, now_iso()])
        applied.append(f)
    return applied


if __name__ == "__main__":  # pragma: no cover
    if len(sys.argv) > 2 and sys.argv[1] == "--render":
        for f in migration_files():
            with open(os.path.join(MIGRATIONS_DIR, f), encoding="utf-8") as fh:
                print(f"-- {f}\n" + render(fh.read(), sys.argv[2]))
    else:
        print("Applied:", migrate() or "nothing (up to date)")
