"""
Tests for the GraphQL mode integration.

- Verifies the Selenium->Playwright auth.json export produces the structure the
  texas_grocery_mcp client expects (offline, uses a fake driver).
- Provides an opt-in live smoke test for product search (requires a valid
  auth.json and network access; set RUN_LIVE=1 to enable).

Run:
    python testing/test_graphql_mode.py
    RUN_LIVE=1 python testing/test_graphql_mode.py
"""
import json
import os
import sys
import tempfile

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utility.graphql_auth import export_selenium_session_to_authjson


class _FakeDriver:
    """Minimal stand-in for a Selenium WebDriver."""

    def __init__(self, cookies, local_storage):
        self._cookies = cookies
        self._local_storage = local_storage

    def get_cookies(self):
        return self._cookies

    def execute_script(self, _script):
        # The auth bridge reads the full localStorage as a dict.
        return self._local_storage


def test_auth_export_structure():
    """auth.json should contain mapped cookies + reese84 localStorage."""
    print("Testing auth.json export structure...")

    reese84_value = json.dumps({"token": "abc", "renewTime": 9999999999000})
    driver = _FakeDriver(
        cookies=[
            {"name": "sat", "value": "s1", "domain": ".heb.com", "path": "/",
             "secure": True, "httpOnly": True, "sameSite": "Lax"},
            {"name": "sst", "value": "s2", "domain": ".heb.com", "path": "/"},
            {"name": "JSESSIONID", "value": "s3", "domain": ".heb.com", "path": "/"},
        ],
        local_storage={"reese84": reese84_value, "other": "x"},
    )

    with tempfile.TemporaryDirectory() as tmp:
        auth_path = os.path.join(tmp, "auth.json")
        result_path = export_selenium_session_to_authjson(
            driver, auth_path=auth_path, store_id="737"
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
    print("  ✓ auth.json structure OK")


def test_live_search():
    """Opt-in live test: search products using a real auth.json."""
    if os.environ.get("RUN_LIVE") != "1":
        print("Skipping live search test (set RUN_LIVE=1 to enable).")
        return

    import asyncio

    from texas_grocery_mcp.clients.graphql import HEBGraphQLClient

    store_id = os.environ.get("STORE_ID", "737")

    async def _run():
        client = HEBGraphQLClient()
        try:
            result = await client.search_products(query="milk", store_id=store_id, limit=5)
            print(f"  Found {len(result.products)} products for 'milk'")
            for p in result.products[:5]:
                print(f"    - {p.name} (id={p.product_id}, sku={p.sku}, ${p.price})")
        finally:
            await client.close()

    asyncio.run(_run())
    print("  ✓ Live search completed")


if __name__ == "__main__":
    print("=" * 60)
    print("GraphQL Mode Tests")
    print("=" * 60)
    test_auth_export_structure()
    test_live_search()
    print("\nAll tests passed.")
