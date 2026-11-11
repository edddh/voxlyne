"""
Voxlyne - Vapi.ai REST API Client

HTTP client for Vapi.ai API interactions.
Handles outbound calls, assistant management, and webhook processing.

API Reference: https://docs.vapi.ai/api-reference
"""

import logging
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_VAPI_BASE_URL = "https://api.vapi.ai"


class VapiClient:
    """
    HTTP client for Vapi.ai REST API.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = DEFAULT_VAPI_BASE_URL,
        timeout: float = 30.0,
    ):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def create_outbound_call(
        self,
        phone_number: str,
        assistant_id: Optional[str] = None,
        assistant_overrides: Optional[Dict[str, Any]] = None,
        phone_number_id: Optional[str] = None,
        customer: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Create an outbound phone call via Vapi.

        Args:
            phone_number: The phone number to call (E.164 format, e.g. +4915123456789)
            assistant_id: Vapi assistant ID to use for the call
            assistant_overrides: Override assistant settings (prompt, voice, etc.)
            phone_number_id: Vapi phone number ID to call from
            customer: Customer info dict with 'number' key
            metadata: Custom metadata to attach to the call

        Returns:
            Vapi call object with 'id', 'status', etc.
        """
        payload: Dict[str, Any] = {}

        if assistant_id:
            payload["assistantId"] = assistant_id

        if assistant_overrides:
            payload["assistantOverrides"] = assistant_overrides

        if phone_number_id:
            payload["phoneNumberId"] = phone_number_id

        # Customer with the number to call
        if customer:
            payload["customer"] = customer
        else:
            payload["customer"] = {"number": phone_number}

        if metadata:
            payload["metadata"] = metadata

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/call/phone",
                headers=self._headers(),
                json=payload,
            )

            if response.status_code >= 400:
                logger.error(
                    f"Vapi create_outbound_call failed: {response.status_code} {response.text}"
                )
                response.raise_for_status()

            result = response.json()
            logger.info(f"Vapi outbound call created: {result.get('id')}")
            return result

    async def get_call(self, call_id: str) -> Dict[str, Any]:
        """
        Get call details from Vapi.

        Args:
            call_id: Vapi call ID

        Returns:
            Vapi call object
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/call/{call_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def end_call(self, call_id: str) -> Dict[str, Any]:
        """
        End an active Vapi call.

        Args:
            call_id: Vapi call ID

        Returns:
            Updated call object
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Vapi uses PATCH to update call status
            response = await client.patch(
                f"{self.base_url}/call/{call_id}",
                headers=self._headers(),
                json={"status": "ended"},
            )

            if response.status_code >= 400:
                logger.error(f"Vapi end_call failed: {response.status_code} {response.text}")
                response.raise_for_status()

            result = response.json()
            logger.info(f"Vapi call ended: {call_id}")
            return result

    async def list_phone_numbers(self) -> list:
        """List all phone numbers configured in Vapi."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/phone-number",
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def get_assistant(self, assistant_id: str) -> Dict[str, Any]:
        """Get assistant details."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/assistant/{assistant_id}",
                headers=self._headers(),
            )
            response.raise_for_status()
            return response.json()

    async def test_connection(self) -> bool:
        """
        Test API connectivity by listing phone numbers.

        Returns:
            True if API key is valid and connection works
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}/phone-number",
                    headers=self._headers(),
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Vapi connection test failed: {e}")
            return False
