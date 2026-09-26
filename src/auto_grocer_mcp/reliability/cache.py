"""Simple TTL cache for API responses."""

from datetime import datetime, timedelta
from typing import Generic, TypeVar

import structlog

logger = structlog.get_logger()

T = TypeVar("T")


class TTLCache(Generic[T]):
    """Simple in-memory cache with time-to-live expiration.

    Thread-safe for basic operations. Uses a dict for storage with
    (value, timestamp) tuples.

    Example:
        cache = TTLCache[ProductDetails](ttl_hours=24)
        cache.set("127074", product_details)
        details = cache.get("127074")  # Returns None if expired
    """

    def __init__(self, ttl_hours: int = 24, max_size: int = 1000):
        """Initialize the cache.

        Args:
            ttl_hours: Time-to-live in hours before entries expire
            max_size: Maximum number of entries to store
        """
        self._cache: dict[str, tuple[T, datetime]] = {}
        self._ttl = timedelta(hours=ttl_hours)
        self._max_size = max_size

    def get(self, key: str) -> T | None:
        """Get a value from the cache.

        Args:
            key: Cache key

        Returns:
            Cached value if present and not expired, None otherwise
        """
        if key not in self._cache:
            return None

        value, cached_at = self._cache[key]
        if datetime.now() - cached_at >= self._ttl:
            # Expired - remove and return None
            del self._cache[key]
            logger.debug("Cache entry expired", key=key)
            return None

        logger.debug("Cache hit", key=key)
        return value

    def set(self, key: str, value: T) -> None:
        """Store a value in the cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        # Evict oldest entries if at max size
        if len(self._cache) >= self._max_size and key not in self._cache:
            self._evict_oldest()

        self._cache[key] = (value, datetime.now())
        logger.debug("Cache set", key=key)

    def invalidate(self, key: str) -> None:
        """Remove a specific entry from the cache.

        Args:
            key: Cache key to remove
        """
        if key in self._cache:
            del self._cache[key]
            logger.debug("Cache entry invalidated", key=key)

    def clear(self) -> None:
        """Remove all entries from the cache."""
        count = len(self._cache)
        self._cache.clear()
        logger.info("Cache cleared", entries_removed=count)

    def _evict_oldest(self) -> None:
        """Remove the oldest entry from the cache."""
        if not self._cache:
            return

        oldest_key = min(self._cache, key=lambda k: self._cache[k][1])
        del self._cache[oldest_key]
        logger.debug("Cache evicted oldest entry", key=oldest_key)

    @property
    def size(self) -> int:
        """Current number of entries in the cache."""
        return len(self._cache)

    def stats(self) -> dict[str, int | float]:
        """Get cache statistics.

        Returns:
            Dict with cache stats (size, ttl_hours, max_size)
        """
        now = datetime.now()
        valid_count = sum(1 for _, (_, ts) in self._cache.items() if now - ts < self._ttl)
        return {
            "size": len(self._cache),
            "valid_entries": valid_count,
            "expired_entries": len(self._cache) - valid_count,
            "ttl_hours": self._ttl.total_seconds() / 3600,
            "max_size": self._max_size,
        }
