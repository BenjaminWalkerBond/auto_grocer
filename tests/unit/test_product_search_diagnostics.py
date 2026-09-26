"""Tests for ProductSearchResult diagnostics and the nodriver browser fallback."""

import pytest
import respx
from httpx import Response


@pytest.fixture(autouse=True)
def reset_tool_state():
    """Reset global state before each test."""
    from auto_grocer_mcp.tools import product as product_module
    from auto_grocer_mcp.tools import store as store_module

    store_module._default_store_id = "737"  # Set default store for tests
    store_module._graphql_client = None
    product_module._graphql_client = None
    yield
    store_module._default_store_id = None
    store_module._graphql_client = None
    product_module._graphql_client = None


@pytest.fixture
def mock_typeahead_response():
    """Mock typeahead response."""
    return {
        "data": {
            "typeaheadContent": {
                "verticalStack": [
                    {
                        "terms": ["Eggs", "Egg whites", "Organic eggs"],
                        "__typename": "TypeaheadTypingSuggestedSearches",
                    }
                ],
            }
        }
    }


@pytest.fixture
def mock_security_challenge_html():
    """Mock HTML response for security challenge."""
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Access Denied</title></head>
    <body>
        <script src="/_Incapsula_Resource"></script>
        <div id="challenge-platform">
            Please verify you are a human by completing this challenge.
        </div>
        <script>
            var reese84 = {};
        </script>
    </body>
    </html>
    """


@pytest.fixture
def mock_ssr_success_html():
    """Mock HTML response for successful SSR search."""
    import json

    next_data = {
        "props": {
            "pageProps": {
                "layout": {
                    "visualComponents": [
                        {
                            "type": "searchGridV2",
                            "items": [
                                {
                                    "__typename": "Product",
                                    "id": "123456",
                                    "fullDisplayName": "Large Eggs 12ct",
                                    "brand": {"name": "Hill Country Fare"},
                                    "SKUs": [
                                        {
                                            "id": "SKU123",
                                            "customerFriendlySize": "12 ct",
                                            "contextPrices": [
                                                {
                                                    "context": "CURBSIDE",
                                                    "listPrice": {"amount": 3.99},
                                                    "salePrice": {"amount": 0},
                                                    "isOnSale": False,
                                                }
                                            ],
                                        }
                                    ],
                                    "inventory": {"inventoryState": "IN_STOCK"},
                                    "productImageUrls": [],
                                    "showCouponFlag": False,
                                }
                            ],
                        }
                    ]
                }
            }
        }
    }

    return f"""
    <!DOCTYPE html>
    <html>
    <head><title>Search Results</title></head>
    <body>
        <script id="__NEXT_DATA__" type="application/json">{json.dumps(next_data)}</script>
    </body>
    </html>
    """


@pytest.mark.asyncio
@respx.mock
async def test_product_search_returns_data_source(mock_typeahead_response):
    """product_search should include data_source field."""
    from auto_grocer_mcp.tools.product import product_search

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search(query="eggs", store_id="737")

    assert "data_source" in result
    assert result["data_source"] == "typeahead_suggestions"


@pytest.mark.asyncio
@respx.mock
async def test_product_search_includes_authenticated_field(mock_typeahead_response, monkeypatch):
    """product_search should include authenticated field."""
    from auto_grocer_mcp.tools.product import product_search

    # Mock as NOT authenticated to test typeahead fallback
    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.is_authenticated",
        lambda: False,
    )

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search(query="eggs", store_id="737")

    assert "authenticated" in result
    # Not authenticated when using typeahead fallback
    assert result["authenticated"] is False


@pytest.mark.asyncio
@respx.mock
async def test_product_search_includes_attempts_summary(mock_typeahead_response):
    """product_search should include attempts summary."""
    from auto_grocer_mcp.tools.product import product_search

    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    result = await product_search(query="eggs", store_id="737")

    assert "attempts_summary" in result
    summary = result["attempts_summary"]
    assert "total" in summary
    assert "successful" in summary


def test_detect_security_challenge_identifies_incapsula():
    """_detect_security_challenge should detect Incapsula challenges."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient

    client = HEBGraphQLClient()

    # Test various challenge indicators
    assert client._detect_security_challenge("<script src='/_Incapsula_Resource'></script>")
    assert client._detect_security_challenge("Please verify you are a human")
    assert client._detect_security_challenge("<div id='challenge-platform'>")
    assert client._detect_security_challenge("Access Denied by WAF")

    # Should not trigger on normal content
    assert not client._detect_security_challenge("<html><body>Normal page</body></html>")
    assert not client._detect_security_challenge("<script>console.log('hello')</script>")


