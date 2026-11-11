"""
Voxlyne - Encryption Utility

Provides Fernet symmetric encryption for credentials storage.
Uses SECRET_KEY from config to derive encryption key.
"""

import base64
import hashlib
import json
import logging
from typing import Dict

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_encryption_key() -> bytes:
    """
    Derive Fernet encryption key from SECRET_KEY.

    Fernet requires a 32-byte url-safe base64-encoded key.
    We derive it from the application's SECRET_KEY using SHA256.

    Returns:
        bytes: URL-safe base64-encoded 32-byte key for Fernet

    Raises:
        ValueError: If SECRET_KEY is not configured
    """
    from app.config import get_settings

    settings = get_settings()

    if not settings.secret_key:
        raise ValueError("SECRET_KEY must be configured in .env for encryption")

    # Hash SECRET_KEY to get consistent 32 bytes
    key_material = hashlib.sha256(settings.secret_key.encode()).digest()

    # Fernet requires url-safe base64 encoding
    return base64.urlsafe_b64encode(key_material)


def encrypt_credentials(data: Dict[str, str]) -> str:
    """
    Encrypt credential dictionary to Fernet token.

    Args:
        data: Dictionary of credential key-value pairs
              Example: {"api_key": "sk-123", "secret": "abc"}

    Returns:
        str: Base64-encoded Fernet token (safe to store in DB)

    Raises:
        ValueError: If SECRET_KEY is not configured
        Exception: If encryption fails

    Example:
        >>> creds = {"api_key": "sk-test-123"}
        >>> token = encrypt_credentials(creds)
        >>> # Store token in database...
    """
    try:
        fernet = Fernet(_get_encryption_key())
        json_data = json.dumps(data, sort_keys=True)  # Consistent JSON serialization
        encrypted_bytes = fernet.encrypt(json_data.encode("utf-8"))
        return encrypted_bytes.decode("utf-8")
    except Exception as e:
        logger.error(f"Failed to encrypt credentials: {e}")
        raise


def decrypt_credentials(encrypted_token: str) -> Dict[str, str]:
    """
    Decrypt Fernet token to credential dictionary.

    Args:
        encrypted_token: Base64-encoded Fernet token from database

    Returns:
        Dict[str, str]: Decrypted credential key-value pairs

    Raises:
        ValueError: If SECRET_KEY is not configured or token is invalid
        InvalidToken: If token is corrupted or was encrypted with different key

    Example:
        >>> token = "gAAAAABf..."  # From database
        >>> creds = decrypt_credentials(token)
        >>> print(creds["api_key"])
        sk-test-123
    """
    try:
        fernet = Fernet(_get_encryption_key())
        decrypted_bytes = fernet.decrypt(encrypted_token.encode("utf-8"))
        return json.loads(decrypted_bytes.decode("utf-8"))
    except InvalidToken:
        logger.error("Failed to decrypt credentials: Invalid token or wrong encryption key")
        raise ValueError("Failed to decrypt credentials - invalid token or encryption key changed")
    except Exception as e:
        logger.error(f"Failed to decrypt credentials: {e}")
        raise


def test_encryption() -> bool:
    """
    Test encryption/decryption roundtrip.

    Returns:
        bool: True if encryption is working correctly

    Example:
        >>> if test_encryption():
        ...     print("Encryption is configured correctly")
    """
    try:
        test_data = {"test_key": "test_value", "number": "12345"}
        encrypted = encrypt_credentials(test_data)
        decrypted = decrypt_credentials(encrypted)

        if decrypted == test_data:
            logger.info("Encryption test passed")
            return True
        else:
            logger.error("Encryption test failed: data mismatch")
            return False

    except Exception as e:
        logger.error(f"Encryption test failed: {e}")
        return False
