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

    # Cache status: auto_grocer uses an in-memory cache only (no external
    # cache service is configured or required).
    components["cache"] = ComponentHealth(
        status="up", message="Not configured (using in-memory)"
    )

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now(UTC).isoformat(),
        components=components,
        circuit_breakers=circuit_breakers,
    ).model_dump()