def test_detect_security_challenge_case_insensitive():
    """_detect_security_challenge should be case insensitive."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient

    client = HEBGraphQLClient()

    assert client._detect_security_challenge("REQUEST UNSUCCESSFUL. Incapsula incident ID: 1-2")
    assert client._detect_security_challenge("Request Unsuccessful")
    assert client._detect_security_challenge("PARDON OUR INTERRUPTION")


def test_detect_security_challenge_ignores_normal_page_with_incapsula_script():
    """A real HEB page carries an inline Incapsula telemetry script and the bare
    word 'incapsula'; these must NOT be treated as a challenge (regression)."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient

    client = HEBGraphQLClient()

    # Bare tokens that Incapsula injects site-wide are not, by themselves, a block.
    assert not client._detect_security_challenge("INCAPSULA")
    assert not client._detect_security_challenge("incapsula")

    # A large, real-looking storefront page that happens to reference the
    # Incapsula resource script must be treated as a normal page.
    normal_page = (
        "<html><head><header>"
        "<script src='/_Incapsula_Resource?SWJIYLWA=abc'></script>"
        "</header><body>"
        "<nav>My Account | My Cart</nav>"
        "<main data-testid='search-grid'>"
        + ("<div class='product'>Add to cart — HEB.com curbside delivery</div>" * 200)
        + "<script id='__NEXT_DATA__' type='application/json'>{}</script>"
        "</main></body></html>"
    )
    assert not client._detect_security_challenge(normal_page)


def test_determine_fallback_reason_not_authenticated():
    """_determine_fallback_reason should explain no auth."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient

    client = HEBGraphQLClient()

    reason = client._determine_fallback_reason(
        was_authenticated=False,
        security_challenge=False,
        attempts=[],
    )

    assert "authentication" in reason.lower()


def test_determine_fallback_reason_security_challenge():
    """_determine_fallback_reason should explain security challenge."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient
    from auto_grocer_mcp.models import ProductSearchAttempt

    client = HEBGraphQLClient()

    attempts = [
        ProductSearchAttempt(query="eggs", method="ssr", result="security_challenge"),
    ]

    reason = client._determine_fallback_reason(
        was_authenticated=True,
        security_challenge=True,
        attempts=attempts,
    )

    assert "security" in reason.lower()
    assert "browser" in reason.lower()


