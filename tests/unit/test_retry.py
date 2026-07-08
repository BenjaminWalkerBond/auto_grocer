"""Tests for retry logic."""

import pytest

from texas_grocery_mcp.reliability.retry import RetryConfig, with_retry


@pytest.mark.asyncio
async def test_retry_succeeds_on_first_attempt():
    """Should return immediately if function succeeds."""
    call_count = 0

    @with_retry()
    async def succeeds():
        nonlocal call_count
        call_count += 1
        return "success"

    result = await succeeds()

    assert result == "success"
    assert call_count == 1


@pytest.mark.asyncio
async def test_retry_retries_on_failure():
    """Should retry on transient failures."""
    call_count = 0

    @with_retry(config=RetryConfig(max_attempts=3, base_delay=0.01))
    async def fails_twice():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Network error")
        return "success"

    result = await fails_twice()

    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_retry_raises_after_max_attempts():
    """Should raise after exhausting retries."""
    call_count = 0

    @with_retry(config=RetryConfig(max_attempts=2, base_delay=0.01))
    async def always_fails():
        nonlocal call_count
        call_count += 1
        raise ConnectionError("Network error")

    with pytest.raises(ConnectionError):
        await always_fails()

    assert call_count == 2


@pytest.mark.asyncio
async def test_retry_does_not_retry_non_retryable():
    """Should not retry non-retryable exceptions."""
    call_count = 0

    @with_retry(config=RetryConfig(max_attempts=3, base_delay=0.01))
    async def validation_error():
        nonlocal call_count
        call_count += 1
        raise ValueError("Invalid input")

    with pytest.raises(ValueError):
        await validation_error()

    assert call_count == 1
