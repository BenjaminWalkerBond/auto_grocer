"""Tests for structured logging."""

import json
import sys
from io import StringIO


def test_logger_outputs_json():
    """Logger should output JSON to stderr."""
    from texas_grocery_mcp.observability.logging import configure_logging, get_logger

    # Capture stderr
    captured = StringIO()
    original_stderr = sys.stderr

    try:
        sys.stderr = captured
        configure_logging(log_level="DEBUG")
        logger = get_logger("test")
        logger.info("test message", key="value")

        # Force flush
        sys.stderr.flush()
        output = captured.getvalue()

        # Should be valid JSON
        lines = [line for line in output.strip().split("\n") if line]
        assert len(lines) >= 1

        log_entry = json.loads(lines[-1])
        assert log_entry["event"] == "test message"
        assert log_entry["key"] == "value"
    finally:
        sys.stderr = original_stderr


def test_logger_includes_timestamp():
    """Logger should include ISO timestamp."""
    from texas_grocery_mcp.observability.logging import configure_logging, get_logger

    captured = StringIO()
    original_stderr = sys.stderr

    try:
        sys.stderr = captured
        configure_logging()
        logger = get_logger("test")
        logger.info("test")
        sys.stderr.flush()

        output = captured.getvalue()
        lines = [line for line in output.strip().split("\n") if line]
        log_entry = json.loads(lines[-1])

        assert "timestamp" in log_entry
        assert "T" in log_entry["timestamp"]  # ISO format
    finally:
        sys.stderr = original_stderr
