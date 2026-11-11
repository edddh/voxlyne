"""
Voxlyne - Twilio Client

Lightweight Twilio client for phone number validation and status queries.
Note: With Vapi, Twilio is configured INSIDE Vapi as the phone provider.
Vapi manages the actual Twilio bridge. This client is for:
- Validating phone numbers
- Querying call status directly from Twilio (if needed)
- Future: direct Twilio integration without Vapi
"""

import logging
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# E.164 phone number pattern
E164_PATTERN = re.compile(r"^\+[1-9]\d{1,14}$")


class TwilioClient:
    """
    Lightweight Twilio REST API client.
    """

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        default_from_number: Optional[str] = None,
    ):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.default_from_number = default_from_number
        self.base_url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}"

    async def get_call_status(self, call_sid: str) -> dict:
        """
        Get the status of a Twilio call.

        Args:
            call_sid: Twilio Call SID

        Returns:
            Twilio call resource dict
        """
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/Calls/{call_sid}.json",
                auth=(self.account_sid, self.auth_token),
            )
            response.raise_for_status()
            return response.json()

    async def test_connection(self) -> bool:
        """
        Test Twilio API connectivity by fetching account info.

        Returns:
            True if credentials are valid
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.base_url}.json",
                    auth=(self.account_sid, self.auth_token),
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"Twilio connection test failed: {e}")
            return False

    async def list_phone_numbers(self) -> list:
        """List phone numbers on the account."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{self.base_url}/IncomingPhoneNumbers.json",
                auth=(self.account_sid, self.auth_token),
            )
            response.raise_for_status()
            data = response.json()
            return data.get("incoming_phone_numbers", [])


def validate_e164(phone_number: str) -> bool:
    """
    Validate that a phone number is in E.164 format.

    Args:
        phone_number: Phone number string (e.g. +4915123456789)

    Returns:
        True if valid E.164 format
    """
    return bool(E164_PATTERN.match(phone_number))


def normalize_phone_number(phone_number: str) -> Optional[str]:
    """
    Attempt to normalize a phone number to E.164 format.

    Args:
        phone_number: Raw phone number string

    Returns:
        E.164 formatted number or None if invalid
    """
    # Strip whitespace and common separators
    cleaned = re.sub(r"[\s\-\(\)\.]", "", phone_number)

    # If already E.164
    if validate_e164(cleaned):
        return cleaned

    # If starts with 00, replace with +
    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]
        if validate_e164(cleaned):
            return cleaned

    # If starts with 0 and looks German, prepend +49
    if cleaned.startswith("0") and len(cleaned) >= 10:
        cleaned = "+49" + cleaned[1:]
        if validate_e164(cleaned):
            return cleaned

    return None
