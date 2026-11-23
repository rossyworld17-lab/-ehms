"""Generate the data dictionary and entity-relationship diagram from the live schema.

Run:  python -m ehms.datadict > ../docs/DATA_DICTIONARY.md
It builds a temporary SQLite database from the migrations, so the document always matches the code."""
from __future__ import annotations

import os
import re
import tempfile

from . import __version__
from .db import Database
from .migrate import MIGRATIONS_DIR, migrate, migration_files

GROUPS = [
    ("Organisation, users and security", r"^(organisations|hotels|departments|users|roles|permissions|role_permissions|user_roles|user_hotels|sessions|login_attempts|password_resets|audit_logs|system_settings|number_sequences|sequences|job_runs|backups|schema)"),
    ("Rooms, guests and reservations", r"^(room|rooms|guests|reservation|rate_|promo|group|cancellation|wake_up|referral|availability|public_bookings)"),
    ("Folios, payments and billing", r"^(folio|payment|online_|gateway_|refund|approval|customer_notes|exchange_rates|invoice)"),
    ("Accounting and finance", r"^(accounts|journal|accounting_|tax|budget|bank_|expense|petty_cash)"),
    ("Restaurant, bar and kitchen", r"^(outlets|pos_|menu|recipe|order|kitchen|cashier|table_reservations)"),
    ("Inventory and procurement", r"^(stores|inventory|stock|supplier|purchase|goods_|quotation|requisition|procurement)"),
    ("Housekeeping and laundry", r"^(housekeeping|laundry|linen)"),
    ("Human resources and payroll", r"^(employee|leave|attendance|shift|roster|payroll|payslip|statutory|staff_|appraisals|trainings|public_holidays|welfare|job_|applicant|recruit|hr_)"),
    ("Maintenance, security and events", r"^(asset|maintenance|work_order|preventive|incident|security_|visitor|lost_|access_|emergency|venue|event)"),
    ("Guest relations, sales and revenue", r"^(loyalty|complaint|feedback|survey|campaign|corporate|agent|sales|season|pricing|competitor|crm)"),
    ("Intelligence, documents and messaging", r"^(report|bi_|ai_|anomal|document|notification|message|template|integration)"),
]


def _group(table: str) -> str:
    for name, pat in GROUPS:
        if re.match(pat, table):
            return name
    return "Other"


def _purpose_comments() -> dict[str, str]:
    """First comment line above each CREATE TABLE in the migrations, if any."""
    out: dict[str, str] = {}
    for f in migration_files():
        with open(os.path.join(MIGRATIONS_DIR, f), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        for i, line in enumerate(lines):
            m = re.match(r"CREATE TABLE (\w+)", line)
            if m:
                out.setdefault(m.group(1), f)
    return out


def build() -> str:
    tmp = tempfile.mkdtemp()
    db = Database(f"sqlite:///{os.path.join(tmp, 'dd.db')}")
    migrate(db)
    origin = _purpose_comments()
    with db.tx() as c:
        tables = [r["name"] for r in c.all("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' AND name <> 'schema_migrations' ORDER BY name")]
        info = {t: c.all(f"PRAGMA table_info({t})") for t in tables}
        fks = {t: c.all(f"PRAGMA foreign_key_list({t})") for t in tables}
        idx = {t: [r["name"] for r in c.all(f"PRAGMA index_list({t})")] for t in tables}
        uniques: dict[str, list[str]] = {}
        for t in tables:
            for r in c.all(f"PRAGMA index_list({t})"):
                if r["unique"] and not r["name"].startswith("sqlite_autoindex") or (r["unique"] and r["origin"] == "u"):
                    cols = [x["name"] for x in c.all(f"PRAGMA index_info({r['name']})")]
                    uniques.setdefault(t, []).append("(" + ", ".join(cols) + ")")
    db.close()
    out = [f"# Data dictionary — EHMS {__version__}", "",
           "Generated from the migrations by `python -m ehms.datadict`; do not edit by hand. Types are shown as they are in PostgreSQL "
           "(SQLite uses compatible storage classes). Money columns hold whole kobo (minor units); `*_milli` quantities hold thousandths.", "",
           f"**{len(tables)} tables**, {sum(len(v) for v in info.values())} columns, {sum(len(v) for v in fks.values())} foreign keys.", ""]
    by_group: dict[str, list[str]] = {}
    for t in tables:
        by_group.setdefault(_group(t), []).append(t)
    order = [g for g, _ in GROUPS] + ["Other"]
    out.append("## Contents\n")
    for g in order:
        if g in by_group:
            out.append(f"- **{g}**: " + ", ".join(f"[{t}](#{t.replace('_', '_')})" for t in by_group[g]))
    out.append("")
    pg = {"INTEGER": "integer / bigint", "TEXT": "text / date / timestamptz"}
    for g in order:
        if g not in by_group:
            continue
        out.append(f"## {g}\n")
        # ER diagram for the group (relationships inside the group, plus referenced tables)
        out.append("```mermaid\nerDiagram")
        seen = set()
        for t in by_group[g]:
            for fk in fks[t]:
                key = (fk["table"], t, fk["from"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(f"    {fk['table'].upper()} ||--o{{ {t.upper()} : \"{fk['from']}\"")
        if not seen:
            for t in by_group[g]:
                out.append(f"    {t.upper()} {{ }}")
        out.append("```\n")
        for t in by_group[g]:
            refs = {fk["from"]: fk["table"] for fk in fks[t]}
            out.append(f"### {t}\n")
            out.append(f"Defined in `{origin.get(t, '?')}`." + (f" Unique: {', '.join(uniques[t])}." if uniques.get(t) else ""))
            out.append("\n| Column | Type | Null | Default | Key / reference |\n|---|---|---|---|---|")
            for col in info[t]:
                key = "PK" if col["pk"] else (f"→ {refs[col['name']]}" if col["name"] in refs else "")
                typ = col["type"] or ""
                out.append(f"| {col['name']} | {typ} | {'no' if col['notnull'] or col['pk'] else 'yes'} | {col['dflt_value'] if col['dflt_value'] is not None else ''} | {key} |")
            out.append("")
    return "\n".join(out) + "\n"


if __name__ == "__main__":  # pragma: no cover
    print(build(), end="")
