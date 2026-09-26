"""Structured JSON logging configuration."""

import logging
import os
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from structlog.types import Processor

from auto_grocer_mcp.utils.config import get_settings

# Vendored libraries that log per-operation chatter at INFO. On an MCP stdio
# server every one of these lands in the client's log, where it drowns the
# messages that actually explain a failure:
#   * httpx / httpcore   - one "HTTP Request: POST .../graphql 200 OK" per call
#   * mcp.server.lowlevel - one "Processing request of type XRequest" per request
#   * nodriver / uc       - a ~20-line Chromium argv dump per browser launch
#   * websockets          - CDP frame chatter
# They are pinned to WARNING so real problems still surface. Set
# AUTO_GROCER_VERBOSE_LOGS=1 to get the full detail back while debugging.
_NOISY_LIBRARY_LOGGERS = (
    "httpx",
    "httpcore",
    "mcp.server.lowlevel.server",
    "nodriver",
    "uc",
    "websockets",
)


def _verbose_logs_enabled() -> bool:
    """Return True when the operator asked for full third-party log detail."""
    return os.environ.get("AUTO_GROCER_VERBOSE_LOGS", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def add_timestamp(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """Add ISO timestamp to log entry."""
    try:
        from datetime import UTC
    except ImportError:  # Python < 3.11
        from datetime import timezone as _timezone
        UTC = _timezone.utc
    from datetime import datetime

    event_dict["timestamp"] = datetime.now(UTC).isoformat()
    return event_dict


def configure_logging(log_level: str | None = None) -> None:
    """Configure structured JSON logging.

    Logs to stderr to keep stdout clean for MCP protocol.
    """
    settings = get_settings()
    level = log_level or settings.log_level

    # Shared processors for all loggers
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        add_timestamp,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    # Configure structlog
    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure stdlib logging
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(getattr(logging, level.upper()))

    # Keep the stderr stream readable: pin chatty vendored loggers to WARNING
    # unless the operator explicitly asked for the detail.
    library_level = logging.NOTSET if _verbose_logs_enabled() else logging.WARNING
    for name in _NOISY_LIBRARY_LOGGERS:
        logging.getLogger(name).setLevel(library_level)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Get a structured logger instance."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
