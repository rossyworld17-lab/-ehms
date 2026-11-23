"""The interface build must match the server: an old build hides modules (e.g. POS, inventory) without any error."""
import json
import os

from starlette.applications import Starlette

from asgi_client import Client
from ehms import __version__, app as appmod
from ehms.config import settings

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def test_shipped_interface_build_matches_server_version():
    dist = os.path.join(ROOT, "frontend", "dist")
    assert os.path.isfile(os.path.join(dist, "assets", "main.js")), "frontend/dist must be shipped — run npm run build"
    assert appmod.frontend_build_version(dist) == __version__, "frontend/dist is stale — run npm run build and commit it"
    with open(os.path.join(ROOT, "frontend", "package.json"), encoding="utf-8") as fh:
        assert json.load(fh)["version"] == __version__


def _serve(tmp_path, version):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "main.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html><body><div id=root></div></body></html>")
    if version:
        (tmp_path / "version.json").write_text(json.dumps({"version": version}))
    old = settings.frontend_dist
    settings.frontend_dist = str(tmp_path)
    try:
        return Client(Starlette(routes=appmod._frontend_routes()))
    finally:
        settings.frontend_dist = old


def test_matching_build_is_served_without_warning(tmp_path):
    c = _serve(tmp_path, __version__)
    try:
        r = c.get("/")
        assert r.status_code == 200 and "out of date" not in r.text
        a = c.get("/assets/main.js")
        assert a.status_code == 200 and a.headers.get("cache-control") == "no-cache"
    finally:
        c.close()


def test_old_build_shows_a_warning(tmp_path):
    c = _serve(tmp_path, None)
    try:
        r = c.get("/")
        assert r.status_code == 200 and "This screen is out of date" in r.text and __version__ in r.text
    finally:
        c.close()
