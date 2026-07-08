"""Tests for credential storage module."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestCredentialStore:
    """Tests for CredentialStore class."""

    @pytest.fixture
    def temp_auth_dir(self, tmp_path):
        """Create a temporary auth directory."""
        auth_dir = tmp_path / ".texas-grocery-mcp"
        auth_dir.mkdir(parents=True)
        return auth_dir

    @pytest.fixture
    def mock_keyring_unavailable(self):
        """Mock keyring as unavailable."""
        with patch("texas_grocery_mcp.auth.credentials.KEYRING_AVAILABLE", False):
            yield

    @pytest.fixture
    def mock_keyring_available(self):
        """Mock keyring as available."""
        mock_keyring = MagicMock()
        mock_keyring.get_password.return_value = None  # No existing credentials
        mock_keyring.set_password.return_value = None
        mock_keyring.delete_password.return_value = None

        with (
            patch("texas_grocery_mcp.auth.credentials.KEYRING_AVAILABLE", True),
            patch("texas_grocery_mcp.auth.credentials.keyring", mock_keyring),
        ):
            yield mock_keyring

    def test_init_with_keyring_available(self, temp_auth_dir, mock_keyring_available):
        """Should use keyring when available."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        assert store._use_keyring is True

    def test_init_without_keyring(self, temp_auth_dir, mock_keyring_unavailable):
        """Should fall back to encrypted file when keyring unavailable."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        assert store._use_keyring is False

    def test_save_with_keyring(self, temp_auth_dir, mock_keyring_available):
        """Should save credentials to keyring when available."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        result = store.save("test@example.com", "password123")

        assert result["success"] is True
        assert result["method"] == "keyring"

        # Verify keyring was called correctly
        mock_keyring_available.set_password.assert_any_call(
            "texas-grocery-mcp", "email", "test@example.com"
        )
        mock_keyring_available.set_password.assert_any_call(
            "texas-grocery-mcp", "password", "password123"
        )

    def test_save_encrypted_file(self, temp_auth_dir, mock_keyring_unavailable):
        """Should save credentials to encrypted file when keyring unavailable."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        result = store.save("test@example.com", "password123")

        assert result["success"] is True
        assert result["method"] == "encrypted_file"

        # Verify files were created
        assert (temp_auth_dir / ".credentials").exists()
        assert (temp_auth_dir / ".credentials.key").exists()

    def test_encrypted_file_permissions(self, temp_auth_dir, mock_keyring_unavailable):
        """Encrypted files should have restrictive permissions (0o600)."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        store.save("test@example.com", "password123")

        creds_path = temp_auth_dir / ".credentials"
        key_path = temp_auth_dir / ".credentials.key"

        # Check permissions (owner read/write only)
        creds_mode = stat.S_IMODE(os.stat(creds_path).st_mode)
        key_mode = stat.S_IMODE(os.stat(key_path).st_mode)

        assert creds_mode == 0o600
        assert key_mode == 0o600

    def test_encrypted_file_not_plaintext(self, temp_auth_dir, mock_keyring_unavailable):
        """Encrypted credentials file should not contain plaintext password."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        store.save("test@example.com", "supersecretpassword")

        creds_path = temp_auth_dir / ".credentials"
        content = creds_path.read_bytes()

        # Password should NOT appear in plaintext
        assert b"supersecretpassword" not in content
        # File should be encrypted (not JSON)
        with pytest.raises(json.JSONDecodeError):
            json.loads(content.decode())

    def test_get_with_keyring(self, temp_auth_dir, mock_keyring_available):
        """Should retrieve credentials from keyring."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        # Configure mock to return credentials
        def mock_get_password(service, key):
            if key == "email":
                return "test@example.com"
            elif key == "password":
                return "password123"
            return None

        mock_keyring_available.get_password.side_effect = mock_get_password

        store = CredentialStore(temp_auth_dir)
        result = store.get()

        assert result == ("test@example.com", "password123")

    def test_get_encrypted_file(self, temp_auth_dir, mock_keyring_unavailable):
        """Should retrieve credentials from encrypted file."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        store.save("test@example.com", "password123")

        # Create new store instance to simulate fresh retrieval
        store2 = CredentialStore(temp_auth_dir)
        result = store2.get()

        assert result == ("test@example.com", "password123")

    def test_get_returns_none_when_no_credentials(
        self, temp_auth_dir, mock_keyring_unavailable
    ):
        """Should return None when no credentials stored."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        result = store.get()

        assert result is None

    def test_clear_with_keyring(self, temp_auth_dir, mock_keyring_available):
        """Should clear credentials from keyring."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        # Configure mock to return existing credentials
        mock_keyring_available.get_password.return_value = "exists"

        store = CredentialStore(temp_auth_dir)
        result = store.clear()

        assert result["success"] is True
        mock_keyring_available.delete_password.assert_called()

    def test_clear_encrypted_file(self, temp_auth_dir, mock_keyring_unavailable):
        """Should clear encrypted credentials file."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        store.save("test@example.com", "password123")

        assert (temp_auth_dir / ".credentials").exists()

        store.clear()

        assert not (temp_auth_dir / ".credentials").exists()

    def test_has_credentials_true(self, temp_auth_dir, mock_keyring_unavailable):
        """Should return True when credentials are stored."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        store.save("test@example.com", "password123")

        assert store.has_credentials() is True

    def test_has_credentials_false(self, temp_auth_dir, mock_keyring_unavailable):
        """Should return False when no credentials stored."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)

        assert store.has_credentials() is False

    def test_get_storage_info(self, temp_auth_dir, mock_keyring_unavailable):
        """Should return storage info without exposing credentials."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)

        # Before saving
        info = store.get_storage_info()
        assert info["credentials_stored"] is False
        assert info["storage_method"] == "encrypted_file"
        assert "password" not in str(info).lower()

        # After saving
        store.save("test@example.com", "password123")
        info = store.get_storage_info()
        assert info["credentials_stored"] is True

    def test_save_requires_email_and_password(
        self, temp_auth_dir, mock_keyring_unavailable
    ):
        """Should raise error when email or password missing."""
        from texas_grocery_mcp.auth.credentials import CredentialError, CredentialStore

        store = CredentialStore(temp_auth_dir)

        with pytest.raises(CredentialError, match="Email and password are required"):
            store.save("", "password123")

        with pytest.raises(CredentialError, match="Email and password are required"):
            store.save("test@example.com", "")

    def test_mask_email(self, temp_auth_dir, mock_keyring_unavailable):
        """Should mask email addresses for safe logging."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)

        # Normal email
        assert store._mask_email("user@example.com") == "u**r@example.com"

        # Short local part
        assert store._mask_email("ab@example.com") == "**@example.com"

        # Long local part
        assert store._mask_email("johndoe@example.com") == "j*****e@example.com"

        # Invalid email
        assert store._mask_email("invalid") == "***"
        assert store._mask_email("") == "***"

    def test_credential_round_trip(self, temp_auth_dir, mock_keyring_unavailable):
        """Should be able to save and retrieve the same credentials."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        original_email = "test.user+tag@subdomain.example.com"
        original_password = "p@$$w0rd!with#special&chars"

        store = CredentialStore(temp_auth_dir)
        store.save(original_email, original_password)

        # Fresh store instance
        store2 = CredentialStore(temp_auth_dir)
        retrieved = store2.get()

        assert retrieved == (original_email, original_password)

    def test_overwrite_existing_credentials(
        self, temp_auth_dir, mock_keyring_unavailable
    ):
        """Should overwrite existing credentials when saving new ones."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)

        # Save initial credentials
        store.save("old@example.com", "oldpassword")

        # Save new credentials
        store.save("new@example.com", "newpassword")

        # Should return new credentials
        result = store.get()
        assert result == ("new@example.com", "newpassword")


