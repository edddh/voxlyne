"""
Ascolta - OpenAI Realtime Voice Engine

Wraps the existing RealtimeSession to conform to the BaseVoiceEngine interface.
This engine handles INBOUND calls via OpenAI's SIP gateway.
Outbound is not natively supported (use Vapi engine for outbound).
"""

import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from app.services.voice.base import (
    BaseVoiceEngine,
    CallDirection,
    OutboundCallRequest,
    OutboundCallResult,
    VoiceEngineType,
    WebhookEventType,
    WebhookResult,
)

logger = logging.getLogger(__name__)


class OpenAIRealtimeEngine(BaseVoiceEngine):
    """
    Voice engine using OpenAI Realtime API.

    This is the original engine used for inbound SIP calls.
    It delegates to the existing RealtimeSession and CallManager
    for actual call handling. The webhook processing for OpenAI SIP
    events remains in webhook.py as before.
    """

    engine_type = VoiceEngineType.OPENAI_REALTIME

    def __init__(self, settings=None):
        self.settings = settings

    async def start_outbound_call(
        self,
        request: OutboundCallRequest,
    ) -> OutboundCallResult:
        """OpenAI Realtime does not support outbound calls natively."""
        return OutboundCallResult(
            success=False,
            error_message="OpenAI Realtime engine does not support outbound calls. Use Vapi engine instead.",
        )

    async def start_inbound_call(
        self,
        call_id: UUID,
        session_id: str,
        prompt: str,
        **kwargs,
    ) -> None:
        """
        Handle an incoming SIP call via OpenAI Realtime API.
        This delegates to the existing CallManager.start_session() flow.
        """
        # Import here to avoid circular imports
        from app.services.call_manager import CallManager

        call_manager = CallManager()
        await call_manager.start_session(call_id=call_id, session_id=session_id)

    async def end_call(
        self,
        call_id: UUID,
        provider_call_id: Optional[str] = None,
    ) -> bool:
        """
        End an OpenAI Realtime call by hanging up the SIP session.
        """
        if not provider_call_id:
            logger.warning(f"No provider_call_id for OpenAI hangup on call {call_id}")
            return False

        try:
            import httpx

            url = f"https://api.openai.com/v1/realtime/calls/{provider_call_id}/hangup"
            headers = {
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers)
                if response.status_code == 200:
                    logger.info(f"OpenAI SIP hangup successful for {provider_call_id}")
                    return True
                else:
                    logger.warning(f"OpenAI hangup returned {response.status_code}")
                    return False

        except Exception as e:
            logger.error(f"Error hanging up OpenAI call: {e}")
            return False

    async def handle_webhook(
        self,
        payload: Dict[str, Any],
    ) -> WebhookResult:
        """
        Parse OpenAI SIP webhook events into normalized WebhookResult.
        Note: The actual handling logic remains in webhook.py for backwards compatibility.
        This method provides normalization for the new abstraction layer.
        """
        event_type = payload.get("type", "")

        if event_type in ("call.started", "session.created", "realtime.call.incoming"):
            session_id = (
                payload.get("data", {}).get("call_id")
                or payload.get("session", {}).get("id")
                or payload.get("session_id")
            )
            return WebhookResult(
                event_type=WebhookEventType.CALL_STARTED,
                provider_call_id=session_id,
                raw_payload=payload,
            )

        elif event_type in ("call.ended", "realtime.call.ended"):
            session_id = (
                payload.get("data", {}).get("call_id")
                or payload.get("session", {}).get("id")
                or payload.get("session_id")
            )
            return WebhookResult(
                event_type=WebhookEventType.CALL_ENDED,
                provider_call_id=session_id,
                raw_payload=payload,
            )

        elif "dtmf" in event_type.lower():
            digit = (
                payload.get("digit")
                or payload.get("input", {}).get("digit")
                or payload.get("data", {}).get("digit")
            )
            session_id = (
                payload.get("session", {}).get("id")
                or payload.get("session_id")
                or payload.get("data", {}).get("call_id")
            )
            return WebhookResult(
                event_type=WebhookEventType.DTMF,
                provider_call_id=session_id,
                dtmf_digit=str(digit) if digit else None,
                raw_payload=payload,
            )

        elif event_type == "error":
            error = payload.get("error", {})
            return WebhookResult(
                event_type=WebhookEventType.CALL_FAILED,
                error_message=error.get("message", "Unknown error"),
                raw_payload=payload,
            )

        else:
            return WebhookResult(
                event_type=WebhookEventType.STATUS_UPDATE,
                call_status=event_type,
                raw_payload=payload,
            )

    async def test_connection(self) -> bool:
        """Test OpenAI API connectivity."""
        try:
            import httpx

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {self.settings.openai_api_key}"},
                )
                return response.status_code == 200
        except Exception as e:
            logger.error(f"OpenAI connection test failed: {e}")
            return False

    def get_supported_directions(self) -> List[CallDirection]:
        """OpenAI Realtime only supports inbound via SIP."""
        return [CallDirection.INBOUND]
