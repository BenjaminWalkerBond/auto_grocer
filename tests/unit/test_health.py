"""Tests for health check tools."""


def test_health_live_returns_alive():
    """health_live should return alive status."""
    from auto_grocer_mcp.observability.health import health_live

    result = health_live()

    assert result["status"] == "alive"


def test_health_ready_returns_components():
    """health_ready should return component statuses."""
    from auto_grocer_mcp.observability.health import health_ready

    result = health_ready()

    assert "status" in result
    assert "components" in result
    assert "timestamp" in result
    assert result["status"] in ("healthy", "degraded", "unhealthy")


def test_health_ready_reports_in_memory_cache():
    """health_ready should report the cache as the in-memory implementation."""
    from auto_grocer_mcp.observability.health import health_ready

    result = health_ready()

    assert result["components"]["cache"]["status"] == "up"
    assert "in-memory" in result["components"]["cache"]["message"]
