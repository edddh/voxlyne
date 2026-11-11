"""
Voxlyne - HubSpot CRM Provider

Creates contacts and deals in HubSpot using the CRM API v3.
https://developers.hubspot.com/docs/api/crm/contacts
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

from app.services.crm.base import (
    BaseCRMProvider,
    CRMOperation,
    CRMSyncResult,
)

logger = logging.getLogger(__name__)


class HubSpotProvider(BaseCRMProvider):
    """
    HubSpot CRM integration.

    Features:
    - Create contacts with standard and custom properties
    - Create deals linked to contacts
    - Handle duplicate contacts (409 response)
    - Support for private apps and OAuth tokens
    """

    provider_name = "hubspot"
    BASE_URL = "https://api.hubapi.com"

    # HubSpot-specific retryable codes
    RETRYABLE_STATUS_CODES = [429, 500, 502, 503, 504, 522, 524]

    def __init__(
        self,
        api_key: Optional[str] = None,
        access_token: Optional[str] = None,
        timeout: float = 30.0,
    ):
        """
        Initialize HubSpot provider.

        Args:
            api_key: HubSpot Private App API key (hapikey - deprecated)
            access_token: HubSpot OAuth or Private App access token (preferred)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.access_token = access_token
        self.timeout = timeout

        if not self.api_key and not self.access_token:
            logger.warning("HubSpot provider initialized without credentials")

    def _get_headers(self) -> Dict[str, str]:
        """Get authorization headers for HubSpot API."""
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        elif self.api_key:
            # Legacy API key (deprecated but still works for some endpoints)
            headers["Authorization"] = f"Bearer {self.api_key}"

        return headers

    async def create_contact(
        self,
        data: Dict[str, Any],
        config: Dict[str, Any],
    ) -> CRMSyncResult:
        """
        Create a HubSpot Contact via CRM API v3.

        Args:
            data: Mapped contact properties
            config: Provider-specific configuration

        Returns:
            CRMSyncResult with success status and HubSpot contact ID
        """
        url = f"{self.BASE_URL}/crm/v3/objects/contacts"

        # Build properties payload
        # HubSpot expects properties as a flat object
        properties = {}
        for key, value in data.items():
            # Skip internal fields
            if key.startswith("_"):
                continue
            # Convert non-string values
            if isinstance(value, bool):
                properties[key] = "true" if value else "false"
            elif isinstance(value, (list, dict)):
                import json
                properties[key] = json.dumps(value)
            elif value is not None:
                properties[key] = str(value)

        payload = {"properties": properties}

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code == 201:
                    # Contact created successfully
                    result = response.json()
                    contact_id = result.get("id")

                    logger.info(f"HubSpot contact created: {contact_id}")

                    return CRMSyncResult(
                        success=True,
                        external_id=contact_id,
                        response_code=response.status_code,
                        response_body=response.text[:1000],
                        operation=CRMOperation.CREATE_CONTACT,
                        request_payload={"properties_count": len(properties)},
                    )

                elif response.status_code == 409:
                    # Contact already exists - try to find and return existing
                    return await self._handle_duplicate_contact(
                        data, response, config
                    )

                else:
                    # Error response
                    error_msg = self._extract_error_message(response)
                    return CRMSyncResult(
                        success=False,
                        response_code=response.status_code,
                        response_body=response.text[:1000],
                        error_message=error_msg,
                        should_retry=self.is_retryable_error(response.status_code),
                        operation=CRMOperation.CREATE_CONTACT,
                        request_payload={"properties_count": len(properties)},
                    )

        except httpx.TimeoutException:
            return CRMSyncResult(
                success=False,
                error_message=f"HubSpot request timeout after {self.timeout}s",
                should_retry=True,
                operation=CRMOperation.CREATE_CONTACT,
            )

        except httpx.ConnectError as e:
            return CRMSyncResult(
                success=False,
                error_message=f"HubSpot connection error: {str(e)}",
                should_retry=True,
                operation=CRMOperation.CREATE_CONTACT,
            )

        except Exception as e:
            logger.error(f"HubSpot create_contact error: {e}")
            return CRMSyncResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}",
                should_retry=False,
                operation=CRMOperation.CREATE_CONTACT,
            )

    async def _handle_duplicate_contact(
        self,
        data: Dict[str, Any],
        response: httpx.Response,
        config: Dict[str, Any],
    ) -> CRMSyncResult:
        """
        Handle 409 Conflict - contact already exists.

        Attempts to find the existing contact by email or phone.
        """
        logger.info("HubSpot contact already exists, searching for existing record")

        # Try to find by email first
        email = data.get("email")
        if email:
            existing = await self._search_contact_by_email(email)
            if existing:
                return CRMSyncResult(
                    success=True,
                    external_id=existing,
                    response_code=200,
                    response_body="Contact already exists (found by email)",
                    operation=CRMOperation.CREATE_CONTACT,
                )

        # Try to find by phone
        phone = data.get("phone")
        if phone:
            existing = await self._search_contact_by_phone(phone)
            if existing:
                return CRMSyncResult(
                    success=True,
                    external_id=existing,
                    response_code=200,
                    response_body="Contact already exists (found by phone)",
                    operation=CRMOperation.CREATE_CONTACT,
                )

        # Could not find existing contact
        return CRMSyncResult(
            success=False,
            response_code=409,
            response_body=response.text[:1000],
            error_message="Duplicate contact detected but could not find existing record",
            should_retry=False,
            operation=CRMOperation.CREATE_CONTACT,
        )

    async def _search_contact_by_email(self, email: str) -> Optional[str]:
        """Search for contact by email, return contact ID if found."""
        url = f"{self.BASE_URL}/crm/v3/objects/contacts/search"
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "email",
                            "operator": "EQ",
                            "value": email,
                        }
                    ]
                }
            ],
            "limit": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code == 200:
                    results = response.json().get("results", [])
                    if results:
                        return results[0].get("id")
        except Exception as e:
            logger.warning(f"Error searching HubSpot by email: {e}")

        return None

    async def _search_contact_by_phone(self, phone: str) -> Optional[str]:
        """Search for contact by phone, return contact ID if found."""
        url = f"{self.BASE_URL}/crm/v3/objects/contacts/search"
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "phone",
                            "operator": "EQ",
                            "value": phone,
                        }
                    ]
                }
            ],
            "limit": 1,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code == 200:
                    results = response.json().get("results", [])
                    if results:
                        return results[0].get("id")
        except Exception as e:
            logger.warning(f"Error searching HubSpot by phone: {e}")

        return None

    async def create_deal(
        self,
        contact_id: str,
        data: Dict[str, Any],
        config: Dict[str, Any],
    ) -> CRMSyncResult:
        """
        Create a HubSpot Deal and associate with Contact.

        Args:
            contact_id: HubSpot Contact ID to associate
            data: Deal properties
            config: Provider-specific configuration (pipeline, stage)

        Returns:
            CRMSyncResult with deal ID
        """
        # Get pipeline configuration
        pipeline = config.get("deal_pipeline", "default")
        stage = config.get("deal_stage", "appointmentscheduled")

        # Build deal properties
        candidate_name = data.get("firstname", "")
        if data.get("lastname"):
            candidate_name += f" {data['lastname']}"

        properties = {
            "dealname": f"Candidatura - {candidate_name}".strip() or "Nuova Candidatura",
            "pipeline": pipeline,
            "dealstage": stage,
            "amount": "0",
        }

        # Add any role targets as deal description
        if "jobtitle" in data:
            properties["description"] = f"Ruolo: {data['jobtitle']}"

        payload = {
            "properties": properties,
            "associations": [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 3,  # Deal to Contact
                        }
                    ],
                }
            ],
        }

        url = f"{self.BASE_URL}/crm/v3/objects/deals"

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    url,
                    headers=self._get_headers(),
                    json=payload,
                )

                if response.status_code == 201:
                    result = response.json()
                    deal_id = result.get("id")
                    logger.info(f"HubSpot deal created: {deal_id}")

                    return CRMSyncResult(
                        success=True,
                        external_id=deal_id,
                        response_code=response.status_code,
                        response_body=response.text[:500],
                        operation=CRMOperation.CREATE_DEAL,
                    )

                else:
                    error_msg = self._extract_error_message(response)
                    return CRMSyncResult(
                        success=False,
                        response_code=response.status_code,
                        response_body=response.text[:500],
                        error_message=error_msg,
                        should_retry=self.is_retryable_error(response.status_code),
                        operation=CRMOperation.CREATE_DEAL,
                    )

        except Exception as e:
            logger.error(f"HubSpot create_deal error: {e}")
            return CRMSyncResult(
                success=False,
                error_message=f"Error creating deal: {str(e)}",
                should_retry=True,
                operation=CRMOperation.CREATE_DEAL,
            )

    async def test_connection(self) -> bool:
        """
        Test HubSpot API connectivity by fetching account info.

        Returns:
            True if connection is successful
        """
        # Use contacts endpoint to verify auth
        url = f"{self.BASE_URL}/crm/v3/objects/contacts?limit=1"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    url,
                    headers=self._get_headers(),
                )
                if response.status_code == 200:
                    logger.info("HubSpot connection test successful")
                    return True
                else:
                    logger.warning(
                        f"HubSpot connection test failed: {response.status_code}"
                    )
                    return False

        except Exception as e:
            logger.warning(f"HubSpot connection test error: {e}")
            return False

    def _extract_error_message(self, response: httpx.Response) -> str:
        """Extract human-readable error message from HubSpot response."""
        try:
            error_data = response.json()
            return (
                error_data.get("message")
                or error_data.get("error")
                or f"HubSpot API error: {response.status_code}"
            )
        except Exception:
            return f"HubSpot API error: {response.status_code} - {response.text[:200]}"
