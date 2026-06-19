"""
Tests for credential management utilities.
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

# Ensure test environment
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-credentials-tests")

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from orchestrator.api.credentials import (
    decrypt_credential,
    encrypt_credential,
    get_env_credentials,
    mask_credential,
)


class TestCredentialEncryption:
    """Test encrypt_credential and decrypt_credential functions."""

    def test_round_trip(self):
        """Encrypt then decrypt should return original value."""
        original = "secret_password_123"
        encrypted = encrypt_credential(original)
        assert encrypted != original
        assert decrypt_credential(encrypted) == original

    def test_empty_string_handling(self):
        """Empty string should return empty string for both functions."""
        assert encrypt_credential("") == ""
        assert decrypt_credential("") == ""
        assert encrypt_credential(None) == ""
        assert decrypt_credential(None) == ""

    def test_different_lengths(self):
        """Test encryption with various string lengths."""
        test_cases = [
            "a",
            "abc",
            "very_long_secret_string_that_goes_on_and_on_and_on_1234567890!@#$%^&*()",
            "short",
        ]
        for original in test_cases:
            encrypted = encrypt_credential(original)
            assert decrypt_credential(encrypted) == original

    def test_invalid_decryption(self):
        """Decrypting invalid tokens should return empty string."""
        assert decrypt_credential("not-a-valid-fernet-token") == ""
        assert decrypt_credential("YXJiaXRyYXJ5IGJhc2U2NCBzdHJpbmc=") == ""


class TestCredentialMasking:
    """Test mask_credential function."""

    def test_mask_empty_string(self):
        """Empty string should return empty string."""
        assert mask_credential("") == ""
        assert mask_credential(None) == ""

    def test_mask_short_string(self):
        """Strings shorter than 4 chars should be fully masked."""
        assert mask_credential("abc") == "****"
        assert mask_credential("1") == "****"

    def test_mask_exactly_4_chars(self):
        """Strings of exactly 4 chars should be fully masked."""
        assert mask_credential("1234") == "****"

    def test_mask_long_string(self):
        """Longer strings should show last 4 characters."""
        assert mask_credential("secret123") == "****t123"
        assert mask_credential("password") == "****word"
        assert mask_credential("longer_secret_value") == "****alue"


class TestEnvCredentials:
    """Test get_env_credentials function."""

    @patch.dict(
        os.environ,
        {
            "LOGIN_USERNAME": "testuser",
            "LOGIN_PASSWORD": "testpassword",
            "CUSTOM_API_KEY": "sk-12345",
            "DB_PASSWORD": "dbpass",
            "ANTHROPIC_AUTH_TOKEN": "internal-token",
            "JWT_SECRET_KEY": "internal-secret",
            "OPENAI_API_KEY": "internal-key",
            "NOT_A_CRED": "some-value",
        },
        clear=True,
    )
    def test_get_env_credentials(self):
        """Should pick up credential patterns and skip internal keys."""
        # We need to make sure JWT_SECRET_KEY is present if the module needs it,
        # but the function get_env_credentials specifically skips it.
        # Actually, credentials.py imports JWT_SECRET_KEY at module level.

        creds = get_env_credentials()

        # Should include these
        assert creds["LOGIN_USERNAME"] == "testuser"
        assert creds["LOGIN_PASSWORD"] == "testpassword"
        assert creds["CUSTOM_API_KEY"] == "sk-12345"
        assert creds["DB_PASSWORD"] == "dbpass"

        # Should NOT include these
        assert "ANTHROPIC_AUTH_TOKEN" not in creds
        assert "JWT_SECRET_KEY" not in creds
        assert "OPENAI_API_KEY" not in creds
        assert "NOT_A_CRED" not in creds
