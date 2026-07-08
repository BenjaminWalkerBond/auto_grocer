"""Tests for request throttling."""

import asyncio
import time

import pytest


class TestThrottleConfig:
    """Tests for ThrottleConfig dataclass."""

    def test_default_values(self):
        """Should have sensible defaults."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig

        config = ThrottleConfig()

        assert config.max_concurrent == 3
        assert config.min_delay_ms == 200
        assert config.jitter_ms == 200
        assert config.enabled is True

    def test_custom_values(self):
        """Should accept custom configuration."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig

        config = ThrottleConfig(
            max_concurrent=5,
            min_delay_ms=100,
            jitter_ms=50,
            enabled=False,
        )

        assert config.max_concurrent == 5
        assert config.min_delay_ms == 100
        assert config.jitter_ms == 50
        assert config.enabled is False


class TestThrottler:
    """Tests for Throttler class."""

    @pytest.mark.asyncio
    async def test_limits_concurrency(self):
        """Should limit concurrent requests to max_concurrent."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig, Throttler

        config = ThrottleConfig(max_concurrent=2, min_delay_ms=0, jitter_ms=0)
        throttler = Throttler(config)

        concurrent_count = 0
        max_concurrent_observed = 0

        async def task():
            nonlocal concurrent_count, max_concurrent_observed
            async with throttler:
                concurrent_count += 1
                max_concurrent_observed = max(max_concurrent_observed, concurrent_count)
                await asyncio.sleep(0.05)
                concurrent_count -= 1

        # Run 5 tasks concurrently, but only 2 should run at a time
        await asyncio.gather(*[task() for _ in range(5)])

        assert max_concurrent_observed == 2

    @pytest.mark.asyncio
    async def test_enforces_minimum_delay(self):
        """Should enforce minimum delay between requests."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig, Throttler

        config = ThrottleConfig(max_concurrent=10, min_delay_ms=100, jitter_ms=0)
        throttler = Throttler(config)

        request_times = []

        async def task():
            async with throttler:
                request_times.append(time.monotonic())

        # Run 3 sequential requests
        for _ in range(3):
            await task()

        # Check delays between requests (skip first)
        for i in range(1, len(request_times)):
            delay_ms = (request_times[i] - request_times[i - 1]) * 1000
            # Allow 10ms tolerance for timing variance
            assert delay_ms >= 90, f"Delay was {delay_ms}ms, expected >= 90ms"

    @pytest.mark.asyncio
    async def test_jitter_adds_randomness(self):
        """Should add random jitter to delays."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig, Throttler

        config = ThrottleConfig(max_concurrent=10, min_delay_ms=0, jitter_ms=100)
        throttler = Throttler(config)

        delays = []
        last_time = time.monotonic()

        async def task():
            nonlocal last_time
            async with throttler:
                now = time.monotonic()
                delays.append(now - last_time)
                last_time = now

        # Run 10 sequential requests
        for _ in range(10):
            await task()

        # Skip first delay (no previous request)
        delays = delays[1:]

        # Jitter should create variance - not all delays should be identical
        unique_delays = len({round(d, 3) for d in delays})
        assert unique_delays > 1, "Jitter should create variance in delays"

    @pytest.mark.asyncio
    async def test_disabled_throttling_bypasses_limits(self):
        """Should bypass all limits when disabled."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig, Throttler

        config = ThrottleConfig(
            max_concurrent=1,
            min_delay_ms=1000,
            jitter_ms=1000,
            enabled=False,
        )
        throttler = Throttler(config)

        start = time.monotonic()

        async def task():
            async with throttler:
                pass

        # Run 5 concurrent tasks - should be near-instant when disabled
        await asyncio.gather(*[task() for _ in range(5)])

        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"Disabled throttling took {elapsed}s, should be instant"

    @pytest.mark.asyncio
    async def test_config_property_accessible(self):
        """Should expose config via property."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig, Throttler

        config = ThrottleConfig(max_concurrent=7)
        throttler = Throttler(config, name="test")

        assert throttler.config.max_concurrent == 7

    @pytest.mark.asyncio
    async def test_releases_semaphore_on_exception(self):
        """Should release semaphore even if task raises exception."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig, Throttler

        config = ThrottleConfig(max_concurrent=1, min_delay_ms=0, jitter_ms=0)
        throttler = Throttler(config)

        async def failing_task():
            async with throttler:
                raise ValueError("Task failed")

        # First task fails
        with pytest.raises(ValueError):
            await failing_task()

        # Second task should still be able to acquire the semaphore
        acquired = False

        async def second_task():
            nonlocal acquired
            async with throttler:
                acquired = True

        await asyncio.wait_for(second_task(), timeout=1.0)
        assert acquired, "Should be able to acquire after failed task"

    @pytest.mark.asyncio
    async def test_concurrent_delay_enforcement(self):
        """Should enforce delay even with concurrent requests."""
        from texas_grocery_mcp.reliability.throttle import ThrottleConfig, Throttler

        config = ThrottleConfig(max_concurrent=2, min_delay_ms=100, jitter_ms=0)
        throttler = Throttler(config)

        request_times = []
        lock = asyncio.Lock()

        async def task():
            async with throttler, lock:
                request_times.append(time.monotonic())

        # Run 4 concurrent tasks
        await asyncio.gather(*[task() for _ in range(4)])

        # Should have 4 timestamps
        assert len(request_times) == 4

        # Total time should be at least 100ms (delay between batches)
        total_time = max(request_times) - min(request_times)
        assert total_time >= 0.09, f"Total time {total_time}s should be >= 0.09s"