class TestCredentialStoreEdgeCases:
    """Edge case tests for CredentialStore."""

    @pytest.fixture
    def temp_auth_dir(self, tmp_path):
        """Create a temporary auth directory."""
        auth_dir = tmp_path / ".texas-grocery-mcp"
        auth_dir.mkdir(parents=True)
        return auth_dir

    @pytest.fixture
    def mock_keyring_unavailable(self):
        """Mock keyring as unavailable."""
        with patch("texas_grocery_mcp.auth.credentials.KEYRING_AVAILABLE", False):
            yield

    def test_corrupted_key_file(self, temp_auth_dir, mock_keyring_unavailable):
        """Should handle corrupted key file gracefully."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        store.save("test@example.com", "password123")

        # Corrupt the key file
        key_path = temp_auth_dir / ".credentials.key"
        key_path.write_bytes(b"corrupted")

        # Fresh store should return None (can't decrypt)
        store2 = CredentialStore(temp_auth_dir)
        result = store2.get()

        assert result is None

    def test_missing_key_file(self, temp_auth_dir, mock_keyring_unavailable):
        """Should handle missing key file gracefully."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(temp_auth_dir)
        store.save("test@example.com", "password123")

        # Delete the key file
        (temp_auth_dir / ".credentials.key").unlink()

        # Fresh store should return None
        store2 = CredentialStore(temp_auth_dir)
        result = store2.get()

        assert result is None

    def test_auth_dir_created_if_not_exists(self, tmp_path, mock_keyring_unavailable):
        """Should create auth directory if it doesn't exist."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        auth_dir = tmp_path / "nonexistent" / "nested" / "path"
        assert not auth_dir.exists()

        store = CredentialStore(auth_dir)
        store.save("test@example.com", "password123")

        assert auth_dir.exists()
        assert (auth_dir / ".credentials").exists()

    def test_path_with_tilde_expansion(self, mock_keyring_unavailable):
        """Should expand ~ in path."""
        from texas_grocery_mcp.auth.credentials import CredentialStore

        store = CredentialStore(Path("~/.test-credentials"))

        # Should not have ~ in the path
        assert "~" not in str(store.auth_dir)
