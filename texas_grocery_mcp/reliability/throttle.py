"""Request throttling to prevent rate limiting."""

import asyncio
import random
import time
from dataclasses import dataclass
from types import TracebackType

import structlog

logger = structlog.get_logger()


@dataclass
class ThrottleConfig:
    """Configuration for request throttling."""

    max_concurrent: int = 3
    """Maximum concurrent requests allowed."""

    min_delay_ms: int = 200
    """Minimum delay between requests in milliseconds."""

    jitter_ms: int = 200
    """Random jitter added to delay (0 to jitter_ms)."""

    enabled: bool = True
    """Whether throttling is enabled."""


class Throttler:
    """
    Semaphore-based request throttler with delay and jitter.

    Limits concurrent requests and enforces minimum delays between requests
    to prevent overwhelming external APIs with burst traffic.

    Usage:
        throttler = Throttler(ThrottleConfig(max_concurrent=3))

        async with throttler:
            await make_request()
    """

    def __init__(self, config: ThrottleConfig, name: str = "default"):
        """Initialize throttler with configuration.

        Args:
            config: Throttling configuration
            name: Name for logging purposes
        """
        self._config = config
        self._name = name
        self._semaphore = asyncio.Semaphore(config.max_concurrent)
        self._last_request_time: float = 0
        self._lock = asyncio.Lock()

    @property
    def config(self) -> ThrottleConfig:
        """Get the throttle configuration."""
        return self._config

    async def __aenter__(self) -> "Throttler":
        """Acquire throttle slot, waiting if necessary."""
        if not self._config.enabled:
            return self

        await self._semaphore.acquire()

        try:
            await self._wait_for_delay()
        except Exception:
            self._semaphore.release()
            raise

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Release throttle slot and record request time."""
        if not self._config.enabled:
            return

        async with self._lock:
            self._last_request_time = time.monotonic()

        self._semaphore.release()

    async def _wait_for_delay(self) -> None:
        """Wait for minimum delay + jitter since last request."""
        async with self._lock:
            now = time.monotonic()
            min_delay = self._config.min_delay_ms / 1000.0
            elapsed = now - self._last_request_time

            wait_time = min_delay - elapsed if elapsed < min_delay else 0

            # Add jitter to make traffic pattern less predictable
            if self._config.jitter_ms > 0:
                jitter = random.uniform(0, self._config.jitter_ms / 1000.0)
                wait_time += jitter

        if wait_time > 0:
            logger.debug(
                "Throttling request",
                throttler=self._name,
                wait_ms=int(wait_time * 1000),
            )
            await asyncio.sleep(wait_time)
