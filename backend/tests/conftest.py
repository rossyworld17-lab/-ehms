import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("EHMS_SECRET_KEY", "test-secret-key-not-for-production-0123456789")
os.environ["EHMS_LOGIN_RATE_LIMIT"] = "1000"
os.environ["EHMS_WORKER"] = "0"

from asgi_client import Client  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    """Fresh database with demo data for every test (isolated)."""
    from ehms import db as dbmod
    from ehms.http import _rate
    _rate.clear()
    os.environ["EHMS_DOCUMENT_DIR"] = str(tmp_path / "documents")
    url = os.environ.get("TEST_DATABASE_URL")
    if url and url.startswith("postgres"):
        # PostgreSQL run (CI): rebuild an empty schema for every test
        import psycopg
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute("DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;")
        dbmod.set_db(dbmod.Database(url))
    else:
        dbmod.set_db(dbmod.Database(f"sqlite:///{tmp_path}/test.db"))
    from ehms.seed import seed_demo
    seed_demo()
    from ehms.app import create_app
    c = Client(create_app())
    yield c
    c.close()
    dbmod.set_db(None)


@pytest.fixture()
def hotel_id(client):
    from ehms.db import get_db
    with get_db().tx() as c:
        return c.scalar("SELECT id FROM hotels WHERE code = 'CGL'")
