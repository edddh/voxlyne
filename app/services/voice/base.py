"""
Ascolta - Voice Engine Base Classes

Abstract base class and types for voice AI integrations.
Follows the same pattern as app/services/crm/base.py.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID


class VoiceEngineType(str, Enum):
    """Supported voice engine providers."""
    OPENAI_REALTIME = "openai_realtime"
    VAPI = "vapi"


class CallDirection(str, Enum):
    """Call direction."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class WebhookEventType(str, Enum):
    """Normalized webhook event types across providers."""
    CALL_STARTED = "call_started"
    CALL_ENDED = "call_ended"
    CALL_FAILED = "call_failed"
    TRANSCRIPT_UPDATE = "transcript_update"
    DTMF = "dtmf"
    STATUS_UPDATE = "status_update"
    TOOL_CALL = "tool_call"


@dataclass
class WebhookResult:
    """Normalized result from processing a provider-specific webhook."""
    event_type: WebhookEventType
    call_id: Optional[UUID] = None
    provider_call_id: Optional[str] = None
    phone_number: Optional[str] = None
    transcript_role: Optional[str] = None  # "user" or "assistant"
    transcript_text: Optional[str] = None
    dtmf_digit: Optional[str] = None
    call_status: Optional[str] = None
    error_message: Optional[str] = None
    raw_payload: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/storage."""
        return {
            "event_type": self.event_type.value,
            "call_id": str(self.call_id) if self.call_id else None,
            "provider_call_id": self.provider_call_id,
            "phone_number": self.phone_number,
            "transcript_role": self.transcript_role,
            "transcript_text": self.transcript_text[:200] if self.transcript_text else None,
            "dtmf_digit": self.dtmf_digit,
            "call_status": self.call_status,
            "error_message": self.error_message,
        }


@dataclass
class OutboundCallRequest:
    """Request to initiate an outbound call."""
    phone_number: str
    project_id: UUID
    prompt: str
    voice_name: Optional[str] = None
    language: str = "de"
    metadata: Dict[str, Any] = field(default_factory=dict)
    # Vapi-specific
    vapi_assistant_id: Optional[str] = None
    # Twilio-specific
    twilio_phone_number: Optional[str] = None


@dataclass
class OutboundCallResult:
    """Result from initiating an outbound call."""
    success: bool
    call_id: Optional[UUID] = None
    provider_call_id: Optional[str] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class BaseVoiceEngine(ABC):
    """
    Abstract base class for voice AI integrations.

    All voice engines must implement:
    - start_outbound_call: Initiate an outbound call
    - handle_webhook: Process provider-specific webhook events
    - end_call: Terminate an active call
    - test_connection: Verify credentials and connectivity

    Optional methods:
    - start_inbound_call: Handle an incoming call (OpenAI Realtime only for now)
    """

    engine_type: VoiceEngineType = VoiceEngineType.OPENAI_REALTIME

    @abstractmethod
    async def start_outbound_call(
        self,
        request: OutboundCallRequest,
    ) -> OutboundCallResult:
        """
        Initiate an outbound call.

        Args:
            request: Call configuration including phone number, prompt, voice settings

        Returns:
            OutboundCallResult with success status and provider call ID
        """
        pass

    async def start_inbound_call(
        self,
        call_id: UUID,
        session_id: str,
        prompt: str,
        **kwargs,
    ) -> None:
        """
        Handle an incoming call. Not all engines support this.

        Args:
            call_id: Internal call UUID
            session_id: Provider-specific session ID
            prompt: Conversation instructions
        """
        raise NotImplementedError(
            f"{self.engine_type.value} does not support inbound calls"
        )

    @abstractmethod
    async def end_call(
        self,
        call_id: UUID,
        provider_call_id: Optional[str] = None,
    ) -> bool:
        """
        Terminate an active call.

        Args:
            call_id: Internal call UUID
            provider_call_id: Provider-specific call identifier

        Returns:
            True if call was successfully terminated
        """
        pass

    @abstractmethod
    async def handle_webhook(
        self,
        payload: Dict[str, Any],
    ) -> WebhookResult:
        """
        Process a provider-specific webhook payload into a normalized WebhookResult.

        Args:
            payload: Raw webhook JSON payload

        Returns:
            Normalized WebhookResult
        """
        pass

    @abstractmethod
    async def test_connection(self) -> bool:
        """
        Verify credentials and connectivity to the voice provider.

        Returns:
            True if connection is successful
        """
        pass

    def get_supported_directions(self) -> List[CallDirection]:
        """Return the call directions this engine supports."""
        return [CallDirection.INBOUND, CallDirection.OUTBOUND]
