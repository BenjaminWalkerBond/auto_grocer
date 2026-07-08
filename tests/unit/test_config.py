"""Tests for configuration module."""

import os
from unittest.mock import patch


def test_settings_loads_defaults():
    """Settings should have sensible defaults."""
    from texas_grocery_mcp.utils.config import Settings

    settings = Settings()

    assert settings.log_level == "INFO"
    assert settings.environment == "development"


def test_settings_loads_from_env():
    """Settings should load from environment variables."""
    with patch.dict(os.environ, {"HEB_DEFAULT_STORE": "123", "LOG_LEVEL": "DEBUG"}):
        from importlib import reload

        import texas_grocery_mcp.utils.config as config_module

        reload(config_module)
        settings = config_module.Settings()

        assert settings.heb_default_store == "123"
        assert settings.log_level == "DEBUG"


def test_auth_state_path_expands_home():
    """Auth state path should expand ~ to home directory."""
    from texas_grocery_mcp.utils.config import Settings

    settings = Settings()

    assert "~" not in str(settings.auth_state_path)
    assert settings.auth_state_path.name == "auth.json"


def test_throttling_settings_defaults():
    """Throttling settings should have sensible defaults."""
    from texas_grocery_mcp.utils.config import Settings

    settings = Settings()

    # SSR throttling
    assert settings.max_concurrent_ssr_searches == 3
    assert settings.min_ssr_delay_ms == 200
    assert settings.ssr_jitter_ms == 200

    # GraphQL throttling
    assert settings.max_concurrent_graphql == 5
    assert settings.min_graphql_delay_ms == 100
    assert settings.graphql_jitter_ms == 100

    # Global toggle
    assert settings.throttling_enabled is True


def test_throttling_settings_from_env():
    """Throttling settings should load from environment."""
    with patch.dict(
        os.environ,
        {
            "MAX_CONCURRENT_SSR_SEARCHES": "5",
            "MIN_SSR_DELAY_MS": "500",
            "THROTTLING_ENABLED": "false",
        },
    ):
        from importlib import reload

        import texas_grocery_mcp.utils.config as config_module

        reload(config_module)
        settings = config_module.Settings()

        assert settings.max_concurrent_ssr_searches == 5
        assert settings.min_ssr_delay_ms == 500
        assert settings.throttling_enabled is False
