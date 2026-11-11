"""
Voxlyne - Generic Webhook Provider

Sends candidate data to any HTTP endpoint.
Supports HMAC signature for webhook verification.
"""

import hashlib
import hmac
import json
import logging
from typing import Any, Dict, Optional

import httpx

from app.services.crm.base import (
    BaseCRMProvider,
    CRMOperation,
    CRMSyncResult,
)

logger = logging.getLogger(__name__)


class GenericWebhookProvider(BaseCRMProvider):
    """
    Generic webhook provider for any HTTP endpoint.

    Features:
    - Configurable HTTP method (POST, PUT, PATCH)
    - Custom headers support
    - HMAC signature for security
    - Flexible timeout configuration
    """

    provider_name = "generic_webhook"

    def __init__(
        self,
        url: str,
        secret: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        method: str = "POST",
        timeout: float = 30.0,
    ):
        """
        Initialize webhook provider.

        Args:
            url: Target webhook URL
            secret: HMAC secret for signature (optional)
            headers: Custom headers to include
            method: HTTP method (POST, PUT, PATCH)
            timeout: Request timeout in seconds
        """
        self.url = url
        self.secret = secret
        self.custom_headers = headers or {}
        self.method = method.upper()
        self.timeout = timeout

    def _sign_payload(self, payload: bytes) -> str:
        """
        Generate HMAC-SHA256 signature for payload.

        Args:
            payload: Request body bytes

        Returns:
            Hex-encoded signature
        """
        if not self.secret:
            return ""
        return hmac.new(
            self.secret.encode("utf-8"),
            payload,
            hashlib.sha256,
        ).hexdigest()

    async def create_contact(
        self,
        data: Dict[str, Any],
        config: Dict[str, Any],
    ) -> CRMSyncResult:
        """
        Send candidate data to configured webhook URL.

        Args:
            data: Mapped candidate data
            config: Provider-specific configuration

        Returns:
            CRMSyncResult with success status
        """
        # Prepare payload
        payload_dict = {
            "event": "candidate.created",
            "timestamp": data.get("call_started_at"),
            "data": data,
        }
        payload = json.dumps(payload_dict, default=str).encode("utf-8")

        # Build headers
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Voxlyne/1.0",
            **self.custom_headers,
        }

        # Add signature if secret configured
        if self.secret:
            signature = self._sign_payload(payload)
            headers["X-Webhook-Signature"] = f"sha256={signature}"
            headers["X-Signature-Algorithm"] = "HMAC-SHA256"

        # Add timestamp for replay protection
        import time
        headers["X-Webhook-Timestamp"] = str(int(time.time()))

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method=self.method,
                    url=self.url,
                    content=payload,
                    headers=headers,
                )

                # Check for success (2xx status codes)
                is_success = 200 <= response.status_code < 300

                # Try to extract external ID from response
                external_id = None
                try:
                    response_json = response.json()
                    external_id = (
                        response_json.get("id")
                        or response_json.get("external_id")
                        or response_json.get("record_id")
                    )
                except Exception:
                    pass

                # Also check headers for external ID
                if not external_id:
                    external_id = response.headers.get("X-Resource-Id")

                return CRMSyncResult(
                    success=is_success,
                    external_id=str(external_id) if external_id else None,
                    response_code=response.status_code,
                    response_body=response.text[:2000],
                    error_message=(
                        None
                        if is_success
                        else f"Webhook returned {response.status_code}"
                    ),
                    should_retry=self.is_retryable_error(response.status_code),
                    operation=CRMOperation.WEBHOOK,
                    request_payload={"url": self.url, "method": self.method},
                )

        except httpx.TimeoutException:
            logger.warning(f"Webhook timeout: {self.url}")
            return CRMSyncResult(
                success=False,
                error_message=f"Request timeout after {self.timeout}s",
                should_retry=True,
                operation=CRMOperation.WEBHOOK,
                request_payload={"url": self.url, "method": self.method},
            )

        except httpx.ConnectError as e:
            logger.warning(f"Webhook connection error: {self.url} - {e}")
            return CRMSyncResult(
                success=False,
                error_message=f"Connection error: {str(e)}",
                should_retry=True,
                operation=CRMOperation.WEBHOOK,
                request_payload={"url": self.url, "method": self.method},
            )

        except Exception as e:
            logger.error(f"Webhook error: {self.url} - {e}")
            return CRMSyncResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}",
                should_retry=False,
                operation=CRMOperation.WEBHOOK,
                request_payload={"url": self.url, "method": self.method},
            )

    async def test_connection(self) -> bool:
        """
        Test webhook connectivity with a HEAD or GET request.

        Returns:
            True if endpoint is reachable
        """
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try HEAD first (less invasive)
                try:
                    response = await client.head(self.url)
                    return response.status_code < 500
                except Exception:
                    pass

                # Fall back to GET
                response = await client.get(self.url)
                return response.status_code < 500

        except Exception as e:
            logger.warning(f"Webhook connection test failed: {e}")
            return False
