"""Tests for structured logging."""

import json
import logging
import sys
from io import StringIO

import pytest


def test_logger_outputs_json():
    """Logger should output JSON to stderr."""
    from auto_grocer_mcp.observability.logging import configure_logging, get_logger

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
    from auto_grocer_mcp.observability.logging import configure_logging, get_logger

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


# ---------------------------------------------------------------------------
# Third-party log noise
# ---------------------------------------------------------------------------
# The MCP stderr stream is what a human (and the agent) reads when something
# breaks, so it must carry signal. At INFO the vendored libraries drowned it:
# one "Processing request of type ListToolsRequest" per MCP request, one
# "HTTP Request: POST .../graphql" per GraphQL call, and a ~20-line nodriver
# Chromium argv dump per browser launch.

_NOISY = ["httpx", "httpcore", "mcp.server.lowlevel.server", "nodriver", "uc", "websockets"]


@pytest.mark.parametrize("logger_name", _NOISY)
def test_noisy_third_party_loggers_are_quiet_by_default(logger_name, monkeypatch):
    """Chatty vendored loggers must not emit INFO into the MCP stderr stream."""
    from auto_grocer_mcp.observability.logging import configure_logging

    monkeypatch.delenv("AUTO_GROCER_VERBOSE_LOGS", raising=False)
    configure_logging()

    logger = logging.getLogger(logger_name)
    assert not logger.isEnabledFor(logging.INFO), (
        f"{logger_name} still logs at INFO"
    )
    # Real problems must still surface.
    assert logger.isEnabledFor(logging.WARNING)


@pytest.mark.parametrize("logger_name", _NOISY)
def test_verbose_env_restores_third_party_info_logs(logger_name, monkeypatch):
    """AUTO_GROCER_VERBOSE_LOGS=1 brings the detail back for debugging."""
    from auto_grocer_mcp.observability.logging import configure_logging

    monkeypatch.setenv("AUTO_GROCER_VERBOSE_LOGS", "1")
    try:
        configure_logging()
        assert logging.getLogger(logger_name).isEnabledFor(logging.INFO)
    finally:
        monkeypatch.delenv("AUTO_GROCER_VERBOSE_LOGS", raising=False)
        configure_logging()


def test_our_own_loggers_still_log_at_info(monkeypatch):
    """Silencing vendored libraries must not silence auto_grocer itself."""
    from auto_grocer_mcp.observability.logging import configure_logging

    monkeypatch.delenv("AUTO_GROCER_VERBOSE_LOGS", raising=False)
    configure_logging()

    assert logging.getLogger("auto_grocer_mcp.clients.graphql").isEnabledFor(
        logging.INFO
    )
