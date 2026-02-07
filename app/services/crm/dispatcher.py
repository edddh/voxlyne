"""
Ascolta - CRM Dispatcher

Orchestrates CRM synchronization for completed interviews.
Handles provider selection, data mapping, retry logic, and status tracking.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from app.config import get_settings
from app.database.db import get_database
from app.services.crm.base import (
    BaseCRMProvider,
    CRMConfig,
    CRMOperation,
    CRMSyncResult,
    CRMSyncStatus,
)
from app.services.crm.mapper import DataMapper
from app.services.crm.providers.hubspot import HubSpotProvider
from app.services.crm.providers.webhook import GenericWebhookProvider
from app.services.crm.retry import RetryConfig, RetryManager

logger = logging.getLogger(__name__)


class CRMDispatcher:
    """
    Orchestrates CRM synchronization for completed interviews.

    Responsibilities:
    - Fetch CRM configuration from project
    - Select appropriate provider
    - Map data to CRM format
    - Execute with retry logic
    - Track sync status in database
    """

    def __init__(self):
        self.mapper = DataMapper()
        self.settings = get_settings()

    def _get_retry_manager(self) -> RetryManager:
        """Create retry manager with settings from config."""
        config = RetryConfig(
            max_attempts=self.settings.crm_retry_max_attempts,
            initial_delay=self.settings.crm_retry_initial_delay,
        )
        return RetryManager(config)

    def _get_provider(
        self,
        provider_name: str,
        config: Dict[str, Any],
        credentials: Dict[str, str],
    ) -> BaseCRMProvider:
        """
        Get or create provider instance.

        Args:
            provider_name: Provider type (hubspot, generic_webhook)
            config: Provider-specific configuration
            credentials: API keys/tokens

        Returns:
            Configured provider instance
        """
        if provider_name == "hubspot":
            return HubSpotProvider(
                api_key=credentials.get("api_key"),
                access_token=credentials.get("access_token"),
            )

        elif provider_name == "generic_webhook":
            # Get webhook URL from config
            webhook_url = config.get("url")
            if not webhook_url:
                raise ValueError("Webhook URL not configured")

            return GenericWebhookProvider(
                url=webhook_url,
                secret=credentials.get("secret"),
                headers=config.get("headers"),
                method=config.get("method", "POST"),
            )

        else:
            raise ValueError(f"Unknown CRM provider: {provider_name}")

    async def dispatch(
        self,
        call_id: UUID,
        json_data: Dict[str, Any],
        call_metadata: Dict[str, Any],
    ) -> bool:
        """
        Dispatch candidate data to configured CRM.

        Called from CallManager._post_process_interview() after PDF/email.

        Args:
            call_id: UUID of the call
            json_data: Extracted candidate JSON from GPT-4
            call_metadata: Call info (id, started_at, duration_seconds, phone_number)

        Returns:
            True if sync was successful
        """
        db = get_database()

        try:
            # 1. Check if CRM sync is globally enabled
            if not self.settings.crm_sync_enabled:
                logger.debug(f"CRM sync disabled globally, skipping call {call_id}")
                return True

            # 2. Fetch project CRM config
            crm_config = await self._get_crm_config(call_id)
            if not crm_config or not crm_config.enabled:
                logger.debug(f"CRM sync disabled for project, skipping call {call_id}")
                return True

            provider_name = crm_config.provider

            # 3. Get credentials via CredentialsManager
            from app.services.credentials.manager import CredentialsManager

            # Get project_id for this call
            call_project = await db.fetch_one(
                "SELECT project_id FROM calls WHERE id = :call_id",
                {"call_id": str(call_id)},
            )

            if not call_project or not call_project["project_id"]:
                logger.error(f"No project_id found for call {call_id}")
                return False

            creds_manager = CredentialsManager()
            credentials = await creds_manager.get_credentials(
                entity_type="project",
                entity_id=call_project["project_id"],
                service_type="crm",
                provider=provider_name,
            )

            if not credentials and provider_name != "generic_webhook":
                logger.warning(
                    f"No CRM credentials found for {provider_name}, skipping call {call_id}"
                )
                return False

            # 4. Initialize provider
            try:
                provider = self._get_provider(
                    provider_name,
                    crm_config.config,
                    credentials,
                )
            except ValueError as e:
                logger.error(f"Failed to initialize CRM provider: {e}")
                return False

            # 5. Map data to CRM format
            mapped_data = self.mapper.map_to_crm(
                json_data=json_data,
                call_metadata=call_metadata,
                field_mapping=crm_config.field_mapping,
                provider=provider_name,
            )

            logger.debug(f"Mapped {len(mapped_data)} fields for CRM sync")

            # 6. Get record ID (for linking sync log)
            record = await db.fetch_one(
                "SELECT id FROM records WHERE call_id = :call_id",
                {"call_id": str(call_id)},
            )
            record_id = record["id"] if record else None

            # 7. Create sync log entry
            log_id = await self._create_sync_log(
                call_id=call_id,
                record_id=record_id,
                provider=provider_name,
                operation=CRMOperation.CREATE_CONTACT.value,
                request_payload={"fields": list(mapped_data.keys())},
            )

            # 8. Execute with retry
            retry_manager = self._get_retry_manager()
            result = await retry_manager.execute_with_retry(
                func=provider.create_contact,
                args=(mapped_data, crm_config.config),
                log_id=log_id,
            )

            # 9. Update sync status
            await retry_manager.update_final_status(log_id, result)
            await self._update_record_crm_status(
                call_id=call_id,
                result=result,
                provider=provider_name,
            )

            # 10. Optionally create deal
            if (
                result.success
                and crm_config.config.get("create_deal")
                and result.external_id
            ):
                await self._create_deal(
                    provider=provider,
                    contact_id=result.external_id,
                    mapped_data=mapped_data,
                    config=crm_config.config,
                    call_id=call_id,
                    record_id=record_id,
                )

            logger.info(
                f"CRM sync {'completed' if result.success else 'failed'} "
                f"for call {call_id}: {provider_name}"
            )

            return result.success

        except Exception as e:
            logger.error(f"CRM dispatch error for call {call_id}: {e}", exc_info=True)
            return False

    async def _get_crm_config(self, call_id: UUID) -> Optional[CRMConfig]:
        """Fetch CRM config from project_crm_config table (M4+)."""
        db = get_database()

        # Get project_id from call
        call_data = await db.fetch_one(
            "SELECT project_id FROM calls WHERE id = :call_id",
            {"call_id": str(call_id)}
        )

        if not call_data or not call_data["project_id"]:
            logger.warning(f"Call {call_id} has no project_id, CRM sync skipped")
            return None

        # Query project_crm_config (M4+)
        config = await db.fetch_one(
            """
            SELECT enabled, provider, hubspot_api_key_encrypted, hubspot_portal_id,
                   webhook_url, webhook_secret_encrypted, config
            FROM project_crm_config
            WHERE project_id = :project_id AND enabled = TRUE
            """,
            {"project_id": str(call_data["project_id"])}
        )

        if not config:
            logger.info(f"No CRM config for project {call_data['project_id']}, sync skipped")
            return None

        # Decrypt API keys
        from app.services.encryption import decrypt

        credentials = {}
        if config["provider"] == "hubspot":
            if config["hubspot_api_key_encrypted"]:
                credentials["api_key"] = decrypt(config["hubspot_api_key_encrypted"])
            credentials["portal_id"] = config["hubspot_portal_id"]
        elif config["provider"] == "webhook":
            credentials["url"] = config["webhook_url"]
            if config["webhook_secret_encrypted"]:
                credentials["secret"] = decrypt(config["webhook_secret_encrypted"])

        return CRMConfig(
            enabled=True,
            provider=config["provider"],
            credentials=credentials,
            config=config["config"] or {}
        )


    async def _create_sync_log(
        self,
        call_id: UUID,
        record_id: Optional[int],
        provider: str,
        operation: str,
        request_payload: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Create initial sync log entry."""
        db = get_database()

        result = await db.fetch_one(
            """
            INSERT INTO crm_sync_log (
                call_id, record_id, provider, operation, status, request_payload,
                max_attempts, created_at
            )
            VALUES (
                :call_id, :record_id, :provider, :operation, :status, :request_payload,
                :max_attempts, :created_at
            )
            RETURNING id
            """,
            {
                "call_id": str(call_id),
                "record_id": record_id,
                "provider": provider,
                "operation": operation,
                "status": CRMSyncStatus.PENDING.value,
                "request_payload": json.dumps(request_payload) if request_payload else None,
                "max_attempts": self.settings.crm_retry_max_attempts,
                "created_at": datetime.now(timezone.utc),
            },
        )

        return result["id"]

    async def _update_record_crm_status(
        self,
        call_id: UUID,
        result: CRMSyncResult,
        provider: str,
    ) -> None:
        """Update records table with CRM sync status."""
        db = get_database()

        await db.execute(
            """
            UPDATE records
            SET crm_synced = :synced,
                crm_synced_at = :synced_at,
                crm_external_id = :external_id,
                crm_provider = :provider,
                crm_error = :error,
                updated_at = :updated_at
            WHERE call_id = :call_id
            """,
            {
                "call_id": str(call_id),
                "synced": result.success,
                "synced_at": datetime.now(timezone.utc) if result.success else None,
                "external_id": result.external_id,
                "provider": provider,
                "error": result.error_message if not result.success else None,
                "updated_at": datetime.now(timezone.utc),
            },
        )

    async def _create_deal(
        self,
        provider: BaseCRMProvider,
        contact_id: str,
        mapped_data: Dict[str, Any],
        config: Dict[str, Any],
        call_id: UUID,
        record_id: Optional[int],
    ) -> None:
        """Create a deal linked to the contact."""
        try:
            log_id = await self._create_sync_log(
                call_id=call_id,
                record_id=record_id,
                provider=provider.provider_name,
                operation=CRMOperation.CREATE_DEAL.value,
            )

            result = await provider.create_deal(
                contact_id=contact_id,
                data=mapped_data,
                config=config,
            )

            retry_manager = self._get_retry_manager()
            await retry_manager.update_final_status(log_id, result)

            if result.success:
                logger.info(f"CRM deal created for call {call_id}: {result.external_id}")
            else:
                logger.warning(f"CRM deal creation failed for call {call_id}: {result.error_message}")

        except Exception as e:
            logger.error(f"Error creating CRM deal for call {call_id}: {e}")

    async def retry_sync(self, call_id: UUID) -> bool:
        """
        Manually retry CRM sync for a call.

        Args:
            call_id: UUID of the call to retry

        Returns:
            True if retry was successful
        """
        db = get_database()

        # Fetch record with JSON data
        record = await db.fetch_one(
            """
            SELECT r.id, r.json_data, c.started_at, c.duration_seconds, c.phone_number
            FROM records r
            JOIN calls c ON r.call_id = c.id
            WHERE r.call_id = :call_id
            """,
            {"call_id": str(call_id)},
        )

        if not record:
            logger.warning(f"Record not found for call {call_id}")
            return False

        json_data = record["json_data"]
        if isinstance(json_data, str):
            json_data = json.loads(json_data)

        call_metadata = {
            "id": str(call_id),
            "started_at": record["started_at"],
            "duration_seconds": record["duration_seconds"],
            "phone_number": record["phone_number"],
        }

        return await self.dispatch(
            call_id=call_id,
            json_data=json_data,
            call_metadata=call_metadata,
        )

    async def test_connection(
        self,
        provider: str,
        credentials: Dict[str, str],
        config: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Test CRM connection with provided credentials.

        Args:
            provider: Provider name
            credentials: API credentials
            config: Optional provider config

        Returns:
            True if connection test passes
        """
        try:
            provider_instance = self._get_provider(
                provider,
                config or {},
                credentials,
            )
            return await provider_instance.test_connection()
        except Exception as e:
            logger.error(f"CRM connection test failed: {e}")
            return False
