"""Thin database layer supporting PostgreSQL (production) and SQLite (development/tests).

Queries are written with ``?`` placeholders and portable SQL. For PostgreSQL the
placeholders are rewritten to ``%s`` and the ``psycopg`` driver is used.
All money is stored as integer minor units (kobo for NGN) to avoid rounding errors.
"""
from __future__ import annotations

import datetime as _dt
import decimal
import re
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

from .config import settings


class DBError(Exception):
    pass


class IntegrityError(DBError):
    pass


def _norm(v: Any) -> Any:
    if isinstance(v, _dt.datetime):
        if v.tzinfo is None:
            v = v.replace(tzinfo=_dt.timezone.utc)
        return v.astimezone(_dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    return v


class Connection:
    """Wraps a DB-API connection with dict rows and a common API."""

    def __init__(self, raw: Any, dialect: str):
        self.raw = raw
        self.dialect = dialect

    def _sql(self, sql: str) -> str:
        if self.dialect == "postgresql":
            return re.sub(r"\?", "%s", sql)
        return sql

    def execute(self, sql: str, params: tuple | list = ()) -> Any:
        try:
            cur = self.raw.cursor()
            cur.execute(self._sql(sql), tuple(params))
            return cur
        except sqlite3.IntegrityError as e:
            raise IntegrityError(str(e)) from e
        except Exception as e:  # psycopg errors
            name = type(e).__name__
            if "Integrity" in name or "UniqueViolation" in name or "ForeignKey" in name or "CheckViolation" in name:
                raise IntegrityError(str(e)) from e
            if "RaiseException" in name:
                raise IntegrityError(str(e)) from e
            raise

    def all(self, sql: str, params: tuple | list = ()) -> list[dict]:
        cur = self.execute(sql, params)
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [{c: _norm(v) for c, v in zip(cols, row)} for row in cur.fetchall()]

    def one(self, sql: str, params: tuple | list = ()) -> dict | None:
        rows = self.all(sql, params)
        return rows[0] if rows else None

    def scalar(self, sql: str, params: tuple | list = ()) -> Any:
        cur = self.execute(sql, params)
        row = cur.fetchone()
        return _norm(row[0]) if row else None

    def insert(self, table: str, data: dict) -> int:
        cols = list(data.keys())
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)}) RETURNING id"
        return int(self.scalar(sql, [data[c] for c in cols]))

    def update(self, table: str, row_id: int, data: dict) -> None:
        if not data:
            return
        sets = ", ".join(f"{c} = ?" for c in data)
        self.execute(f"UPDATE {table} SET {sets} WHERE id = ?", [*data.values(), row_id])

    def lock(self, table: str, row_id: int) -> dict | None:
        """Lock a row for the rest of the transaction (PostgreSQL); SQLite transactions
        are already serialised by BEGIN IMMEDIATE."""
        if self.dialect == "postgresql":
            return self.one(f"SELECT * FROM {table} WHERE id = ? FOR UPDATE", [row_id])
        return self.one(f"SELECT * FROM {table} WHERE id = ?", [row_id])


class Database:
    def __init__(self, url: str):
        self.url = url
        if url.startswith("sqlite"):
            self.dialect = "sqlite"
            path = url.split("sqlite:///", 1)[1] if "sqlite:///" in url else ":memory:"
            self.path = path or ":memory:"
            self._local = threading.local()
            self._memory_conn = None
            if self.path == ":memory:":
                # one shared connection for in-memory DBs (tests)
                self._memory_conn = self._new_sqlite()
                self._lock = threading.RLock()
        elif url.startswith("postgres"):
            self.dialect = "postgresql"
            try:
                import psycopg  # noqa: F401
            except ImportError as e:  # pragma: no cover
                raise DBError("PostgreSQL requires the 'psycopg' package (pip install psycopg[binary])") from e
        else:
            raise DBError(f"Unsupported DATABASE_URL: {url}")

    def _new_sqlite(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None, timeout=30)
        c.execute("PRAGMA foreign_keys = ON")
        c.execute("PRAGMA journal_mode = WAL") if self.path != ":memory:" else None
        return c

    def _raw(self):
        if self.dialect == "sqlite":
            if self._memory_conn is not None:
                return self._memory_conn
            c = getattr(self._local, "conn", None)
            if c is None:
                c = self._new_sqlite()
                self._local.conn = c
            return c
        import psycopg
        return psycopg.connect(self.url, autocommit=False)

    @contextmanager
    def tx(self) -> Iterator[Connection]:
        """Run a block inside a single database transaction."""
        if self.dialect == "sqlite":
            lock = getattr(self, "_lock", None)
            if lock:
                lock.acquire()
            raw = self._raw()
            try:
                raw.execute("BEGIN IMMEDIATE")
                conn = Connection(raw, "sqlite")
                try:
                    yield conn
                    raw.execute("COMMIT")
                except BaseException:
                    raw.execute("ROLLBACK")
                    raise
            finally:
                if lock:
                    lock.release()
        else:
            raw = self._raw()
            conn = Connection(raw, "postgresql")
            try:
                yield conn
                raw.commit()
            except BaseException:
                raw.rollback()
                raise
            finally:
                raw.close()

    def executescript(self, script: str) -> None:
        if self.dialect == "sqlite":
            lock = getattr(self, "_lock", None)
            if lock:
                lock.acquire()
            try:
                self._raw().executescript(script)
            finally:
                if lock:
                    lock.release()
        else:
            raw = self._raw()
            try:
                raw.execute(script)
                raw.commit()
            finally:
                raw.close()


_db: Database | None = None


def get_db() -> Database:
    global _db
    if _db is None:
        _db = Database(settings.database_url)
    return _db


def set_db(db: Database) -> None:
    global _db
    _db = db


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
