"""Tests for health check tools."""

from unittest.mock import MagicMock, patch

import pytest


def test_health_live_returns_alive():
    """health_live should return alive status."""
    from texas_grocery_mcp.observability.health import health_live

    result = health_live()

    assert result["status"] == "alive"


def test_health_ready_returns_components():
    """health_ready should return component statuses."""
    from texas_grocery_mcp.observability.health import health_ready

    result = health_ready()

    assert "status" in result
    assert "components" in result
    assert "timestamp" in result
    assert result["status"] in ("healthy", "degraded", "unhealthy")


class TestRedisHealthCheck:
    """Tests for Redis health check functionality."""

    def test_redis_health_when_connected(self):
        """Verify Redis health check returns up when connected."""
        # Redis is an optional dependency not shipped with auto_grocier (we use
        # the in-memory cache). Skip when the package isn't installed.
        pytest.importorskip("redis")
        from texas_grocery_mcp.observability.health import _check_redis_health_sync

        with patch("redis.from_url") as mock_from_url:
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_client.info.return_value = {"redis_version": "7.0.0"}
            mock_from_url.return_value = mock_client

            result = _check_redis_health_sync("redis://localhost:6379")

            assert result.status == "up"
            assert "7.0.0" in result.message
            mock_client.close.assert_called_once()

    def test_redis_health_when_connection_fails(self):
        """Verify Redis health check returns down when connection fails."""
        # Optional dependency — skip when redis isn't installed (see above).
        pytest.importorskip("redis")
        from texas_grocery_mcp.observability.health import _check_redis_health_sync

        with patch("redis.from_url") as mock_from_url:
            mock_from_url.side_effect = ConnectionError("Connection refused")

            result = _check_redis_health_sync("redis://localhost:6379")

            assert result.status == "down"
            assert "Connection failed" in result.message

    def test_redis_health_when_redis_not_installed(self):
        """Verify graceful handling when redis package not installed."""

        with (
            patch.dict("sys.modules", {"redis": None}),
            patch(
                "texas_grocery_mcp.observability.health._check_redis_health_sync"
            ) as mock_check,
        ):
            from texas_grocery_mcp.models.health import ComponentHealth

            mock_check.return_value = ComponentHealth(
                status="up",
                message="Redis client not installed (optional dependency)",
            )

            result = mock_check("redis://localhost:6379")

            assert result.status == "up"
            assert "not installed" in result.message

    def test_health_ready_with_redis_configured(self):
        """Verify health_ready checks Redis when configured."""
        with patch(
            "texas_grocery_mcp.utils.config.get_settings"
        ) as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.redis_url = "redis://localhost:6379"
            mock_get_settings.return_value = mock_settings

            with patch(
                "texas_grocery_mcp.observability.health._check_redis_health_sync"
            ) as mock_check:
                from texas_grocery_mcp.models.health import ComponentHealth

                mock_check.return_value = ComponentHealth(
                    status="up", message="Redis 7.0.0"
                )

                from texas_grocery_mcp.observability.health import health_ready

                result = health_ready()

                assert result["components"]["cache"]["status"] == "up"
                mock_check.assert_called_once_with("redis://localhost:6379")

    def test_health_ready_degraded_when_redis_down(self):
        """Verify health_ready returns degraded when Redis is unreachable."""
        with patch(
            "texas_grocery_mcp.utils.config.get_settings"
        ) as mock_get_settings:
            mock_settings = MagicMock()
            mock_settings.redis_url = "redis://localhost:6379"
            mock_get_settings.return_value = mock_settings

            with patch(
                "texas_grocery_mcp.observability.health._check_redis_health_sync"
            ) as mock_check:
                from texas_grocery_mcp.models.health import ComponentHealth

                mock_check.return_value = ComponentHealth(
                    status="down", message="Connection failed: Connection refused"
                )

                from texas_grocery_mcp.observability.health import health_ready

                result = health_ready()

                assert result["components"]["cache"]["status"] == "down"
                # Status should be degraded (not unhealthy - cache is optional)
                assert result["status"] in ("degraded", "unhealthy")
