"""
Encryption Service - Symmetric encryption for sensitive data

Uses Fernet (symmetric encryption) from cryptography library.
Encrypts/decrypts:
- SIP passwords
- CRM API keys (HubSpot, Salesforce)
- Calendar OAuth tokens (Google, Microsoft)
- Webhook secrets

Key Management:
- Encryption key loaded from environment variable ENCRYPTION_KEY
- If not set, uses SECRET_KEY as fallback
- Key must be 32 url-safe base64-encoded bytes
- Generate with: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""

import logging
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from app.config import get_settings

logger = logging.getLogger(__name__)


class EncryptionService:
    """Handles encryption/decryption of sensitive data"""

    def __init__(self):
        """Initialize encryption service with key from settings"""
        # Try encryption_key first, fallback to secret_key
        settings = get_settings()
        encryption_key = settings.encryption_key or settings.secret_key

        # Ensure key is bytes
        if isinstance(encryption_key, str):
            encryption_key = encryption_key.encode()

        # Validate key length and format
        try:
            self.cipher = Fernet(encryption_key)
            logger.info("Encryption service initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize encryption service: {e}")
            raise ValueError(
                "Invalid encryption key. Generate with: "
                "python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            )

    def encrypt(self, plaintext: Optional[str]) -> Optional[str]:
        """
        Encrypt plaintext string

        Args:
            plaintext: String to encrypt (e.g., API key, password)

        Returns:
            Encrypted string (base64-encoded), or None if input is None

        Example:
            >>> enc = EncryptionService()
            >>> encrypted = enc.encrypt("my-secret-api-key")
            >>> print(encrypted)
            'gAAAAABhxxx...'
        """
        if plaintext is None:
            return None

        if not plaintext:  # Empty string
            return ""

        try:
            # Convert to bytes and encrypt
            encrypted_bytes = self.cipher.encrypt(plaintext.encode())
            # Return as base64 string for DB storage
            return encrypted_bytes.decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            raise RuntimeError(f"Failed to encrypt data: {e}")

    def decrypt(self, encrypted: Optional[str]) -> Optional[str]:
        """
        Decrypt encrypted string

        Args:
            encrypted: Encrypted string (base64-encoded)

        Returns:
            Decrypted plaintext string, or None if input is None

        Raises:
            RuntimeError: If decryption fails (invalid key, corrupted data)

        Example:
            >>> enc = EncryptionService()
            >>> plaintext = enc.decrypt("gAAAAABhxxx...")
            >>> print(plaintext)
            'my-secret-api-key'
        """
        if encrypted is None:
            return None

        if not encrypted:  # Empty string
            return ""

        try:
            # Decrypt from base64 string
            decrypted_bytes = self.cipher.decrypt(encrypted.encode())
            # Return as plaintext string
            return decrypted_bytes.decode()
        except InvalidToken:
            logger.error("Decryption failed: Invalid token (wrong key or corrupted data)")
            raise RuntimeError(
                "Failed to decrypt data. The encryption key may have changed, "
                "or the data is corrupted."
            )
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            raise RuntimeError(f"Failed to decrypt data: {e}")

    def encrypt_dict(self, data: dict, fields: list[str]) -> dict:
        """
        Encrypt specific fields in a dictionary

        Args:
            data: Dictionary containing sensitive fields
            fields: List of field names to encrypt

        Returns:
            New dictionary with encrypted fields (original field names + '_encrypted')

        Example:
            >>> enc = EncryptionService()
            >>> data = {"api_key": "secret123", "portal_id": "12345"}
            >>> encrypted = enc.encrypt_dict(data, ["api_key"])
            >>> print(encrypted)
            {'api_key_encrypted': 'gAAAAABhxxx...', 'portal_id': '12345'}
        """
        result = data.copy()
        for field in fields:
            if field in result:
                plaintext = result.pop(field)
                result[f"{field}_encrypted"] = self.encrypt(plaintext)
        return result

    def decrypt_dict(self, data: dict, fields: list[str]) -> dict:
        """
        Decrypt specific fields in a dictionary

        Args:
            data: Dictionary containing encrypted fields (with '_encrypted' suffix)
            fields: List of original field names (without '_encrypted')

        Returns:
            New dictionary with decrypted fields (original field names)

        Example:
            >>> enc = EncryptionService()
            >>> data = {"api_key_encrypted": "gAAAAABhxxx...", "portal_id": "12345"}
            >>> decrypted = enc.decrypt_dict(data, ["api_key"])
            >>> print(decrypted)
            {'api_key': 'secret123', 'portal_id': '12345'}
        """
        result = data.copy()
        for field in fields:
            encrypted_field = f"{field}_encrypted"
            if encrypted_field in result:
                encrypted = result.pop(encrypted_field)
                result[field] = self.decrypt(encrypted)
        return result


# Global instance (singleton pattern)
_encryption_service: Optional[EncryptionService] = None


def get_encryption_service() -> EncryptionService:
    """
    Get global encryption service instance (singleton)

    Returns:
        EncryptionService instance

    Example:
        >>> from app.services.encryption import get_encryption_service
        >>> enc = get_encryption_service()
        >>> encrypted = enc.encrypt("my-secret")
    """
    global _encryption_service
    if _encryption_service is None:
        _encryption_service = EncryptionService()
    return _encryption_service


# Convenience functions for common use cases
def encrypt(plaintext: Optional[str]) -> Optional[str]:
    """Encrypt plaintext (convenience wrapper)"""
    return get_encryption_service().encrypt(plaintext)


def decrypt(encrypted: Optional[str]) -> Optional[str]:
    """Decrypt encrypted text (convenience wrapper)"""
    return get_encryption_service().decrypt(encrypted)
