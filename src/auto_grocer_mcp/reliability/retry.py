"""Retry logic with exponential backoff and jitter."""

import asyncio
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from functools import wraps
from typing import ParamSpec, TypeVar

import structlog

logger = structlog.get_logger()

P = ParamSpec("P")
T = TypeVar("T")

# Exceptions that should trigger retry
RETRYABLE_EXCEPTIONS: tuple[type[Exception], ...] = (
    ConnectionError,
    TimeoutError,
    OSError,
)


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0
    exponential_base: float = 2.0
    jitter: bool = True
    retryable_exceptions: tuple[type[Exception], ...] = field(
        default_factory=lambda: RETRYABLE_EXCEPTIONS
    )


def calculate_delay(attempt: int, config: RetryConfig) -> float:
    """Calculate delay for next retry attempt."""
    delay = config.base_delay * (config.exponential_base ** (attempt - 1))
    delay = min(delay, config.max_delay)

    if config.jitter:
        delay = delay * (0.5 + random.random())

    return delay


def with_retry(
    config: RetryConfig | None = None,
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator for async functions with retry logic.

    Args:
        config: Retry configuration. Uses defaults if not provided.

    Returns:
        Decorated function that retries on transient failures.
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(func)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            last_exception: Exception | None = None

            for attempt in range(1, config.max_attempts + 1):
                try:
                    return await func(*args, **kwargs)
                except config.retryable_exceptions as e:
                    last_exception = e
                    if attempt < config.max_attempts:
                        delay = calculate_delay(attempt, config)
                        logger.warning(
                            "Retry attempt",
                            function=func.__name__,
                            attempt=attempt,
                            max_attempts=config.max_attempts,
                            delay=delay,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)
                except Exception:
                    # Non-retryable exception, raise immediately
                    raise

            # Exhausted all retries
            if last_exception:
                raise last_exception
            raise RuntimeError("Unexpected retry state")

        return wrapper

    return decorator
