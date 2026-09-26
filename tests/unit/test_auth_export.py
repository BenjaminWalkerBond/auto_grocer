"""Unit tests for the nodriver -> auth.json session export.

Verifies ``export_session_to_authjson`` produces the structure the
auto_grocer_mcp GraphQL client expects. Runs fully offline using fake
CDP cookie/tab/browser stand-ins (no network, no real browser).
"""
import json
import os
import tempfile

from auto_grocer.session_maintenance.auth_export import export_session_to_authjson


class _FakeCDPCookie:
    """Minimal stand-in for a nodriver/CDP cookie object (attribute access)."""

    def __init__(self, name, value, domain=".heb.com", path="/", expires=None,
                 same_site=None, http_only=False, secure=False):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.expires = expires
        self.same_site = same_site
        self.http_only = http_only
        self.secure = secure


class _FakeCookieJar:
    def __init__(self, cookies):
        self._cookies = cookies

    async def get_all(self):
        return self._cookies


class _FakeBrowser:
    def __init__(self, cookies):
        self.cookies = _FakeCookieJar(cookies)


class _FakeTab:
    """Minimal stand-in for a nodriver Tab (only get_local_storage is used)."""

    def __init__(self, local_storage):
        self._local_storage = local_storage

    async def get_local_storage(self):
        return self._local_storage


async def test_auth_export_structure(monkeypatch):
    """auth.json should contain mapped cookies + reese84 localStorage."""
    # Don't leak HEB_DEFAULT_STORE into the real environment beyond this test.
    monkeypatch.delenv("HEB_DEFAULT_STORE", raising=False)

    reese84_value = json.dumps({"token": "abc", "renewTime": 9999999999000})
    browser = _FakeBrowser(
        cookies=[
            _FakeCDPCookie("sat", "s1", secure=True, http_only=True, same_site="Lax"),
            _FakeCDPCookie("sst", "s2"),
            _FakeCDPCookie("JSESSIONID", "s3"),
        ],
    )
    tab = _FakeTab(local_storage={"reese84": reese84_value, "other": "x"})

    with tempfile.TemporaryDirectory() as tmp:
        auth_path = os.path.join(tmp, "auth.json")
        result_path = await export_session_to_authjson(
            browser, tab, auth_path=auth_path, store_id="737"
        )

        assert os.path.exists(result_path), "auth.json was not created"

        with open(result_path, encoding="utf-8") as f:
            state = json.load(f)

        cookie_names = {c["name"] for c in state["cookies"]}
        assert {"sat", "sst", "JSESSIONID"} <= cookie_names, cookie_names

        # Session cookies should map to -1 expiry when none provided.
        sat = next(c for c in state["cookies"] if c["name"] == "sat")
        assert sat["expires"] == -1

        ls = state["origins"][0]["localStorage"]
        reese = next((i for i in ls if i["name"] == "reese84"), None)
        assert reese is not None, "reese84 missing from localStorage"
        assert json.loads(reese["value"]).get("renewTime"), "reese84 not preserved"

    # Env vars should be set for the MCP settings.
    assert os.environ.get("HEB_DEFAULT_STORE") == "737"
