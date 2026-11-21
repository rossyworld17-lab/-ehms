"""Runtime configuration, read from environment variables."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    v = os.environ.get(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


@dataclass
class Settings:
    # DATABASE_URL examples:
    #   sqlite:///./ehms.db            (development / tests)
    #   postgresql://user:pass@db/ehms (production)
    database_url: str = field(default_factory=lambda: os.environ.get("DATABASE_URL", "sqlite:///./ehms.db"))
    secret_key: str = field(default_factory=lambda: os.environ.get("EHMS_SECRET_KEY") or secrets.token_urlsafe(48))
    access_token_minutes: int = field(default_factory=lambda: int(os.environ.get("EHMS_ACCESS_TOKEN_MINUTES", "30")))
    session_idle_minutes: int = field(default_factory=lambda: int(os.environ.get("EHMS_SESSION_IDLE_MINUTES", "30")))
    max_failed_logins: int = field(default_factory=lambda: int(os.environ.get("EHMS_MAX_FAILED_LOGINS", "5")))
    lockout_minutes: int = field(default_factory=lambda: int(os.environ.get("EHMS_LOCKOUT_MINUTES", "15")))
    min_password_length: int = field(default_factory=lambda: int(os.environ.get("EHMS_MIN_PASSWORD_LENGTH", "10")))
    cors_origins: list[str] = field(default_factory=lambda: [o for o in os.environ.get("EHMS_CORS_ORIGINS", "").split(",") if o])
    frontend_dist: str = field(default_factory=lambda: os.environ.get("EHMS_FRONTEND_DIST", os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "dist")))
    seed_demo: bool = field(default_factory=lambda: _bool("EHMS_SEED_DEMO", False))
    environment: str = field(default_factory=lambda: os.environ.get("EHMS_ENV", "development"))
    login_rate_limit_per_minute: int = field(default_factory=lambda: int(os.environ.get("EHMS_LOGIN_RATE_LIMIT", "10")))


settings = Settings()
