"""Tests for TTL cache."""

import time
from datetime import datetime, timedelta
from unittest.mock import patch

from texas_grocery_mcp.reliability.cache import TTLCache


class TestTTLCache:
    """Tests for TTLCache class."""

    def test_set_and_get(self):
        """Cache should store and retrieve values."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1)

        cache.set("key1", "value1")
        result = cache.get("key1")

        assert result == "value1"

    def test_get_missing_key(self):
        """Cache should return None for missing keys."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1)

        result = cache.get("nonexistent")

        assert result is None

    def test_expired_entry_returns_none(self):
        """Cache should return None for expired entries."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1)
        cache.set("key1", "value1")

        # Mock time to be 2 hours in the future
        future_time = datetime.now() + timedelta(hours=2)
        with patch("texas_grocery_mcp.reliability.cache.datetime") as mock_datetime:
            mock_datetime.now.return_value = future_time

            result = cache.get("key1")

        assert result is None

    def test_expired_entry_is_removed(self):
        """Expired entries should be removed from cache."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1)
        cache.set("key1", "value1")

        # Mock time to be 2 hours in the future
        future_time = datetime.now() + timedelta(hours=2)
        with patch("texas_grocery_mcp.reliability.cache.datetime") as mock_datetime:
            mock_datetime.now.return_value = future_time
            cache.get("key1")  # This should remove the entry

        assert cache.size == 0

    def test_invalidate_removes_entry(self):
        """Invalidate should remove specific entry."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.invalidate("key1")

        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

    def test_invalidate_nonexistent_key(self):
        """Invalidating nonexistent key should not error."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1)

        cache.invalidate("nonexistent")  # Should not raise

    def test_clear_removes_all_entries(self):
        """Clear should remove all entries."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1)
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        cache.clear()

        assert cache.size == 0
        assert cache.get("key1") is None

    def test_max_size_eviction(self):
        """Cache should evict oldest entry when at max size."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1, max_size=3)

        cache.set("key1", "value1")
        time.sleep(0.01)  # Ensure different timestamps
        cache.set("key2", "value2")
        time.sleep(0.01)
        cache.set("key3", "value3")
        time.sleep(0.01)
        cache.set("key4", "value4")  # Should evict key1

        assert cache.size == 3
        assert cache.get("key1") is None  # Evicted
        assert cache.get("key2") == "value2"
        assert cache.get("key4") == "value4"

    def test_update_existing_key(self):
        """Updating existing key should not trigger eviction."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1, max_size=3)

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")
        cache.set("key1", "updated_value1")  # Update, not new entry

        assert cache.size == 3
        assert cache.get("key1") == "updated_value1"

    def test_stats_returns_info(self):
        """Stats should return cache information."""
        cache: TTLCache[str] = TTLCache(ttl_hours=24, max_size=100)
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        stats = cache.stats()

        assert stats["size"] == 2
        assert stats["valid_entries"] == 2
        assert stats["expired_entries"] == 0
        assert stats["ttl_hours"] == 24
        assert stats["max_size"] == 100

    def test_stats_shows_expired_entries(self):
        """Stats should count expired entries separately."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1, max_size=100)
        cache.set("key1", "value1")

        # Mock time to be 2 hours in the future
        future_time = datetime.now() + timedelta(hours=2)
        with patch("texas_grocery_mcp.reliability.cache.datetime") as mock_datetime:
            mock_datetime.now.return_value = future_time

            stats = cache.stats()

        assert stats["size"] == 1
        assert stats["valid_entries"] == 0
        assert stats["expired_entries"] == 1

    def test_generic_type_support(self):
        """Cache should work with different types."""
        # Dict cache
        dict_cache: TTLCache[dict] = TTLCache(ttl_hours=1)
        dict_cache.set("data", {"name": "test", "value": 42})
        assert dict_cache.get("data") == {"name": "test", "value": 42}

        # List cache
        list_cache: TTLCache[list] = TTLCache(ttl_hours=1)
        list_cache.set("items", [1, 2, 3])
        assert list_cache.get("items") == [1, 2, 3]

    def test_size_property(self):
        """Size property should return entry count."""
        cache: TTLCache[str] = TTLCache(ttl_hours=1)

        assert cache.size == 0

        cache.set("key1", "value1")
        assert cache.size == 1

        cache.set("key2", "value2")
        assert cache.size == 2

        cache.invalidate("key1")
        assert cache.size == 1
