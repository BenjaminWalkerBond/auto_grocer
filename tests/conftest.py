"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all shared state between tests."""
    from auto_grocer_mcp.state import StateManager

    StateManager.reset_sync()
    yield
    StateManager.reset_sync()


@pytest.fixture(autouse=True)
def _reset_graphql_hash_refresh_hook():
    """Prevent any unit test from leaking a hash-refresh callback registration.

    Several tests exercise PersistedQueryNotFoundError against a real
    HEBGraphQLClient. Importing auto_grocer.mcp_server (e.g. during test
    collection for test_mcp_server_tools.py) registers the *production*
    capture_hashes callback, which drives a real browser/Docker subprocess. If
    that registration were still active when an unrelated test hits a stale
    hash, it would launch that real subprocess during the unit test suite.
    Reset the hook before and after every test; test_hash_auto_refresh.py
    re-registers its own lightweight fake callback per test as needed.
    """
    from auto_grocer_mcp.clients import graphql as graphql_module

    graphql_module.register_hash_refresh_callback(None)
    graphql_module._last_hash_refresh_monotonic = 0.0
    graphql_module._hash_refresh_in_progress = False
    yield
    graphql_module.register_hash_refresh_callback(None)
    graphql_module._last_hash_refresh_monotonic = 0.0
    graphql_module._hash_refresh_in_progress = False


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers",
        "integration: mark test as integration test (requires real API access)",
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --run-integration is passed."""
    if not config.getoption("--run-integration", default=False):
        skip_integration = pytest.mark.skip(
            reason="Integration tests skipped. Use --run-integration to run."
        )
        for item in items:
            if "integration" in item.keywords:
                item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires authenticated session)",
    )
