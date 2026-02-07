"""
Ascolta - Credentials Management
Centralized service for managing encrypted credentials for all external services
"""

from app.services.credentials.manager import CredentialsManager

__all__ = ["CredentialsManager"]
