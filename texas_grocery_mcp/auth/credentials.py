"""Secure credential storage for automatic login.

This module provides cross-platform secure credential storage using:
1. OS keyring (primary) - macOS Keychain, Windows Credential Manager, Linux Secret Service
2. Encrypted file (fallback) - Fernet symmetric encryption when keyring unavailable

Security guarantees:
- Credentials are always encrypted at rest
- File permissions restricted to owner-only (0o600)
- Password values are never logged
"""

import json
import os
import stat
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger()

SERVICE_NAME = "texas-grocery-mcp"
CREDENTIALS_FILENAME = ".credentials"
KEY_FILENAME = ".credentials.key"

# Check if keyring is available
try:
    import keyring
    from keyring.errors import KeyringError

    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False
    keyring = None  # type: ignore[assignment]
    KeyringError = Exception  # type: ignore[misc, assignment]

# Check if cryptography is available for fallback
try:
    from cryptography.fernet import Fernet, InvalidToken

    CRYPTOGRAPHY_AVAILABLE = True
except ImportError:
    CRYPTOGRAPHY_AVAILABLE = False
    Fernet = None  # type: ignore[misc, assignment]
    InvalidToken = Exception  # type: ignore[misc, assignment]


class CredentialError(Exception):
    """Raised when credential operations fail."""

    pass