def test_determine_fallback_reason_empty_results():
    """_determine_fallback_reason should explain empty results."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient
    from auto_grocer_mcp.models import ProductSearchAttempt

    client = HEBGraphQLClient()

    attempts = [
        ProductSearchAttempt(query="eggs", method="ssr", result="empty"),
        ProductSearchAttempt(query="H-E-B eggs", method="ssr", result="empty"),
    ]

    reason = client._determine_fallback_reason(
        was_authenticated=True,
        security_challenge=False,
        attempts=attempts,
    )

    assert "empty" in reason.lower()


@pytest.mark.asyncio
@respx.mock
async def test_product_search_nodriver_fallback_success_when_challenged(
    mock_typeahead_response, mock_security_challenge_html, monkeypatch
):
    """When SSR is challenged, a successful nodriver browser search returns products."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient
    from auto_grocer_mcp.models import Product
    from auto_grocer_mcp.tools.product import product_search

    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.is_authenticated",
        lambda: True,
    )
    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.get_httpx_cookies",
        lambda: {"sat": "test-token"},
    )

    # SSR returns a security challenge; the browser fallback returns real products.
    respx.get("https://www.heb.com/search").mock(
        return_value=Response(200, text=mock_security_challenge_html)
    )
    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    async def fake_nodriver(self, query, store_id, limit=20):
        return [
            Product(
                sku="123456",
                name="Large Eggs 12ct",
                price=3.99,
                available=True,
                brand=None,
                size=None,
                price_per_unit=None,
                image_url=None,
                aisle=None,
                on_sale=False,
                original_price=None,
            )
        ]

    monkeypatch.setattr(
        HEBGraphQLClient, "_search_products_nodriver", fake_nodriver
    )

    result = await product_search(query="eggs", store_id="737")

    assert result["security_challenge_detected"] is True
    assert result["data_source"] == "ssr"
    assert result["count"] >= 1
    assert "playwright_fallback" not in result


@pytest.mark.asyncio
@respx.mock
async def test_product_search_typeahead_when_challenged_and_browser_empty(
    mock_typeahead_response, mock_security_challenge_html, monkeypatch
):
    """When SSR is challenged and the browser finds nothing, fall back to typeahead."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient
    from auto_grocer_mcp.tools.product import product_search

    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.is_authenticated",
        lambda: True,
    )
    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.get_httpx_cookies",
        lambda: {"sat": "test-token"},
    )

    respx.get("https://www.heb.com/search").mock(
        return_value=Response(200, text=mock_security_challenge_html)
    )
    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    async def empty_nodriver(self, query, store_id, limit=20):
        return []

    monkeypatch.setattr(
        HEBGraphQLClient, "_search_products_nodriver", empty_nodriver
    )

    result = await product_search(query="eggs", store_id="737")

    assert result["security_challenge_detected"] is True
    assert result["data_source"] == "typeahead_suggestions"
    assert "playwright_fallback" not in result


@pytest.mark.asyncio
@respx.mock
async def test_product_search_ssr_success(mock_ssr_success_html, monkeypatch):
    """product_search should return SSR data source on success."""
    from auto_grocer_mcp.tools.product import product_search

    # Mock as authenticated
    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.is_authenticated",
        lambda: True,
    )
    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.get_httpx_cookies",
        lambda: {"sat": "test-token"},
    )

    respx.get("https://www.heb.com/search").mock(
        return_value=Response(200, text=mock_ssr_success_html)
    )

    result = await product_search(query="eggs", store_id="737")

    assert result["data_source"] == "ssr"
    assert result["authenticated"] is True
    assert len(result["products"]) == 1
    assert result["products"][0]["name"] == "Large Eggs 12ct"
    assert result["products"][0]["price"] == 3.99


def test_product_search_result_model():
    """ProductSearchResult model should have all required fields."""
    from auto_grocer_mcp.models import Product, ProductSearchAttempt, ProductSearchResult

    result = ProductSearchResult(
        products=[Product(sku="123", name="Test", price=1.99, available=True)],
        count=1,
        query="test",
        store_id="737",
        data_source="ssr",
        authenticated=True,
        fallback_reason=None,
        security_challenge_detected=False,
        attempts=[ProductSearchAttempt(query="test", method="ssr", result="success")],
        search_url="https://www.heb.com/search?q=test",
        playwright_fallback_available=False,
        playwright_instructions=None,
    )

    assert result.count == 1
    assert result.data_source == "ssr"
    assert len(result.attempts) == 1


def test_product_search_attempt_model():
    """ProductSearchAttempt model should validate correctly."""
    from auto_grocer_mcp.models import ProductSearchAttempt

    attempt = ProductSearchAttempt(
        query="eggs",
        method="ssr",
        result="success",
    )
    assert attempt.method == "ssr"
    assert attempt.result == "success"
    assert attempt.error_detail is None

    attempt_with_error = ProductSearchAttempt(
        query="eggs",
        method="ssr",
        result="error",
        error_detail="Connection timeout",
    )
    assert attempt_with_error.error_detail == "Connection timeout"


# ---------------------------------------------------------------------------
# False WAF alarms
# ---------------------------------------------------------------------------
# A challenged SSR route is an EXPECTED, handled condition: the client simply
# switches to the nodriver browser route, which normally succeeds. Production
# logs showed the alarming verdict being computed and logged BEFORE the browser
# fallback ran ("the in-process browser fallback returned no results. Use the
# session_refresh tool...") and then the fallback returning 20 products. Those
# false alarms pushed the agent into needless session/hash refresh storms.


def test_fallback_reason_does_not_presume_browser_failed_before_it_runs():
    """The challenge reason must not claim the browser fallback already failed."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient
    from auto_grocer_mcp.models import ProductSearchAttempt

    client = HEBGraphQLClient()
    attempts = [
        ProductSearchAttempt(query="eggs", method="ssr", result="security_challenge"),
    ]

    reason = client._determine_fallback_reason(
        was_authenticated=True,
        security_challenge=True,
        attempts=attempts,
    )

    # No nodriver_browser attempt was recorded, so the reason must not assert
    # that the browser returned nothing, nor demand a session refresh.
    assert "returned no results" not in reason.lower()
    assert "session_refresh" not in reason.lower()


