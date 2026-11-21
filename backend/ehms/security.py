"""Password hashing (scrypt), access tokens (JWT/HS256) and TOTP multi-factor codes."""
from __future__ import annotations

import base64
import datetime as dt
import hashlib
import hmac
import os
import secrets
import struct
import time
from urllib.parse import quote

import jwt

from .config import settings

# ---------------------------------------------------------------- passwords
_SCRYPT_N, _SCRYPT_R, _SCRYPT_P = 2**14, 8, 1


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P, dklen=64)
    return f"scrypt${_SCRYPT_N}${_SCRYPT_R}${_SCRYPT_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, dk_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=int(n), r=int(r), p=int(p), dklen=64)
        return hmac.compare_digest(dk, base64.b64decode(dk_b64))
    except Exception:
        return False


def password_problems(password: str) -> list[str]:
    problems = []
    if len(password) < settings.min_password_length:
        problems.append(f"must be at least {settings.min_password_length} characters")
    if not any(c.isupper() for c in password):
        problems.append("must contain an upper-case letter")
    if not any(c.islower() for c in password):
        problems.append("must contain a lower-case letter")
    if not any(c.isdigit() for c in password):
        problems.append("must contain a digit")
    return problems


# ---------------------------------------------------------------- tokens
def create_access_token(user_id: int, jti: str, mfa_pending: bool = False, minutes: int | None = None) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "iat": int(now.timestamp()),
        "exp": int((now + dt.timedelta(minutes=minutes or settings.access_token_minutes)).timestamp()),
        "mfa": bool(mfa_pending),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, settings.secret_key, algorithms=["HS256"])


def new_jti() -> str:
    return secrets.token_hex(16)


# ---------------------------------------------------------------- TOTP (RFC 6238)
def new_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def _hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    h = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    o = h[-1] & 0x0F
    code = (struct.unpack(">I", h[o:o + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def totp_now(secret: str, at: float | None = None) -> str:
    return _hotp(secret, int((at or time.time()) // 30))


def verify_totp(secret: str, code: str, window: int = 1) -> bool:
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit():
        return False
    t = int(time.time() // 30)
    return any(hmac.compare_digest(_hotp(secret, t + w), code) for w in range(-window, window + 1))


def totp_uri(secret: str, email: str, issuer: str = "EHMS") -> str:
    return f"otpauth://totp/{quote(issuer)}:{quote(email)}?secret={secret}&issuer={quote(issuer)}&digits=6&period=30"
