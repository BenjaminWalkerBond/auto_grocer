"""Pytest configuration and fixtures."""

import pytest


@pytest.fixture(autouse=True)
def reset_state():
    """Reset all shared state between tests."""
    from texas_grocery_mcp.state import StateManager

    StateManager.reset_sync()
    yield
    StateManager.reset_sync()


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