class CredentialStore:
    """Secure credential storage with keyring + encrypted file fallback.

    Usage:
        store = CredentialStore(auth_dir=Path("~/.texas-grocery-mcp"))
        store.save("user@example.com", "password123")
        creds = store.get()  # Returns ("user@example.com", "password123") or None
        store.clear()
    """

    def __init__(self, auth_dir: Path):
        """Initialize credential store.

        Args:
            auth_dir: Directory for storing encrypted credentials file (fallback)
        """
        self.auth_dir = auth_dir.expanduser()
        self._use_keyring = self._check_keyring_available()

        if self._use_keyring:
            logger.debug("Using OS keyring for credential storage")
        elif CRYPTOGRAPHY_AVAILABLE:
            logger.debug("Using encrypted file for credential storage")
        else:
            logger.warning(
                "Neither keyring nor cryptography available - credential storage disabled"
            )

    def _check_keyring_available(self) -> bool:
        """Check if OS keyring is available and functional."""
        if not KEYRING_AVAILABLE:
            return False

        try:
            # Try a test operation to verify keyring backend works
            # Some systems have keyring installed but no working backend
            keyring.get_password(SERVICE_NAME, "__availability_test__")
            return True
        except KeyringError:
            logger.debug("Keyring backend not functional, using fallback")
            return False
        except Exception as e:
            logger.debug("Keyring check failed", error=str(e))
            return False

    def _get_or_create_key(self) -> bytes:
        """Get or create encryption key for file-based storage."""
        if not CRYPTOGRAPHY_AVAILABLE:
            raise CredentialError("cryptography library not installed")

        self.auth_dir.mkdir(parents=True, exist_ok=True)
        key_path = self.auth_dir / KEY_FILENAME

        if key_path.exists():
            return key_path.read_bytes()

        # Generate new key
        key = Fernet.generate_key()
        key_path.write_bytes(key)

        # Set restrictive permissions (owner read/write only)
        os.chmod(key_path, stat.S_IRUSR | stat.S_IWUSR)

        logger.debug("Created new encryption key", path=str(key_path))
        return key

    def _save_encrypted(self, email: str, password: str) -> dict[str, Any]:
        """Save credentials to encrypted file."""
        if not CRYPTOGRAPHY_AVAILABLE:
            raise CredentialError(
                "Cannot save credentials: cryptography library not installed. "
                "Install with: pip install cryptography"
            )

        try:
            key = self._get_or_create_key()
            fernet = Fernet(key)

            data = json.dumps({"email": email, "password": password})
            encrypted = fernet.encrypt(data.encode())

            creds_path = self.auth_dir / CREDENTIALS_FILENAME
            creds_path.write_bytes(encrypted)

            # Set restrictive permissions
            os.chmod(creds_path, stat.S_IRUSR | stat.S_IWUSR)

            logger.info(
                "Credentials saved to encrypted file",
                path=str(creds_path),
                email_masked=self._mask_email(email),
            )
            return {"method": "encrypted_file", "success": True}

        except Exception as e:
            logger.error("Failed to save credentials to encrypted file", error=str(e))
            raise CredentialError(f"Failed to save credentials: {e}") from e

    def _get_encrypted(self) -> tuple[str, str] | None:
        """Retrieve credentials from encrypted file."""
        if not CRYPTOGRAPHY_AVAILABLE:
            return None

        creds_path = self.auth_dir / CREDENTIALS_FILENAME
        key_path = self.auth_dir / KEY_FILENAME

        if not creds_path.exists() or not key_path.exists():
            return None

        try:
            key = key_path.read_bytes()
            fernet = Fernet(key)
            encrypted = creds_path.read_bytes()
            decrypted = fernet.decrypt(encrypted)
            data = json.loads(decrypted.decode())

            email = data.get("email")
            password = data.get("password")

            if email and password:
                logger.debug(
                    "Retrieved credentials from encrypted file",
                    email_masked=self._mask_email(email),
                )
                return (email, password)

            return None

        except InvalidToken:
            logger.warning("Encrypted credentials file corrupted or key mismatch")
            return None
        except Exception as e:
            logger.error("Failed to read encrypted credentials", error=str(e))
            return None

    def _clear_encrypted(self) -> None:
        """Remove encrypted credentials file."""
        creds_path = self.auth_dir / CREDENTIALS_FILENAME

        if creds_path.exists():
            creds_path.unlink()
            logger.debug("Deleted encrypted credentials file")

        # Optionally keep the key for future use, but remove credentials
        # Key can be regenerated if needed

    def _mask_email(self, email: str) -> str:
        """Mask email for safe logging (e.g., u***r@example.com)."""
        if not email or "@" not in email:
            return "***"

        local, domain = email.split("@", 1)
        if len(local) <= 2:
            masked_local = "*" * len(local)
        else:
            masked_local = local[0] + "*" * (len(local) - 2) + local[-1]

        return f"{masked_local}@{domain}"

    def save(self, email: str, password: str) -> dict[str, Any]:
        """Save credentials securely.

        Args:
            email: HEB account email
            password: HEB account password

        Returns:
            dict with success status and storage method used

        Raises:
            CredentialError: If credentials cannot be saved
        """
        if not email or not password:
            raise CredentialError("Email and password are required")

        if self._use_keyring:
            try:
                keyring.set_password(SERVICE_NAME, "email", email)
                keyring.set_password(SERVICE_NAME, "password", password)

                logger.info(
                    "Credentials saved to OS keyring",
                    email_masked=self._mask_email(email),
                )
                return {"method": "keyring", "success": True}

            except KeyringError as e:
                logger.warning(
                    "Keyring save failed, falling back to encrypted file",
                    error=str(e),
                )
                # Fall through to encrypted file
                self._use_keyring = False

        return self._save_encrypted(email, password)

    def get(self) -> tuple[str, str] | None:
        """Retrieve stored credentials.

        Returns:
            Tuple of (email, password) or None if no credentials stored
        """
        if self._use_keyring:
            try:
                email = keyring.get_password(SERVICE_NAME, "email")
                password = keyring.get_password(SERVICE_NAME, "password")

                if email and password:
                    logger.debug(
                        "Retrieved credentials from OS keyring",
                        email_masked=self._mask_email(email),
                    )
                    return (email, password)

            except KeyringError as e:
                logger.warning("Keyring read failed", error=str(e))

        # Try encrypted file as fallback
        return self._get_encrypted()

    def clear(self) -> dict[str, Any]:
        """Remove stored credentials.

        Returns:
            dict with success status
        """
        errors = []

        if self._use_keyring:
            try:
                # keyring.delete_password raises if not found, so check first
                if keyring.get_password(SERVICE_NAME, "email"):
                    keyring.delete_password(SERVICE_NAME, "email")
                if keyring.get_password(SERVICE_NAME, "password"):
                    keyring.delete_password(SERVICE_NAME, "password")
                logger.info("Cleared credentials from OS keyring")
            except KeyringError as e:
                errors.append(f"Keyring: {e}")

        # Always try to clear encrypted file too
        try:
            self._clear_encrypted()
        except Exception as e:
            errors.append(f"Encrypted file: {e}")

        if errors:
            logger.warning("Some credential sources could not be cleared", errors=errors)

        return {"success": True, "cleared": True}

    def has_credentials(self) -> bool:
        """Check if credentials are stored (without retrieving them).

        Returns:
            True if credentials are available
        """
        return self.get() is not None

    def get_storage_info(self) -> dict[str, Any]:
        """Get information about credential storage (for session_status).

        Returns:
            dict with storage method and availability, never exposes actual credentials
        """
        has_creds = self.has_credentials()

        if self._use_keyring:
            method = "keyring"
            backend = "OS keyring (secure)"
        elif CRYPTOGRAPHY_AVAILABLE:
            method = "encrypted_file"
            backend = "Encrypted file"
        else:
            method = "none"
            backend = "Not available"

        return {
            "credentials_stored": has_creds,
            "storage_method": method,
            "storage_backend": backend,
            "keyring_available": KEYRING_AVAILABLE and self._use_keyring,
            "encryption_available": CRYPTOGRAPHY_AVAILABLE,
        }
