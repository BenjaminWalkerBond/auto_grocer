"""Health check endpoints."""

try:
    from datetime import UTC
except ImportError:  # Python < 3.11
    from datetime import timezone as _timezone
    UTC = _timezone.utc
from datetime import datetime
from typing import Any, Literal, cast

import structlog

from auto_grocer_mcp.models.health import (
    CircuitBreakerStatus,
    ComponentHealth,
    HealthResponse,
)

logger = structlog.get_logger()


def health_live() -> dict[str, str]:
    """Liveness probe - is the process running?

    Returns a simple alive status. Use for Kubernetes liveness probes.
    """
    return {"status": "alive"}


def _check_redis_health_sync(redis_url: str) -> ComponentHealth:
    """Check Redis connectivity (sync version).

    Args:
        redis_url: Redis connection URL

    Returns:
        ComponentHealth with status and optional message
    """
    try:
        import redis

        # Parse URL and connect with timeout
        client = redis.from_url(  # type: ignore[no-untyped-call]
            redis_url,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )

        try:
            # Ping to verify connectivity
            client.ping()

            # Get basic info for health details
            info = client.info(section="server")
            redis_version = info.get("redis_version", "unknown")

            return ComponentHealth(
                status="up",
                message=f"Redis {redis_version}",
            )

        finally:
            client.close()

    except ImportError:
        return ComponentHealth(
            status="up",
            message="Redis client not installed (optional dependency)",
        )
    except Exception as e:
        logger.warning("Redis health check failed", error=str(e))
        return ComponentHealth(
            status="down",
            message=f"Connection failed: {str(e)}",
        )


def health_ready() -> dict[str, Any]:
    """Readiness probe - can the server handle requests?

    Returns detailed component health. Use for Kubernetes readiness probes.
    """
    components: dict[str, ComponentHealth] = {}
    circuit_breakers: dict[str, CircuitBreakerStatus] = {}
    overall_status: Literal["healthy", "degraded", "unhealthy"] = "healthy"

    # Check GraphQL API status
    try:
        from auto_grocer_mcp.clients.graphql import HEBGraphQLClient

        client = HEBGraphQLClient()
        cb_status = client.circuit_breaker.get_status()

        state_raw = cb_status.get("state")
        state: Literal["closed", "open", "half_open"] = "closed"
        if isinstance(state_raw, str) and state_raw in ("closed", "open", "half_open"):
            state = cast(Literal["closed", "open", "half_open"], state_raw)

        failures_raw = cb_status.get("failure_count", 0)
        failures = int(failures_raw) if isinstance(failures_raw, int) else 0

        if state == "open":
            components["graphql_api"] = ComponentHealth(
                status="down", message="Circuit breaker open"
            )
            overall_status = "degraded"
        else:
            components["graphql_api"] = ComponentHealth(status="up")

        circuit_breakers["heb_graphql"] = CircuitBreakerStatus(
            state=state,
            failures=failures,
        )
    except Exception as e:
        components["graphql_api"] = ComponentHealth(
            status="down", message=str(e)
        )
        overall_status = "unhealthy"

    # Check cache status (if configured)
    try:
        from auto_grocer_mcp.utils.config import get_settings

        settings = get_settings()
        if settings.redis_url:
            # Actually check Redis connectivity
            cache_health = _check_redis_health_sync(settings.redis_url)
            components["cache"] = cache_health

            if cache_health.status == "down" and overall_status == "healthy":
                overall_status = "degraded"
        else:
            components["cache"] = ComponentHealth(
                status="up", message="Not configured (using in-memory)"
            )
    except Exception as e:
        components["cache"] = ComponentHealth(status="down", message=str(e))
        if overall_status == "healthy":
            overall_status = "degraded"

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now(UTC).isoformat(),
        components=components,
        circuit_breakers=circuit_breakers,
    ).model_dump()
