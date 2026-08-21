"""Circuit breaker pattern for preventing cascading failures."""

import time
from dataclasses import dataclass
from enum import Enum
from threading import Lock

import structlog

logger = structlog.get_logger()


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreakerOpenError(Exception):
    """Raised when circuit breaker is open."""

    def __init__(self, name: str, retry_after: float):
        self.name = name
        self.retry_after = retry_after
        super().__init__(f"Circuit breaker '{name}' is open. Retry after {retry_after:.1f}s")


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""

    failure_threshold: int = 5
    recovery_timeout: float = 30.0
    half_open_max_calls: int = 3


class CircuitBreaker:
    """Circuit breaker for external service calls.

    Prevents cascading failures by "tripping" after repeated failures
    and allowing the system to recover.
    """

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None):
        self.name = name
        self.config = config or CircuitBreakerConfig()
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float | None = None
        self._half_open_calls = 0
        self._lock = Lock()

    @property
    def state(self) -> CircuitState:
        """Get current circuit state, checking for transition to half-open."""
        with self._lock:
            if self._state == CircuitState.OPEN and self._should_attempt_recovery():
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("Circuit breaker transitioning to half-open", name=self.name)
            return self._state

    @property
    def failure_count(self) -> int:
        """Get current failure count."""
        return self._failure_count

    def _should_attempt_recovery(self) -> bool:
        """Check if enough time has passed to attempt recovery."""
        if self._last_failure_time is None:
            return False
        return time.time() - self._last_failure_time >= self.config.recovery_timeout

    def check(self) -> None:
        """Check if request should be allowed.

        Raises:
            CircuitBreakerOpen: If circuit is open and recovery timeout hasn't elapsed.
        """
        current_state = self.state  # This may transition to half-open

        if current_state == CircuitState.OPEN:
            retry_after = (
                self.config.recovery_timeout
                - (time.time() - (self._last_failure_time or 0))
            )
            raise CircuitBreakerOpenError(self.name, max(0, retry_after))

        if current_state == CircuitState.HALF_OPEN:
            with self._lock:
                if self._half_open_calls >= self.config.half_open_max_calls:
                    raise CircuitBreakerOpenError(self.name, self.config.recovery_timeout)
                self._half_open_calls += 1

    def record_success(self) -> None:
        """Record a successful call."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self.config.half_open_max_calls:
                    self._state = CircuitState.CLOSED
                    self._failure_count = 0
                    self._success_count = 0
                    logger.info("Circuit breaker closed", name=self.name)
            else:
                self._failure_count = 0
                self._success_count = 0

    def record_failure(self) -> None:
        """Record a failed call."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()

            if self._state == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker reopened from half-open",
                    name=self.name,
                )
            elif self._failure_count >= self.config.failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning(
                    "Circuit breaker opened",
                    name=self.name,
                    failure_count=self._failure_count,
                )

    def get_status(self) -> dict[str, str | int]:
        """Get circuit breaker status for health checks."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
        }
