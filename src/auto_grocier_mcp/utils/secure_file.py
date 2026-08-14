"""Secure file operations for sensitive data."""

import json
import os
import stat
from contextlib import suppress
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

# File permissions: owner read/write only (0o600)
SECURE_FILE_MODE = stat.S_IRUSR | stat.S_IWUSR

# Directory permissions: owner read/write/execute only (0o700)
SECURE_DIR_MODE = stat.S_IRWXU


def write_secure_json(path: Path, data: Any, indent: int = 2) -> None:
    """Write JSON data to a file with secure permissions.

    Creates the file with 0o600 permissions (owner read/write only).
    If the file exists, ensures permissions are correct before writing.

    Args:
        path: Path to write to
        data: Data to serialize as JSON
        indent: JSON indentation level

    Raises:
        OSError: If file operations fail
    """
    # Ensure path is a Path object
    path = Path(path)

    # Ensure parent directory exists with secure permissions
    path.parent.mkdir(parents=True, exist_ok=True)

    # Set directory permissions to 0o700 (owner only)
    try:
        os.chmod(path.parent, SECURE_DIR_MODE)
    except OSError as e:
        logger.warning(
            "Could not set directory permissions",
            path=str(path.parent),
            error=str(e),
        )

    # Write to a temp file first, then rename (atomic on POSIX)
    temp_path = path.with_suffix(".tmp")

    try:
        # Create file with secure permissions using os.open
        fd = os.open(
            temp_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            SECURE_FILE_MODE,
        )

        try:
            with os.fdopen(fd, "w") as f:
                json.dump(data, f, indent=indent)
        except Exception:
            # fd is closed by fdopen even on error, but if fdopen fails
            # we need to close it manually
            with suppress(OSError):
                os.close(fd)
            raise

        # Atomic rename
        os.replace(temp_path, path)

        logger.debug(
            "Wrote secure file",
            path=str(path),
            mode=oct(SECURE_FILE_MODE),
        )

    except Exception:
        # Clean up temp file if it exists
        if temp_path.exists():
            with suppress(OSError):
                temp_path.unlink()
        raise


def ensure_secure_permissions(path: Path) -> bool:
    """Ensure a file has secure permissions (0o600).

    Args:
        path: Path to check/fix

    Returns:
        True if permissions are now secure, False if unable to fix
    """
    path = Path(path)

    if not path.exists():
        return True

    try:
        current_mode = path.stat().st_mode & 0o777

        if current_mode != SECURE_FILE_MODE:
            os.chmod(path, SECURE_FILE_MODE)
            logger.info(
                "Fixed file permissions",
                path=str(path),
                old_mode=oct(current_mode),
                new_mode=oct(SECURE_FILE_MODE),
            )

        return True

    except OSError as e:
        logger.warning(
            "Could not fix file permissions",
            path=str(path),
            error=str(e),
        )
        return False
