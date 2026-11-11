"""
Voxlyne - Vapi Voice Engine

Voice engine implementation using Vapi.ai for outbound calls.
Vapi manages the full STT → LLM → TTS pipeline and Twilio telephony bridge.
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
from app.services.voice.vapi_client import VapiClient

logger = logging.getLogger(__name__)


class VapiEngine(BaseVoiceEngine):
    """
    Voice engine using Vapi.ai for outbound calls.

    Vapi handles:
    - STT (Deepgram, Whisper, etc.)
    - LLM routing (GPT-4o, Claude, Groq, etc.)
    - TTS (ElevenLabs, PlayHT, OpenAI, etc.)
    - Twilio telephony bridge
    - Interruption handling
    - Turn detection

    Our backend:
    - Initiates calls via Vapi API
    - Receives webhook events
    - Stores transcripts
    - Runs post-processing (GPT-4 extraction, PDF, email, CRM)
    """

    engine_type = VoiceEngineType.VAPI

    def __init__(self, settings=None):
        self.settings = settings

    async def _get_vapi_client(self, project_id: UUID) -> VapiClient:
        """
        Get VapiClient with credentials for the given project.

        Uses CredentialsManager to fetch project-level API key with fallback to global .env.

        Args:
            project_id: UUID of the project

        Returns:
            VapiClient instance with project-specific credentials

        Raises:
            ValueError: If no API key is configured (neither project-level nor global)
        """
        from app.services.credentials.manager import CredentialsManager

        creds_manager = CredentialsManager()
        creds = await creds_manager.get_credentials(
            entity_type="project",
            entity_id=project_id,
            service_type="voice",
            provider="vapi",
        )

        api_key = creds.get("api_key")
        if not api_key:
            raise ValueError(
                f"Vapi API key not configured for project {project_id}. "
                "Please configure it in project settings or set VAPI_API_KEY in .env"
            )

        base_url = getattr(self.settings, "vapi_base_url", "https://api.vapi.ai")
        return VapiClient(api_key=api_key, base_url=base_url)

    async def start_outbound_call(
        self,
        request: OutboundCallRequest,
    ) -> OutboundCallResult:
        """
        Initiate an outbound call via Vapi.

        The assistant can be:
        1. A pre-configured Vapi assistant (by ID)
        2. An inline assistant with overrides (prompt, voice, etc.)
        """
        try:
            # Get Vapi client with project-specific credentials
            client = await self._get_vapi_client(request.project_id)

            # Build assistant overrides if no assistant_id
            assistant_id = request.vapi_assistant_id
            assistant_overrides = None

            if not assistant_id:
                # Create inline assistant config with the project's prompt
                assistant_overrides = await self._build_assistant_overrides(request)

            # Build metadata to link back to our internal call
            metadata = {
                **(request.metadata or {}),
                "project_id": str(request.project_id),
            }

            # Determine the phone number ID to call from
            phone_number_id = None
            if request.twilio_phone_number:
                # Vapi needs the phoneNumberId, not the raw number
                # The Twilio number should be configured in Vapi dashboard
                # and we reference it by Vapi's phoneNumberId
                metadata["twilio_from_number"] = request.twilio_phone_number

            vapi_phone_number_id = getattr(self.settings, "vapi_phone_number_id", None)

            result = await client.create_outbound_call(
                phone_number=request.phone_number,
                assistant_id=assistant_id,
                assistant_overrides=assistant_overrides,
                phone_number_id=vapi_phone_number_id,
                metadata=metadata,
            )

            vapi_call_id = result.get("id")
            logger.info(
                f"Vapi outbound call initiated: {vapi_call_id} → {request.phone_number}"
            )

            return OutboundCallResult(
                success=True,
                provider_call_id=vapi_call_id,
                metadata={"vapi_response": result},
            )

        except Exception as e:
            logger.error(f"Failed to start Vapi outbound call: {e}")
            return OutboundCallResult(
                success=False,
                error_message=str(e),
            )

    async def end_call(
        self,
        call_id: UUID,
        provider_call_id: Optional[str] = None,
    ) -> bool:
        """
        End a Vapi call.

        Note: Uses global Vapi credentials (not project-specific) for simplicity.
        """
        if not provider_call_id:
            logger.warning(f"No provider_call_id for Vapi hangup on call {call_id}")
            return False

        try:
            # Use global credentials for hangup (simpler, same account)
            client = self._get_vapi_client_global()
            await client.end_call(provider_call_id)
            return True
        except Exception as e:
            logger.error(f"Failed to end Vapi call {provider_call_id}: {e}")
            return False

    def _get_vapi_client_global(self) -> VapiClient:
        """Get VapiClient with global credentials from .env."""
        api_key = getattr(self.settings, "vapi_api_key", None)
        if not api_key:
            raise ValueError("VAPI_API_KEY is not configured in .env")
        base_url = getattr(self.settings, "vapi_base_url", "https://api.vapi.ai")
        return VapiClient(api_key=api_key, base_url=base_url)

    async def handle_webhook(
        self,
        payload: Dict[str, Any],
    ) -> WebhookResult:
        """
        Parse Vapi webhook events into normalized WebhookResult.

        Vapi webhook event types:
        - assistant-request: Vapi asks for assistant config (for dynamic assistants)
        - function-call: Deprecated, use tool-calls
        - tool-calls: LLM wants to call a tool
        - status-update: Call status changed (queued, ringing, in-progress, forwarding, ended)
        - end-of-call-report: Full call summary after completion
        - hang: Vapi detected it should hang up
        - speech-update: Speech activity (started/stopped)
        - transcript: Real-time transcript updates
        - conversation-update: Conversation messages update
        """
        message_type = payload.get("message", {}).get("type", "")

        # Vapi wraps everything in a 'message' object
        message = payload.get("message", payload)
        msg_type = message.get("type", message_type)

        if msg_type == "status-update":
            return self._handle_status_update(message)
        elif msg_type == "end-of-call-report":
            return self._handle_end_of_call_report(message)
        elif msg_type == "transcript":
            return self._handle_transcript(message)
        elif msg_type == "conversation-update":
            return self._handle_conversation_update(message)
        elif msg_type == "tool-calls":
            return self._handle_tool_calls(message)
        elif msg_type == "hang":
            return WebhookResult(
                event_type=WebhookEventType.CALL_ENDED,
                provider_call_id=message.get("call", {}).get("id"),
                raw_payload=payload,
            )
        elif msg_type == "speech-update":
            return WebhookResult(
                event_type=WebhookEventType.STATUS_UPDATE,
                call_status=f"speech_{message.get('status', 'unknown')}",
                provider_call_id=message.get("call", {}).get("id"),
                raw_payload=payload,
            )
        else:
            return WebhookResult(
                event_type=WebhookEventType.STATUS_UPDATE,
                call_status=msg_type,
                raw_payload=payload,
            )

    async def test_connection(self) -> bool:
        """
        Test Vapi API connectivity.

        Note: Uses global credentials from .env.
        """
        try:
            client = self._get_vapi_client_global()
            return await client.test_connection()
        except Exception as e:
            logger.error(f"Vapi test connection failed: {e}")
            return False

    def get_supported_directions(self) -> List[CallDirection]:
        """Vapi supports both inbound and outbound."""
        return [CallDirection.INBOUND, CallDirection.OUTBOUND]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    async def _build_assistant_overrides(self, request: OutboundCallRequest) -> Dict[str, Any]:
        """
        Build Vapi assistant overrides from an OutboundCallRequest.
        This allows dynamic configuration without pre-creating assistants in Vapi dashboard.
        """
        overrides: Dict[str, Any] = {
            "firstMessage": self._get_first_message(request.language),
            "model": {
                "provider": "openai",
                "model": "gpt-4o",
                "messages": [
                    {
                        "role": "system",
                        "content": request.prompt,
                    }
                ],
            },
            "voice": await self._get_voice_config(request),
            "silenceTimeoutSeconds": 10,
            "maxDurationSeconds": getattr(self.settings, "max_call_duration_seconds", 600),
            "backgroundSound": "off",
            "metadata": request.metadata,
        }

        # Transcriber config
        overrides["transcriber"] = {
            "provider": "deepgram",
            "model": "nova-2",
            "language": request.language,
        }

        return overrides

    async def _get_voice_config(self, request: OutboundCallRequest) -> Dict[str, Any]:
        """
        Build Vapi voice configuration, preferring ElevenLabs for German.

        Priority for voice_id:
        1. Request elevenlabs_voice_id (from project settings)
        2. Project-level ElevenLabs credentials from DB
        3. Global elevenlabs_voice_id from .env
        4. Fallback to OpenAI voice
        """
        from app.services.credentials.manager import CredentialsManager

        # Try to get ElevenLabs voice ID from request (project config)
        elevenlabs_voice_id = getattr(request, "elevenlabs_voice_id", None)

        # If not in request, try credentials manager
        if not elevenlabs_voice_id:
            try:
                creds_manager = CredentialsManager()
                elevenlabs_creds = await creds_manager.get_credentials(
                    entity_type="project",
                    entity_id=request.project_id,
                    service_type="tts",
                    provider="elevenlabs",
                )
                # Note: voice_id might be in project config, not credentials
                # Credentials only contain api_key for ElevenLabs
                # voice_id is usually in project.elevenlabs_voice_id field
            except Exception as e:
                logger.debug(f"Could not load ElevenLabs credentials: {e}")

        # Fallback to global settings
        if not elevenlabs_voice_id:
            elevenlabs_voice_id = getattr(self.settings, "elevenlabs_voice_id", None)

        if elevenlabs_voice_id:
            return {
                "provider": "11labs",
                "voiceId": elevenlabs_voice_id,
                "stability": 0.5,
                "similarityBoost": 0.75,
                "model": "eleven_turbo_v2_5",
            }

        # Fallback to OpenAI voice
        voice_name = request.voice_name or "alloy"
        return {
            "provider": "openai",
            "voiceId": voice_name,
        }

    def _get_first_message(self, language: str) -> str:
        """Get the opening message based on language."""
        if language == "de":
            return "Hallo, guten Tag!"
        elif language == "en":
            return "Hello, good day!"
        else:
            return "Buongiorno!"

    def _handle_status_update(self, message: Dict[str, Any]) -> WebhookResult:
        """Handle Vapi status-update events."""
        status = message.get("status", "")
        call_data = message.get("call", {})
        vapi_call_id = call_data.get("id")

        # Map Vapi statuses to our event types
        if status == "in-progress":
            return WebhookResult(
                event_type=WebhookEventType.CALL_STARTED,
                provider_call_id=vapi_call_id,
                phone_number=call_data.get("customer", {}).get("number"),
                call_status=status,
                raw_payload=message,
            )
        elif status == "ended":
            return WebhookResult(
                event_type=WebhookEventType.CALL_ENDED,
                provider_call_id=vapi_call_id,
                call_status=status,
                metadata={
                    "ended_reason": message.get("endedReason", ""),
                    "duration_seconds": call_data.get("duration"),
                },
                raw_payload=message,
            )
        elif status in ("queued", "ringing"):
            return WebhookResult(
                event_type=WebhookEventType.STATUS_UPDATE,
                provider_call_id=vapi_call_id,
                call_status=status,
                raw_payload=message,
            )
        else:
            return WebhookResult(
                event_type=WebhookEventType.STATUS_UPDATE,
                provider_call_id=vapi_call_id,
                call_status=status,
                raw_payload=message,
            )

    def _handle_end_of_call_report(self, message: Dict[str, Any]) -> WebhookResult:
        """
        Handle Vapi end-of-call-report.
        This contains the full transcript and call summary.
        """
        call_data = message.get("call", {})
        vapi_call_id = call_data.get("id")

        return WebhookResult(
            event_type=WebhookEventType.CALL_ENDED,
            provider_call_id=vapi_call_id,
            call_status="ended",
            metadata={
                "summary": message.get("summary", ""),
                "transcript": message.get("transcript", ""),
                "ended_reason": message.get("endedReason", ""),
                "duration_seconds": call_data.get("duration"),
                "recording_url": message.get("recordingUrl"),
                "stereo_recording_url": message.get("stereoRecordingUrl"),
                "messages": message.get("messages", []),
            },
            raw_payload=message,
        )

    def _handle_transcript(self, message: Dict[str, Any]) -> WebhookResult:
        """Handle Vapi real-time transcript events."""
        call_data = message.get("call", {})
        vapi_call_id = call_data.get("id")
        role = message.get("role", "user")  # "user" or "assistant"
        transcript_type = message.get("transcriptType", "")  # "partial" or "final"
        text = message.get("transcript", "")

        return WebhookResult(
            event_type=WebhookEventType.TRANSCRIPT_UPDATE,
            provider_call_id=vapi_call_id,
            transcript_role=role,
            transcript_text=text,
            metadata={"transcript_type": transcript_type},
            raw_payload=message,
        )

    def _handle_conversation_update(self, message: Dict[str, Any]) -> WebhookResult:
        """Handle Vapi conversation-update events (full message list)."""
        call_data = message.get("call", {})
        vapi_call_id = call_data.get("id")

        return WebhookResult(
            event_type=WebhookEventType.TRANSCRIPT_UPDATE,
            provider_call_id=vapi_call_id,
            metadata={
                "conversation": message.get("messages", []),
            },
            raw_payload=message,
        )

    def _handle_tool_calls(self, message: Dict[str, Any]) -> WebhookResult:
        """Handle Vapi tool-calls events (LLM wants to use a tool)."""
        call_data = message.get("call", {})
        vapi_call_id = call_data.get("id")
        tool_calls = message.get("toolCalls", [])

        return WebhookResult(
            event_type=WebhookEventType.TOOL_CALL,
            provider_call_id=vapi_call_id,
            metadata={"tool_calls": tool_calls},
            raw_payload=message,
        )
