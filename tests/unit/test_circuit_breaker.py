"""Tests for circuit breaker pattern."""

import asyncio

import pytest

from texas_grocery_mcp.reliability.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
)


def test_circuit_starts_closed():
    """Circuit should start in closed state."""
    cb = CircuitBreaker("test")
    assert cb.state == CircuitState.CLOSED


def test_circuit_opens_after_threshold():
    """Circuit should open after failure threshold."""
    cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=2))

    cb.record_failure()
    assert cb.state == CircuitState.CLOSED

    cb.record_failure()
    assert cb.state == CircuitState.OPEN


def test_circuit_resets_on_success():
    """Circuit should reset failure count on success."""
    cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=3))

    cb.record_failure()
    cb.record_failure()
    cb.record_success()

    assert cb.failure_count == 0
    assert cb.state == CircuitState.CLOSED


def test_open_circuit_raises():
    """Open circuit should raise CircuitBreakerOpen."""
    cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=1))
    cb.record_failure()

    with pytest.raises(CircuitBreakerOpenError):
        cb.check()


@pytest.mark.asyncio
async def test_circuit_transitions_to_half_open():
    """Circuit should transition to half-open after timeout."""
    cb = CircuitBreaker(
        "test",
        config=CircuitBreakerConfig(failure_threshold=1, recovery_timeout=0.1),
    )
    cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Wait for recovery timeout
    await asyncio.sleep(0.15)

    # Next check should allow through (half-open)
    cb.check()  # Should not raise
    assert cb.state == CircuitState.HALF_OPEN
