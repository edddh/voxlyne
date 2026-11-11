"""
Voxlyne - Credentials Manager

Centralized service for managing encrypted credentials for all external services.
Supports project-level and tenant-level credentials with fallback to global .env settings.
"""

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
        db_creds = await self._fetch_db_credentials(
            entity_type, entity_id, service_type, provider, credential_key
        )
        if db_creds:
            return db_creds

        # Fallback to global .env settings
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

    async def get_credentials_with_fallback(
        self,
        tenant_id: UUID,
        project_id: Optional[UUID],
        service_type: str,
        provider: str,
        credential_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """
        Resolve credentials with project → tenant → .env fallback.

        This is the resolution order needed for tenant-configurable LLM/voice
        provider keys: a project can override its tenant's default, a tenant
        can set a default for all its projects, and .env remains the final
        global fallback (same as get_credentials).

        Args:
            tenant_id: UUID of the owning tenant (always required)
            project_id: UUID of the project, if resolving for a specific
                project; pass None to resolve tenant-level only
            service_type: 'crm', 'voice', 'telephony', 'tts', 'calendar'
            provider: Provider name (vapi, xai, livekit, zadarma, etc.)
            credential_key: Optional reference key for multiple credentials

        Returns:
            Dict[str, str]: Credential key-value pairs (empty dict if not found)
        """
        if project_id is not None:
            project_creds = await self._fetch_db_credentials(
                "project", project_id, service_type, provider, credential_key
            )
            if project_creds:
                return project_creds

        tenant_creds = await self._fetch_db_credentials(
            "tenant", tenant_id, service_type, provider, credential_key
        )
        if tenant_creds:
            return tenant_creds

        env_creds = self._get_env_fallback(service_type, provider)
        if env_creds:
            logger.debug(
                f"Using global .env fallback for {service_type}/{provider} "
                f"(no project/tenant-level credentials found for tenant {tenant_id}"
                f"{f', project {project_id}' if project_id else ''})"
            )
            return env_creds

        logger.warning(
            f"No credentials found for {service_type}/{provider} "
            f"(tenant={tenant_id}, project={project_id})"
        )
        return {}

    async def _fetch_db_credentials(
        self,
        entity_type: str,
        entity_id: UUID,
        service_type: str,
        provider: str,
        credential_key: Optional[str] = None,
    ) -> Dict[str, str]:
        """DB-only lookup (no .env fallback). Returns {} if not found."""
        db = get_database()

        try:
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
                await db.execute(
                    """UPDATE service_credentials
                       SET last_used_at = :now
                       WHERE id = :id""",
                    {"now": datetime.now(timezone.utc), "id": result["id"]},
                )

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
            if provider in ("openai_realtime", "openai") and self.settings.openai_api_key:
                return {"api_key": self.settings.openai_api_key}
            if provider == "xai" and self.settings.xai_api_key:
                return {"api_key": self.settings.xai_api_key}

        # Telephony providers
        elif service_type == "telephony":
            if provider == "twilio":
                if self.settings.twilio_account_sid and self.settings.twilio_auth_token:
                    return {
                        "account_sid": self.settings.twilio_account_sid,
                        "auth_token": self.settings.twilio_auth_token,
                    }
            if provider == "livekit":
                if self.settings.livekit_url and self.settings.livekit_api_key and self.settings.livekit_api_secret:
                    return {
                        "url": self.settings.livekit_url,
                        "api_key": self.settings.livekit_api_key,
                        "api_secret": self.settings.livekit_api_secret,
                    }
            if provider == "zadarma":
                if self.settings.zadarma_sip_login and self.settings.zadarma_sip_password:
                    creds = {
                        "sip_login": self.settings.zadarma_sip_login,
                        "sip_password": self.settings.zadarma_sip_password,
                    }
                    if self.settings.zadarma_number:
                        creds["number"] = self.settings.zadarma_number
                    return creds

        # TTS providers
        elif service_type == "tts":
            if provider == "elevenlabs" and self.settings.elevenlabs_api_key:
                return {"api_key": self.settings.elevenlabs_api_key}
            if provider == "elevenlabs_agent" and self.settings.elevenlabs_api_key:
                creds = {"api_key": self.settings.elevenlabs_api_key}
                if self.settings.elevenlabs_tool_secret:
                    creds["tool_secret"] = self.settings.elevenlabs_tool_secret
                return creds

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

            elif provider == "calcom" and self.settings.calcom_api_key:
                return {"api_key": self.settings.calcom_api_key}

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
              AND is_active = TRUE
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

            elif service_type == "voice" and provider in ("openai_realtime", "openai"):
                import httpx

                api_key = credentials.get("api_key")
                if not api_key:
                    return {"success": False, "message": "Missing api_key"}

                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://api.openai.com/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    if response.status_code == 200:
                        return {"success": True, "message": "Connection successful"}
                    return {
                        "success": False,
                        "message": f"Connection failed ({response.status_code})",
                        "error": response.text[:300],
                    }

            elif service_type == "voice" and provider == "xai":
                import httpx

                api_key = credentials.get("api_key")
                if not api_key:
                    return {"success": False, "message": "Missing api_key"}

                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://api.x.ai/v1/models",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    if response.status_code == 200:
                        return {"success": True, "message": "Connection successful"}
                    return {
                        "success": False,
                        "message": f"Connection failed ({response.status_code})",
                        "error": response.text[:300],
                    }

            # Telephony providers
            elif service_type == "telephony" and provider == "twilio":
                from app.services.telephony.twilio_client import TwilioClient

                account_sid = credentials.get("account_sid")
                auth_token = credentials.get("auth_token")
                if not account_sid or not auth_token:
                    return {"success": False, "message": "Missing account_sid or auth_token"}

                client = TwilioClient(account_sid=account_sid, auth_token=auth_token)
                is_valid = await client.test_connection()
                return {
                    "success": is_valid,
                    "message": "Connection successful" if is_valid else "Connection failed",
                }

            elif service_type == "telephony" and provider == "livekit":
                # Full API validation (room listing) requires the livekit-server-sdk,
                # which lives in requirements-voice.txt and isn't merged into the main
                # app environment yet (see that file for why). Structural check only
                # until the voice-worker service (with the SDK installed) takes this over.
                url = credentials.get("url")
                api_key = credentials.get("api_key")
                api_secret = credentials.get("api_secret")
                missing = [
                    name for name, val in (("url", url), ("api_key", api_key), ("api_secret", api_secret))
                    if not val
                ]
                if missing:
                    return {"success": False, "message": f"Missing {', '.join(missing)}"}
                if not (url.startswith("wss://") or url.startswith("ws://")):
                    return {"success": False, "message": "url must start with wss:// or ws://"}
                return {
                    "success": True,
                    "message": "Fields present (full LiveKit API check pending voice-worker integration)",
                }

            elif service_type == "telephony" and provider == "zadarma":
                # Zadarma's REST API needs HMAC-signed requests; deferred to the
                # concrete telephony provider implementation. Structural check only.
                sip_login = credentials.get("sip_login")
                sip_password = credentials.get("sip_password")
                missing = [
                    name for name, val in (("sip_login", sip_login), ("sip_password", sip_password))
                    if not val
                ]
                if missing:
                    return {"success": False, "message": f"Missing {', '.join(missing)}"}
                return {
                    "success": True,
                    "message": "Fields present (full Zadarma API check pending telephony provider implementation)",
                }

            # TTS providers
            elif service_type == "tts" and provider in ("elevenlabs", "elevenlabs_agent"):
                import httpx

                api_key = credentials.get("api_key")
                if not api_key:
                    return {"success": False, "message": "Missing api_key"}

                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://api.elevenlabs.io/v1/voices",
                        headers={"xi-api-key": api_key},
                    )
                    if response.status_code == 200:
                        return {"success": True, "message": "Connection successful"}
                    return {
                        "success": False,
                        "message": f"Connection failed ({response.status_code})",
                        "error": response.text[:300],
                    }

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
                from app.services.crm.providers.webhook import GenericWebhookProvider

                url = credentials.get("url")
                if not url:
                    return {
                        "success": False,
                        "message": "Missing url",
                        "error": "Provide webhook URL in credentials data as 'url'",
                    }

                provider_instance = GenericWebhookProvider(
                    url=url,
                    secret=credentials.get("secret"),
                )
                is_valid = await provider_instance.test_connection()
                return {
                    "success": is_valid,
                    "message": "Connection successful" if is_valid else "Connection failed",
                }

            elif service_type == "calendar" and provider == "google_calendar":
                from app.services.calendar.providers.google import GoogleCalendarProvider

                access_token = credentials.get("access_token")
                if not access_token:
                    return {"success": False, "message": "Missing access_token"}

                provider_instance = GoogleCalendarProvider(
                    access_token=access_token,
                    refresh_token=credentials.get("refresh_token"),
                    client_id=credentials.get("client_id"),
                    client_secret=credentials.get("client_secret"),
                )
                is_valid = await provider_instance.test_connection()
                return {
                    "success": is_valid,
                    "message": "Connection successful" if is_valid else "Connection failed",
                }

            elif service_type == "calendar" and provider == "ms_graph":
                from app.services.calendar.providers.microsoft import MicrosoftCalendarProvider

                access_token = credentials.get("access_token")
                if not access_token:
                    return {"success": False, "message": "Missing access_token"}

                provider_instance = MicrosoftCalendarProvider(
                    access_token=access_token,
                    refresh_token=credentials.get("refresh_token"),
                    client_id=credentials.get("client_id"),
                    client_secret=credentials.get("client_secret"),
                    tenant_id=credentials.get("tenant_id"),
                )
                is_valid = await provider_instance.test_connection()
                return {
                    "success": is_valid,
                    "message": "Connection successful" if is_valid else "Connection failed",
                }

            elif service_type == "calendar" and provider == "calcom":
                import httpx

                api_key = credentials.get("api_key")
                if not api_key:
                    return {"success": False, "message": "Missing api_key"}

                async with httpx.AsyncClient(timeout=10.0) as client:
                    response = await client.get(
                        "https://api.cal.com/v2/me",
                        headers={"Authorization": f"Bearer {api_key}"},
                    )
                    if response.status_code == 200:
                        return {"success": True, "message": "Connection successful"}
                    return {
                        "success": False,
                        "message": f"Connection failed ({response.status_code})",
                        "error": response.text[:300],
                    }

            else:
                return {
                    "success": False,
                    "message": f"Unknown provider: {service_type}/{provider}",
                }

        except Exception as e:
            logger.error(f"Test connection failed for {service_type}/{provider}: {e}")
            return {"success": False, "message": "Connection test failed", "error": str(e)}
