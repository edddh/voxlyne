"""
Ascolta - Credentials Manager

Centralized service for managing encrypted credentials for all external services.
Supports project-level and tenant-level credentials with fallback to global .env settings.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.config import get_settings
from app.database.db import get_database
from app.utils.encryption import decrypt_credentials, encrypt_credentials

logger = logging.getLogger(__name__)


class CredentialsManager:
    """
    Manages encrypted credentials for external services.

    Responsibilities:
    - Store/retrieve encrypted credentials per project/tenant
    - Fallback to global .env settings if no entity-level credentials
    - Test credential validity
    - Track usage statistics
    """

    def __init__(self):
        self.settings = get_settings()

    async def get_credentials(
        self,
        entity_type: str,
        entity_id: UUID,
        service_type: str,
        provider: str,
        credential_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Get credentials from DB (decrypted) with fallback to .env.

        Priority:
        1. Database (entity-level, encrypted)
        2. Environment variables (global fallback)

        Args:
            entity_type: 'project' or 'tenant'
            entity_id: UUID of project/tenant
            service_type: 'crm', 'voice', 'telephony', 'tts', 'calendar'
            provider: Provider name (vapi, twilio, elevenlabs, hubspot, etc.)
            credential_key: Optional reference key for multiple credentials

        Returns:
            Dict[str, str]: Credential key-value pairs (empty dict if not found)

        Example:
            >>> creds = await manager.get_credentials(
            ...     entity_type="project",
            ...     entity_id=project_id,
            ...     service_type="voice",
            ...     provider="vapi"
            ... )
            >>> vapi_key = creds.get("api_key")
        """
        db = get_database()

        try:
            # 1. Try database credentials
            query = """
                SELECT encrypted_data, id
                FROM service_credentials
                WHERE entity_type = :entity_type
                  AND entity_id = :entity_id
                  AND service_type = :service_type
                  AND provider = :provider
                  AND is_active = TRUE
            """
            params: Dict[str, Any] = {
                "entity_type": entity_type,
                "entity_id": str(entity_id),
                "service_type": service_type,
                "provider": provider,
            }

            if credential_key:
                query += " AND credential_key = :credential_key"
                params["credential_key"] = credential_key

            query += " LIMIT 1"

            result = await db.fetch_one(query, params)

            if result:
                # Update last_used_at
                await db.execute(
                    """UPDATE service_credentials
                       SET last_used_at = :now
                       WHERE id = :id""",
                    {"now": datetime.now(timezone.utc), "id": result["id"]},
                )

                # Decrypt and return
                credentials = decrypt_credentials(result["encrypted_data"])
                logger.debug(
                    f"Loaded {service_type}/{provider} credentials from DB "
                    f"for {entity_type} {entity_id}"
                )
                return credentials

        except Exception as e:
            logger.error(
                f"Failed to load credentials from DB for {service_type}/{provider}: {e}"
            )
            # Continue to fallback

        # 2. Fallback to global .env settings
        env_creds = self._get_env_fallback(service_type, provider)
        if env_creds:
            logger.debug(
                f"Using global .env fallback for {service_type}/{provider} "
                f"(no {entity_type}-level credentials found)"
            )
            return env_creds

        logger.warning(
            f"No credentials found for {service_type}/{provider} "
            f"(entity_type={entity_type}, entity_id={entity_id})"
        )
        return {}

    def _get_env_fallback(self, service_type: str, provider: str) -> Dict[str, str]:
        """
        Get credentials from global environment variables.

        Args:
            service_type: Service category
            provider: Provider name

        Returns:
            Dict[str, str]: Credentials from .env or empty dict
        """
        # Voice providers
        if service_type == "voice":
            if provider == "vapi" and self.settings.vapi_api_key:
                return {"api_key": self.settings.vapi_api_key}

        # Telephony providers
        elif service_type == "telephony":
            if provider == "twilio":
                if self.settings.twilio_account_sid and self.settings.twilio_auth_token:
                    return {
                        "account_sid": self.settings.twilio_account_sid,
                        "auth_token": self.settings.twilio_auth_token,
                    }

        # TTS providers
        elif service_type == "tts":
            if provider == "elevenlabs" and self.settings.elevenlabs_api_key:
                return {"api_key": self.settings.elevenlabs_api_key}

        # CRM providers
        elif service_type == "crm":
            if provider == "hubspot":
                if self.settings.hubspot_access_token:
                    return {"access_token": self.settings.hubspot_access_token}
                elif self.settings.hubspot_api_key:
                    return {"api_key": self.settings.hubspot_api_key}

            elif provider == "generic_webhook":
                if self.settings.webhook_secret:
                    return {"secret": self.settings.webhook_secret}
                # Webhook can work without secret
                return {}

        # Calendar providers
        elif service_type == "calendar":
            if provider == "google_calendar":
                creds = {}
                if self.settings.google_calendar_client_id:
                    creds["client_id"] = self.settings.google_calendar_client_id
                if self.settings.google_calendar_client_secret:
                    creds["client_secret"] = self.settings.google_calendar_client_secret
                if self.settings.google_calendar_access_token:
                    creds["access_token"] = self.settings.google_calendar_access_token
                if self.settings.google_calendar_refresh_token:
                    creds["refresh_token"] = self.settings.google_calendar_refresh_token
                return creds if creds else {}

            elif provider == "ms_graph":
                creds = {}
                if self.settings.ms_graph_client_id:
                    creds["client_id"] = self.settings.ms_graph_client_id
                if self.settings.ms_graph_client_secret:
                    creds["client_secret"] = self.settings.ms_graph_client_secret
                if self.settings.ms_graph_tenant_id:
                    creds["tenant_id"] = self.settings.ms_graph_tenant_id
                return creds if creds else {}

        return {}

    async def set_credentials(
        self,
        entity_type: str,
        entity_id: UUID,
        service_type: str,
        provider: str,
        data: Dict[str, str],
        credential_key: Optional[str] = None,
        expires_at: Optional[datetime] = None,
    ) -> int:
        """
        Set/update credentials (encrypts before storing).

        Args:
            entity_type: 'project' or 'tenant'
            entity_id: UUID of project/tenant
            service_type: Service category
            provider: Provider name
            data: Credential key-value pairs to encrypt
            credential_key: Reference key (default: 'default')
            expires_at: Optional expiration (for OAuth tokens)

        Returns:
            int: Credential ID

        Example:
            >>> cred_id = await manager.set_credentials(
            ...     entity_type="project",
            ...     entity_id=project_id,
            ...     service_type="voice",
            ...     provider="vapi",
            ...     data={"api_key": "sk-..."}
            ... )
        """
        db = get_database()

        if not credential_key:
            credential_key = "default"

        try:
            # Encrypt credentials
            encrypted_data = encrypt_credentials(data)

            # Upsert (insert or update on conflict)
            result = await db.fetch_one(
                """
                INSERT INTO service_credentials (
                    entity_type, entity_id, service_type, provider, credential_key,
                    encrypted_data, expires_at, is_active, created_at, updated_at
                )
                VALUES (
                    :entity_type, :entity_id, :service_type, :provider, :credential_key,
                    :encrypted_data, :expires_at, TRUE, :now, :now
                )
                ON CONFLICT (entity_type, entity_id, service_type, provider, credential_key)
                DO UPDATE SET
                    encrypted_data = EXCLUDED.encrypted_data,
                    expires_at = EXCLUDED.expires_at,
                    is_active = TRUE,
                    updated_at = EXCLUDED.updated_at
                RETURNING id
                """,
                {
                    "entity_type": entity_type,
                    "entity_id": str(entity_id),
                    "service_type": service_type,
                    "provider": provider,
                    "credential_key": credential_key,
                    "encrypted_data": encrypted_data,
                    "expires_at": expires_at,
                    "now": datetime.now(timezone.utc),
                },
            )

            credential_id = result["id"]
            logger.info(
                f"Saved {service_type}/{provider} credentials for "
                f"{entity_type} {entity_id} (id={credential_id})"
            )
            return credential_id

        except Exception as e:
            logger.error(f"Failed to save credentials: {e}", exc_info=True)
            raise

    async def delete_credentials(self, credential_id: int, hard_delete: bool = False) -> bool:
        """
        Delete credentials (soft-delete by default).

        Args:
            credential_id: ID of credential to delete
            hard_delete: If True, permanently delete; if False, set is_active=False

        Returns:
            bool: True if deleted successfully
        """
        db = get_database()

        try:
            if hard_delete:
                result = await db.execute(
                    "DELETE FROM service_credentials WHERE id = :id",
                    {"id": credential_id},
                )
            else:
                result = await db.execute(
                    """UPDATE service_credentials
                       SET is_active = FALSE, updated_at = :now
                       WHERE id = :id""",
                    {"id": credential_id, "now": datetime.now(timezone.utc)},
                )

            logger.info(
                f"{'Hard-deleted' if hard_delete else 'Soft-deleted'} credential {credential_id}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to delete credential {credential_id}: {e}")
            return False

    async def list_credentials(
        self,
        entity_type: str,
        entity_id: UUID,
        service_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List credentials metadata (NO decrypted values).

        Args:
            entity_type: 'project' or 'tenant'
            entity_id: UUID of project/tenant
            service_type: Optional filter by service type

        Returns:
            List of credential metadata dicts (id, service_type, provider, credential_key, is_active, created_at)

        Example:
            >>> creds = await manager.list_credentials("project", project_id, "voice")
            >>> for cred in creds:
            ...     print(f"{cred['provider']}: {cred['is_active']}")
        """
        db = get_database()

        query = """
            SELECT id, service_type, provider, credential_key,
                   is_active, last_used_at, expires_at, created_at
            FROM service_credentials
            WHERE entity_type = :entity_type
              AND entity_id = :entity_id
        """
        params: Dict[str, Any] = {
            "entity_type": entity_type,
            "entity_id": str(entity_id),
        }

        if service_type:
            query += " AND service_type = :service_type"
            params["service_type"] = service_type

        query += " ORDER BY created_at DESC"

        results = await db.fetch_all(query, params)

        return [dict(row) for row in results]

    async def test_connection(
        self,
        service_type: str,
        provider: str,
        credentials: Dict[str, str],
    ) -> Dict[str, Any]:
        """
        Test credentials validity by calling provider API.

        Args:
            service_type: Service category
            provider: Provider name
            credentials: Credential dict to test

        Returns:
            Dict with 'success' (bool), 'message' (str), optional 'error'

        Example:
            >>> result = await manager.test_connection(
            ...     "voice", "vapi", {"api_key": "sk-..."}
            ... )
            >>> if result["success"]:
            ...     print("Credentials valid!")
        """
        try:
            # Voice providers
            if service_type == "voice" and provider == "vapi":
                from app.services.voice.vapi_client import VapiClient

                api_key = credentials.get("api_key")
                if not api_key:
                    return {"success": False, "message": "Missing api_key"}

                client = VapiClient(api_key=api_key)
                is_valid = await client.test_connection()
                return {
                    "success": is_valid,
                    "message": "Connection successful" if is_valid else "Connection failed",
                }

            # Telephony providers
            elif service_type == "telephony" and provider == "twilio":
                # TODO: Implement Twilio test connection
                # For now, just validate that credentials are present
                if credentials.get("account_sid") and credentials.get("auth_token"):
                    return {"success": True, "message": "Credentials present (test not implemented)"}
                else:
                    return {"success": False, "message": "Missing account_sid or auth_token"}

            # TTS providers
            elif service_type == "tts" and provider == "elevenlabs":
                # TODO: Implement ElevenLabs test connection
                if credentials.get("api_key"):
                    return {"success": True, "message": "Credentials present (test not implemented)"}
                else:
                    return {"success": False, "message": "Missing api_key"}

            # CRM providers
            elif service_type == "crm" and provider == "hubspot":
                from app.services.crm.providers.hubspot import HubSpotProvider

                provider_instance = HubSpotProvider(
                    api_key=credentials.get("api_key"),
                    access_token=credentials.get("access_token"),
                )
                is_valid = await provider_instance.test_connection()
                return {
                    "success": is_valid,
                    "message": "Connection successful" if is_valid else "Connection failed",
                }

            elif service_type == "crm" and provider == "generic_webhook":
                # Webhook doesn't need test - just check URL format
                return {"success": True, "message": "Webhook provider configured"}

            # Calendar providers - stub for now
            elif service_type == "calendar":
                return {"success": True, "message": f"{provider} test not implemented yet"}

            else:
                return {
                    "success": False,
                    "message": f"Unknown provider: {service_type}/{provider}",
                }

        except Exception as e:
            logger.error(f"Test connection failed for {service_type}/{provider}: {e}")
            return {"success": False, "message": "Connection test failed", "error": str(e)}