def test_fallback_reason_reports_browser_failure_only_after_it_ran():
    """Once the browser attempt is recorded empty, the reason may say so."""
    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient
    from auto_grocer_mcp.models import ProductSearchAttempt

    client = HEBGraphQLClient()
    attempts = [
        ProductSearchAttempt(query="eggs", method="ssr", result="security_challenge"),
        ProductSearchAttempt(query="eggs", method="nodriver_browser", result="empty"),
    ]

    reason = client._determine_fallback_reason(
        was_authenticated=True,
        security_challenge=True,
        attempts=attempts,
    )

    assert "browser" in reason.lower()
    assert "no results" in reason.lower()


@pytest.mark.asyncio
@respx.mock
async def test_challenged_but_successful_search_reports_no_failure(
    mock_typeahead_response, mock_security_challenge_html, monkeypatch, caplog
):
    """A challenge cleared by the browser must not log errors or a fallback_reason."""
    import logging

    from auto_grocer_mcp.clients.graphql import HEBGraphQLClient
    from auto_grocer_mcp.models import Product
    from auto_grocer_mcp.tools.product import product_search

    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.is_authenticated", lambda: True
    )
    monkeypatch.setattr(
        "auto_grocer_mcp.clients.graphql.get_httpx_cookies",
        lambda: {"sat": "test-token"},
    )
    respx.get("https://www.heb.com/search").mock(
        return_value=Response(200, text=mock_security_challenge_html)
    )
    respx.post("https://www.heb.com/graphql").mock(
        return_value=Response(200, json=mock_typeahead_response)
    )

    async def fake_nodriver(self, query, store_id, limit=20):
        return [
            Product(
                sku="123456",
                name="Large Eggs 12ct",
                price=3.99,
                available=True,
                brand=None,
                size=None,
                price_per_unit=None,
                image_url=None,
                aisle=None,
                on_sale=False,
                original_price=None,
            )
        ]

    monkeypatch.setattr(HEBGraphQLClient, "_search_products_nodriver", fake_nodriver)

    with caplog.at_level(logging.WARNING):
        result = await product_search(query="eggs", store_id="737")

    assert result["count"] >= 1
    # The search SUCCEEDED, so it must not advertise a failure reason.
    assert not result.get("fallback_reason")
    # A handled route switch is not an error.
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert not errors, f"unexpected error logs on a successful search: {errors}"
