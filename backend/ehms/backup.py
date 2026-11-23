"""Database backup, verification and restore (release 1.2).

A backup is one ZIP file in EHMS_BACKUP_DIR (default ./data/backups) holding every table as JSON lines, the stored
documents and room photos, and a manifest with row counts and SHA-256 checksums. Backups work the same on SQLite and
PostgreSQL, and a backup taken on one can be restored into the other.

Verification re-reads the archive, checks every checksum and count, then performs a real test restore into a
temporary SQLite database built from the current migrations and compares the row counts table by table.

Restore (into an EMPTY database, with EHMS stopped):
    python -m ehms.backup restore data/backups/ehms-backup-20261123T020000Z.zip
    (uses DATABASE_URL; documents are restored into EHMS_DOCUMENT_DIR)
Other commands:  python -m ehms.backup create | verify <file> | list
"""
from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import os
import sys
import tempfile
import zipfile

from . import __version__
from .db import Database, get_db

FORMAT = "ehms-backup/1"
SKIP_TABLES = {"schema_migrations"}


def backup_dir() -> str:
    d = os.environ.get("EHMS_BACKUP_DIR") or os.path.join(os.getcwd(), "data", "backups")
    os.makedirs(d, exist_ok=True)
    return d


def _tables(c) -> list[str]:
    if c.dialect == "sqlite":
        rows = c.all("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
        names = [r["name"] for r in rows]
    else:
        rows = c.all("SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' ORDER BY table_name")
        names = [r["table_name"] for r in rows]
    return [n for n in names if n not in SKIP_TABLES]


def _foreign_keys(c, table: str) -> list[tuple[str, str]]:
    """[(column, referenced table)]"""
    if c.dialect == "sqlite":
        return [(r["from"], r["table"]) for r in c.all(f"PRAGMA foreign_key_list({c._ident(table)})")]
    return [(r["column_name"], r["ref_table"]) for r in c.all(
        "SELECT kcu.column_name, ccu.table_name AS ref_table FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema "
        "JOIN information_schema.constraint_column_usage ccu ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema "
        "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_name = ? AND tc.table_schema = current_schema()", [table])]


def _files_root() -> str:
    from .modules.documents import storage_dir
    return storage_dir()


def create_backup(kind: str = "manual", user_id: int | None = None, db: Database | None = None, include_files: bool = True) -> dict:
    """Write a backup archive and record it in the backups table. Returns the backup row."""
    db = db or get_db()
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    name = f"ehms-backup-{stamp}.zip"
    path = os.path.join(backup_dir(), name)
    n = 1
    while os.path.exists(path):
        n += 1
        name = f"ehms-backup-{stamp}-{n}.zip"
        path = os.path.join(backup_dir(), name)
    manifest: dict = {"format": FORMAT, "ehms_version": __version__, "created_at": stamp, "dialect": db.dialect, "tables": {}, "files": {}}
    try:
        with db.tx() as c:
            versions = [r["version"] for r in c.all("SELECT version FROM schema_migrations ORDER BY version")]
            manifest["migrations"] = versions
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as z:
                for t in _tables(c):
                    if t == "backups":
                        continue  # the backup register describes the archives themselves
                    rows = c.all(f"SELECT * FROM {c._ident(t)} ORDER BY 1")
                    data = "".join(json.dumps(r, default=str, separators=(",", ":")) + "\n" for r in rows).encode("utf-8")
                    z.writestr(f"tables/{t}.jsonl", data)
                    manifest["tables"][t] = {"rows": len(rows), "sha256": hashlib.sha256(data).hexdigest()}
                if include_files:
                    root = _files_root()
                    for dirpath, _, files in os.walk(root):
                        for f in files:
                            full = os.path.join(dirpath, f)
                            rel = os.path.relpath(full, root).replace("\\", "/")
                            if rel.startswith(".."):
                                continue
                            with open(full, "rb") as fh:
                                blob = fh.read()
                            z.writestr(f"files/{rel}", blob)
                            manifest["files"][rel] = hashlib.sha256(blob).hexdigest()
                z.writestr("manifest.json", json.dumps(manifest, indent=1))
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            checksum = hashlib.sha256(fh.read()).hexdigest()
        row = {"filename": name, "kind": kind, "status": "ok", "size_bytes": size, "tables_count": len(manifest["tables"]),
               "rows_count": sum(t["rows"] for t in manifest["tables"].values()), "checksum": checksum, "verified": 0,
               "created_by": user_id, "created_at": _now()}
    except Exception as e:  # record the failure so it is visible and alerted
        try:
            os.remove(path)
        except OSError:
            pass
        row = {"filename": name, "kind": kind, "status": "failed", "error": f"{type(e).__name__}: {e}"[:500], "verified": 0,
               "created_by": user_id, "created_at": _now()}
    with db.tx() as c:
        row["id"] = c.insert("backups", row)
    return row


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def read_archive(path: str) -> tuple[dict, dict[str, list[dict]], dict[str, bytes]]:
    """Open and fully check an archive. Raises ValueError with a readable reason when anything is wrong."""
    with zipfile.ZipFile(path) as z:
        bad = z.testzip()
        if bad:
            raise ValueError(f"Corrupt entry in archive: {bad}")
        manifest = json.loads(z.read("manifest.json"))
        if manifest.get("format") != FORMAT:
            raise ValueError("Not an EHMS backup archive")
        tables: dict[str, list[dict]] = {}
        for t, meta in manifest["tables"].items():
            data = z.read(f"tables/{t}.jsonl")
            if hashlib.sha256(data).hexdigest() != meta["sha256"]:
                raise ValueError(f"Checksum mismatch in table {t}")
            rows = [json.loads(line) for line in data.decode("utf-8").splitlines() if line]
            if len(rows) != meta["rows"]:
                raise ValueError(f"Row count mismatch in table {t}")
            tables[t] = rows
        files: dict[str, bytes] = {}
        for rel, sha in manifest.get("files", {}).items():
            blob = z.read(f"files/{rel}")
            if hashlib.sha256(blob).hexdigest() != sha:
                raise ValueError(f"Checksum mismatch in file {rel}")
            files[rel] = blob
    return manifest, tables, files


def _nullable(c, table: str) -> set[str]:
    if c.dialect == "sqlite":
        return {r["name"] for r in c.all(f"PRAGMA table_info({c._ident(table)})") if not r["notnull"] and not r["pk"]}
    return {r["column_name"] for r in c.all("SELECT column_name FROM information_schema.columns WHERE table_schema = current_schema() "
                                           "AND table_name = ? AND is_nullable = 'YES'", [table])}


def _order(c, tables: list[str]) -> tuple[list[str], dict[str, list[str]]]:
    """Insert order honouring foreign keys, plus the columns to fill in afterwards (self-references, and one nullable
    link of every circular group such as reservations → group blocks → folios → reservations)."""
    fks = {t: _foreign_keys(c, t) for t in tables}
    deps = {t: {ref for _, ref in fks[t] if ref != t and ref in tables} for t in tables}
    deferred: dict[str, list[str]] = {t: [col for col, ref in fks[t] if ref == t] for t in tables}
    order: list[str] = []
    remaining = {t: set(d) for t, d in deps.items()}
    while remaining:
        ready = sorted(t for t, d in remaining.items() if not (d - set(order)))
        if ready:
            for t in ready:
                order.append(t)
                remaining.pop(t)
            continue
        # stuck: find tables that are part of a cycle (they can reach themselves) and break one nullable link
        def reaches(start: str, goal: str) -> bool:
            seen, todo = set(), [start]
            while todo:
                x = todo.pop()
                for r in remaining.get(x, ()):
                    if r == goal:
                        return True
                    if r not in seen and r in remaining:
                        seen.add(r)
                        todo.append(r)
            return False
        members = sorted(t for t in remaining if reaches(t, t))
        broke = False
        for t in members:
            nullable = _nullable(c, t)
            cols = [(col, ref) for col, ref in fks[t] if ref in remaining and ref != t and ref in members and col in nullable]
            if cols:
                for col, ref in cols:
                    deferred[t].append(col)
                remaining[t] -= {ref for _, ref in cols}
                broke = True
                break
        if not broke:
            raise ValueError(f"Cannot order tables for restore (circular required links among {', '.join(members)})")
    return order, deferred


def restore_into(db: Database, tables: dict[str, list[dict]], require_empty: bool = True) -> dict[str, int]:
    """Load backup rows into a database whose schema is already migrated. Returns inserted counts."""
    counts: dict[str, int] = {}
    with db.tx() as c:
        present = _tables(c)
        if require_empty:
            busy = [t for t in present if t in tables and t not in ("backups",) and c.scalar(f"SELECT COUNT(*) FROM {c._ident(t)}")]
            if busy:
                raise ValueError(f"The target database is not empty (e.g. {', '.join(busy[:5])}); restore into a new, empty database")
        order, deferred = _order(c, [t for t in present if t in tables])
        later: list[tuple[str, int, dict]] = []
        for t in order:
            cols_present = None
            for row in tables[t]:
                if cols_present is None:
                    cols_present = {r for r in row}
                data = dict(row)
                hold = {k: data[k] for k in deferred.get(t, []) if data.get(k) is not None}
                for k in hold:
                    data[k] = None
                cols = [c._ident(k) for k in data]
                c.execute(f"INSERT INTO {c._ident(t)} ({', '.join(cols)}) VALUES ({', '.join('?' for _ in cols)})", [data[k] for k in data])
                if hold:
                    later.append((t, row["id"], hold))
            counts[t] = len(tables[t])
        for t, rid, hold in later:
            c.update(t, rid, hold)
        if c.dialect == "postgresql":
            for t in order:
                if tables[t] and "id" in tables[t][0]:
                    c.execute(f"SELECT setval(pg_get_serial_sequence('{c._ident(t)}', 'id'), (SELECT COALESCE(MAX(id), 1) FROM {c._ident(t)}))")
    return counts


def verify(path: str) -> dict:
    """Check the archive and test-restore it into a temporary SQLite database."""
    from .migrate import migrate
    manifest, tables, files = read_archive(path)
    with tempfile.TemporaryDirectory() as tmp:
        test = Database(f"sqlite:///{os.path.join(tmp, 'restore-test.db')}")
        try:
            migrate(test)
            counts = restore_into(test, tables)
            with test.tx() as c:
                for t, n in counts.items():
                    actual = c.scalar(f"SELECT COUNT(*) FROM {c._ident(t)}")
                    if actual != n:
                        raise ValueError(f"Test restore of {t}: expected {n} rows, found {actual}")
        finally:
            test.close()
    return {"ok": True, "tables": len(tables), "rows": sum(len(v) for v in tables.values()), "files": len(files),
            "ehms_version": manifest.get("ehms_version"), "created_at": manifest.get("created_at")}


def restore(path: str, db: Database | None = None) -> dict:
    from .migrate import migrate
    db = db or get_db()
    manifest, tables, files = read_archive(path)
    migrate(db)
    counts = restore_into(db, tables)
    root = _files_root()
    for rel, blob in files.items():
        dest = os.path.normpath(os.path.join(root, rel))
        if not dest.startswith(os.path.normpath(root)):
            continue  # never write outside the documents directory
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(blob)
    return {"tables": len(counts), "rows": sum(counts.values()), "files": len(files), "from_version": manifest.get("ehms_version")}


def apply_retention(db: Database | None = None, days: int | None = None) -> int:
    """Delete scheduled backups older than the retention period (manual backups are kept until deleted)."""
    db = db or get_db()
    days = days if days is not None else int(os.environ.get("EHMS_BACKUP_RETENTION_DAYS", "14"))
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).isoformat()
    removed = 0
    with db.tx() as c:
        for b in c.all("SELECT * FROM backups WHERE kind = 'scheduled' AND created_at < ?", [cutoff]):
            try:
                os.remove(os.path.join(backup_dir(), os.path.basename(b["filename"])))
            except OSError:
                pass
            c.execute("DELETE FROM backups WHERE id = ?", [b["id"]])
            removed += 1
    return removed


def _main(argv: list[str]) -> int:  # pragma: no cover - command line
    if not argv or argv[0] not in ("create", "verify", "restore", "list"):
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "create":
        from .migrate import migrate
        migrate()
        row = create_backup("manual")
        print(json.dumps(row, indent=1))
        return 0 if row["status"] == "ok" else 1
    if cmd == "list":
        with get_db().tx() as c:
            for b in c.all("SELECT * FROM backups ORDER BY id DESC"):
                print(b["created_at"], b["status"], b["kind"], b["filename"], b["size_bytes"])
        return 0
    if len(argv) < 2:
        print("Give the backup file")
        return 2
    try:
        out = verify(argv[1]) if cmd == "verify" else restore(argv[1])
    except (ValueError, zipfile.BadZipFile, KeyError) as e:
        print(f"FAILED: {e}")
        return 1
    print(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(_main(sys.argv[1:]))
