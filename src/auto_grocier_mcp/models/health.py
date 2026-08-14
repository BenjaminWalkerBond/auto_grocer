"""Health check response models."""

try:
    from datetime import UTC
except ImportError:  # Python < 3.11
    from datetime import timezone as _timezone
    UTC = _timezone.utc
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    """Health status of a single component."""

    status: Literal["up", "down", "degraded"] = Field(description="Component status")
    latency_ms: float | None = Field(default=None, description="Response latency")
    message: str | None = Field(default=None, description="Status message")


class CircuitBreakerStatus(BaseModel):
    """Status of a circuit breaker."""

    state: Literal["closed", "open", "half_open"] = Field(
        description="Circuit state"
    )
    failures: int = Field(default=0, description="Current failure count")


class HealthResponse(BaseModel):
    """Health check response."""

    status: Literal["healthy", "degraded", "unhealthy"] = Field(
        description="Overall health status"
    )
    timestamp: str = Field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
        description="Check timestamp",
    )
    components: dict[str, ComponentHealth] = Field(
        default_factory=dict, description="Component health statuses"
    )
    circuit_breakers: dict[str, CircuitBreakerStatus] = Field(
        default_factory=dict, description="Circuit breaker statuses"
    )
