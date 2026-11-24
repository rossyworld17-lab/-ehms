"""Encryption of sensitive data at rest (release 1.4).

Field encryption: guest and visitor identification numbers, and staff and supplier bank, tax, pension and NHF numbers
and staff two-step verification secrets are stored as `enc:v1:<base64(nonce | ciphertext+tag)>` using AES-256-GCM. The database layer encrypts these columns
on every insert/update (`ENCRYPTED_COLUMNS`) and decrypts any value carrying the prefix on every read, so the rest of
the code works with plain values.

Backup encryption: backup archives are written as a stream of AES-256-GCM chunks (format `EHMSENC1`).

Key: `EHMS_DATA_KEY` (32 random bytes, base64) — required in production. Without it (development and the Windows
demo) a key is generated once and kept in `data/ehms-data.key` next to the database. **Losing the key makes the
encrypted fields and backups unreadable**: keep a copy in the hotel's password manager or safe.
    Generate one:  python -c "import base64,os;print(base64.b64encode(os.urandom(32)).decode())"
"""
from __future__ import annotations

import base64
import os
import struct
import threading

PREFIX = "enc:v1:"
MAGIC = b"EHMSENC1"
CHUNK = 1024 * 1024

ENCRYPTED_COLUMNS: dict[str, frozenset[str]] = {
    "guests": frozenset({"id_number"}),
    "visitors": frozenset({"id_number"}),
    "employees": frozenset({"bank_account_number", "tax_id", "pension_pin", "nhf_number"}),
    "suppliers": frozenset({"bank_account_number"}),
    "users": frozenset({"mfa_secret"}),
}

_lock = threading.Lock()
_cache: dict[str, object] = {}


class KeyError_(Exception):
    pass


def key_file() -> str:
    d = os.environ.get("EHMS_DATA_DIR") or os.path.join(os.getcwd(), "data")
    return os.path.join(d, "ehms-data.key")


def _raw_key() -> bytes:
    env = os.environ.get("EHMS_DATA_KEY", "").strip()
    if env:
        try:
            k = base64.b64decode(env, validate=True)
        except Exception as e:
            raise KeyError_("EHMS_DATA_KEY must be base64") from e
        if len(k) != 32:
            raise KeyError_("EHMS_DATA_KEY must decode to exactly 32 bytes")
        return k
    if os.environ.get("EHMS_ENV", "development") == "production":
        raise KeyError_("EHMS_DATA_KEY is required in production")
    path = key_file()
    if os.path.isfile(path):
        with open(path, "rb") as fh:
            k = base64.b64decode(fh.read().strip())
        if len(k) == 32:
            return k
    os.makedirs(os.path.dirname(path), exist_ok=True)
    k = os.urandom(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as fh:
        fh.write(base64.b64encode(k))
    return k


def _aead():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    src = os.environ.get("EHMS_DATA_KEY", "") or key_file()
    with _lock:
        a = _cache.get(src)
        if a is None:
            a = AESGCM(_raw_key())
            _cache.clear()
            _cache[src] = a
        return a


def reset_cache() -> None:
    with _lock:
        _cache.clear()


def encrypt_value(v):
    if v is None or v == "" or not isinstance(v, str) or v.startswith(PREFIX):
        return v
    nonce = os.urandom(12)
    ct = _aead().encrypt(nonce, v.encode("utf-8"), b"ehms-field")
    return PREFIX + base64.b64encode(nonce + ct).decode("ascii")


def decrypt_value(v):
    if not isinstance(v, str) or not v.startswith(PREFIX):
        return v
    try:
        blob = base64.b64decode(v[len(PREFIX):])
        return _aead().decrypt(blob[:12], blob[12:], b"ehms-field").decode("utf-8")
    except Exception:
        return "[encrypted — key mismatch]"


def encrypt_row(table: str, data: dict) -> dict:
    cols = ENCRYPTED_COLUMNS.get(table)
    if not cols:
        return data
    return {k: (encrypt_value(v) if k in cols else v) for k, v in data.items()}


def encrypt_existing(db) -> int:
    """Encrypt values written before 1.4 (or by raw SQL). Idempotent; runs at start-up."""
    n = 0
    with db.tx() as c:
        for table, cols in ENCRYPTED_COLUMNS.items():
            for col in cols:
                rows = c.execute(f"SELECT id, {c._ident(col)} FROM {c._ident(table)} WHERE {c._ident(col)} IS NOT NULL AND {c._ident(col)} <> ? "
                                 f"AND {c._ident(col)} NOT LIKE ?", ["", PREFIX + "%"]).fetchall()
                for rid, val in rows:
                    c.execute(f"UPDATE {c._ident(table)} SET {c._ident(col)} = ? WHERE id = ?", [encrypt_value(str(val)), rid])
                    n += 1
    return n


# ------------------------------------------------------------------ backup files
def is_encrypted_file(path: str) -> bool:
    with open(path, "rb") as fh:
        return fh.read(len(MAGIC)) == MAGIC


def encrypt_file(src: str, dst: str) -> None:
    aead = _aead()
    base = os.urandom(8)
    with open(src, "rb") as fi, open(dst, "wb") as fo:
        fo.write(MAGIC + base)
        i = 0
        chunk = fi.read(CHUNK)
        while True:
            nxt = fi.read(CHUNK)
            last = not nxt
            nonce = base + struct.pack(">I", i)
            ct = aead.encrypt(nonce, chunk, b"last" if last else b"more")
            fo.write(struct.pack(">I", len(ct)) + ct)
            if last:
                break
            chunk, i = nxt, i + 1


def decrypt_file(src: str, dst) -> None:
    """Decrypt to a path or a writable binary file object; raises ValueError on a wrong key or tampering."""
    from cryptography.exceptions import InvalidTag
    aead = _aead()
    out = open(dst, "wb") if isinstance(dst, str) else dst
    try:
        with open(src, "rb") as fi:
            head = fi.read(len(MAGIC) + 8)
            if head[:len(MAGIC)] != MAGIC:
                raise ValueError("Not an encrypted EHMS backup")
            base, i, ended = head[len(MAGIC):], 0, False
            while True:
                hdr = fi.read(4)
                if not hdr:
                    break
                ct = fi.read(struct.unpack(">I", hdr)[0])
                nonce = base + struct.pack(">I", i)
                try:
                    out.write(aead.decrypt(nonce, ct, b"more"))
                except InvalidTag:
                    try:
                        out.write(aead.decrypt(nonce, ct, b"last"))
                        ended = True
                    except InvalidTag:
                        raise ValueError("The backup cannot be decrypted: wrong EHMS_DATA_KEY or the file was altered")
                    if fi.read(1):
                        raise ValueError("The backup was altered (data after the last chunk)")
                    break
                i += 1
            if not ended:
                raise ValueError("The backup is incomplete (truncated)")
    finally:
        if isinstance(dst, str):
            out.close()
