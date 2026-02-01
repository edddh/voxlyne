"""
Ascolta - Realtime Session Handler
Manages OpenAI Realtime API WebSocket connection for voice calls
"""

import asyncio
import json
import logging
from datetime import datetime
from typing import Awaitable, Callable, Optional
from uuid import UUID

import websockets
from websockets.client import WebSocketClientProtocol

from app.config import get_settings
from app.database.db import get_database

logger = logging.getLogger(__name__)


# Default Italian conversation prompt (hardcoded for M1)
# In M2, this will be loaded from the database per project
DEFAULT_PROMPT_A = """Sei un assistente AI professionale che conduce colloqui telefonici in italiano per Demo Organization, un'azienda leader nelle costruzioni.

IMPORTANTE - CONSENSO GDPR:
All'inizio della chiamata, DEVI chiedere il consenso per raccogliere e processare i dati:

"Buongiorno! Grazie per aver chiamato Ascolta. Prima di iniziare, devo informarla che questa conversazione verrà registrata e analizzata per valutare la sua candidatura. I suoi dati saranno trattati secondo il GDPR. Lei può interrompere in qualsiasi momento premendo il tasto 9 sul telefono, oppure dicendo 'cancella i miei dati', per eliminare la trascrizione di questa chiamata. Accetta di procedere con il colloquio? Risponda sì o no."

ATTENDI la risposta dell'utente:
- Se dice "sì", "accetto", "va bene" o simili → Procedi con il colloquio
- Se dice "no", "non accetto" o simili → Ringrazia e termina la chiamata
- Se non risponde o è incerto → Ripeti la domanda una volta

DOPO IL CONSENSO, conduci il colloquio:

1. Presentati brevemente
2. Chiedi: "Per quale ruolo ti stai candidando?"
3. Chiedi: "Raccontami un'esperienza lavorativa di cui vai particolarmente fiero"
4. Chiedi: "Quali sono le tue principali competenze tecniche?"
5. Chiedi: "Come ti trovi a lavorare in squadra? Fammi un esempio"
6. Chiedi: "Disponibilità: puoi lavorare in trasferta o su turni se necessario?"

REGOLE:
- Sii professionale ma cordiale
- Fai domande brevi e chiare
- NON chiedere: età, genere, religione, nazionalità, stato di salute
- Se l'utente offre spontaneamente dati sensibili, rispondi: "Non è necessario condividere questa informazione"
- Se l'utente fa silenzio per più di 5 secondi, chiedi: "Sei ancora lì? Vuoi che ripeta la domanda?"
- Alla fine ringrazia e spiega che riceverà un riscontro

Usa un tono naturale e conversazionale. Mantieni le risposte concise."""


class RealtimeSession:
    """
    Manages a single OpenAI Realtime API WebSocket session for a phone call.

    Responsibilities:
    - WebSocket connection management
    - Conversation flow (consent → interview)
    - DTMF detection
    - Transcript buffering
    - Error handling
    """

    def __init__(
        self,
        call_id: UUID,
        openai_session_id: str,
        on_consent_received: Callable[[UUID, bool], None],
        on_interview_complete: Callable[[UUID], None],
        on_error: Callable[[UUID, str], None],
        on_dtmf_cancel: Callable[[UUID, str], Awaitable[None]],
    ):
        self.call_id = call_id
        self.openai_session_id = openai_session_id
        self.on_consent_received = on_consent_received
        self.on_interview_complete = on_interview_complete
        self.on_error = on_error
        self.on_dtmf_cancel = on_dtmf_cancel

        self.settings = get_settings()
        self.ws: Optional[WebSocketClientProtocol] = None
        self.is_connected = False
        self.consent_given = False
        self.transcript_buffer = []
        self._output_transcript_buffer: list[str] = []
        self._input_transcript_buffer: list[str] = []
        self._finalized = False
        self._dtmf_cancelled = False

        # Task management
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        """
        Connect to OpenAI Realtime API via WebSocket.
        """
        try:
            # Construct WebSocket URL
            # See: https://platform.openai.com/docs/guides/realtime
            if self.openai_session_id and self.openai_session_id.startswith("rtc_"):
                ws_url = (
                    f"wss://api.openai.com/v1/realtime"
                    f"?call_id={self.openai_session_id}"
                )
            else:
                ws_url = (
                    f"wss://api.openai.com/v1/realtime"
                    f"?model={self.settings.openai_realtime_model}"
                )

            headers = {
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "OpenAI-Beta": "realtime=v1",
            }

            logger.info(f"Connecting to OpenAI Realtime API for call {self.call_id}")

            self.ws = await websockets.connect(
                ws_url,
                additional_headers=headers,
                ping_interval=20,
                ping_timeout=10,
            )

            self.is_connected = True
            logger.info(f"WebSocket connected for call {self.call_id}")

            # Start receiving messages
            self._receive_task = asyncio.create_task(self._receive_loop())

            # Start timeout watchdog
            self._timeout_task = asyncio.create_task(self._timeout_watchdog())

            # Configure the session
            await self._configure_session()

        except Exception as e:
            logger.error(f"Failed to connect WebSocket: {e}")
            await self.on_error(self.call_id, f"Connection failed: {e}")
            raise

    async def disconnect(self) -> None:
        """
        Disconnect from OpenAI Realtime API.
        """
        self.is_connected = False

        # Cancel tasks
        if self._receive_task:
            self._receive_task.cancel()
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
        if self._timeout_task:
            self._timeout_task.cancel()

        # Close WebSocket
        if self.ws:
            try:
                await self.ws.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket for call {self.call_id}: {e}")

        logger.info(f"WebSocket disconnected for call {self.call_id}")

        # Flush remaining transcripts with error handling
        try:
            if self._output_transcript_buffer:
                await self._persist_transcript("assistant", "".join(self._output_transcript_buffer))
                self._output_transcript_buffer = []
            if self._input_transcript_buffer:
                await self._persist_transcript("user", "".join(self._input_transcript_buffer))
                self._input_transcript_buffer = []
        except Exception as e:
            logger.error(f"Error flushing transcripts for call {self.call_id}: {e}")

        # Mark call ended with error handling
        try:
            await self._mark_call_ended()
        except Exception as e:
            logger.error(f"CRITICAL: Failed to finalize call {self.call_id} on disconnect: {e}")
        finally:
            self._finalized = True

    async def _configure_session(self) -> None:
        """
        Configure the Realtime session with system prompt and settings.
        """
        is_sip_call = self.openai_session_id and self.openai_session_id.startswith("rtc_")

        # SIP calls are configured via the accept() request; keep session.update minimal.
        if is_sip_call:
            session_config = {
                "type": "realtime",
                "instructions": DEFAULT_PROMPT_A,
            }
        else:
            session_config = {
                "type": "realtime",
                "instructions": DEFAULT_PROMPT_A,
                "audio": {
                    "input": {
                        "transcription": {
                            "model": "whisper-1",
                            "language": "it",
                        },
                        "turn_detection": {
                            "type": "server_vad",
                            "threshold": 0.5,
                            "prefix_padding_ms": 300,
                            "silence_duration_ms": 500,
                        },
                    }
                },
                "temperature": 0.8,
                "max_response_output_tokens": 4096,
                "voice": self.settings.openai_realtime_voice,
            }

        config = {
            "type": "session.update",
            "session": session_config,
        }

        await self._send_message(config)
        logger.info(f"Session configured for call {self.call_id}")

    async def send_consent_prompt(self) -> None:
        """
        Send the initial consent prompt.
        The prompt is already in the system instructions,
        so we just need to trigger the conversation start.
        """
        # Create a conversation item to start the flow
        message = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": "[Chiamata iniziata]"
                    }
                ]
            }
        }

        await self._send_message(message)

        # Request a response
        await self._send_message({"type": "response.create"})

        logger.info(f"Consent prompt sent for call {self.call_id}")

    async def start_interview(self) -> None:
        """
        Start the actual interview after consent is received.
        """
        self.consent_given = True

        # The AI will continue automatically based on the system prompt
        logger.info(f"Interview started for call {self.call_id}")

    async def send_decline_message(self) -> None:
        """
        Send a goodbye message when consent is declined.
        """
        message = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Capisco. Grazie per il suo tempo. Arrivederci."
                    }
                ]
            }
        }

        await self._send_message(message)
        await self._send_message({"type": "response.create"})

    async def send_cancellation_message(self) -> None:
        """
        Send goodbye message for DTMF cancellation.
        """
        message = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Operazione completata. La trascrizione di questa chiamata verrà eliminata. Arrivederci."
                    }
                ]
            }
        }

        await self._send_message(message)
        await self._send_message({"type": "response.create"})

    async def _check_voice_cancellation(self, transcript: str) -> None:
        """
        Check if user said a cancellation phrase (fallback for DTMF).
        Triggers cancellation if user says "cancella", "elimina i miei dati", etc.
        """
        if not transcript or self._dtmf_cancelled:
            return

        # Normalize text
        text_lower = transcript.lower().strip()

        # Cancellation phrases in Italian
        cancel_phrases = [
            "cancella",
            "elimina",
            "cancella i miei dati",
            "elimina i miei dati",
            "voglio cancellare",
            "cancella tutto",
            "elimina tutto",
            "cancella la registrazione",
            "non voglio più",
            "annulla tutto",
        ]

        # Check if any cancellation phrase is in the transcript
        for phrase in cancel_phrases:
            if phrase in text_lower:
                logger.info(f"Voice cancellation detected: '{phrase}' in '{text_lower[:50]}...'")
                self._dtmf_cancelled = True
                await self.on_dtmf_cancel(self.call_id, self.openai_session_id)
                return

    async def send_error_message(self) -> None:
        """
        Send an apology message when an error occurs.
        """
        message = {
            "type": "conversation.item.create",
            "item": {
                "type": "message",
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": "Mi dispiace, si è verificato un problema tecnico. La preghiamo di richiamare più tardi. Arrivederci."
                    }
                ]
            }
        }

        await self._send_message(message)
        await self._send_message({"type": "response.create"})

    async def hangup(self) -> None:
        """
        Terminate the call gracefully.
        """
        # Send a session close event (if supported by API)
        # Otherwise just disconnect
        await self.disconnect()

    async def _timeout_watchdog(self) -> None:
        """
        Watchdog that enforces maximum call duration.
        Prevents stuck sessions from running indefinitely.
        """
        try:
            max_duration = self.settings.max_call_duration_seconds
            logger.info(f"Call {self.call_id} timeout watchdog started ({max_duration}s)")

            await asyncio.sleep(max_duration)

            if self.is_connected:
                logger.warning(
                    f"Call {self.call_id} exceeded maximum duration ({max_duration}s), "
                    "forcing hangup"
                )
                await self.send_error_message()
                await asyncio.sleep(3)
                await self.hangup()

        except asyncio.CancelledError:
            logger.debug(f"Timeout watchdog cancelled for call {self.call_id}")
        except Exception as e:
            logger.error(f"Timeout watchdog error for call {self.call_id}: {e}")

    async def _receive_loop(self) -> None:
        """
        Continuously receive and process messages from OpenAI.
        """
        try:
            async for message in self.ws:
                try:
                    data = json.loads(message)
                    if isinstance(data, str):
                        # Some events can arrive as JSON-encoded strings; try one more decode.
                        try:
                            data = json.loads(data)
                        except json.JSONDecodeError:
                            logger.warning(
                                f"Received non-JSON string message: {data[:200]}"
                            )
                            continue
                    if not isinstance(data, dict):
                        logger.warning(
                            f"Ignoring non-dict message: {type(data).__name__}"
                        )
                        continue
                    await self._handle_message(data)
                except json.JSONDecodeError as e:
                    logger.error(f"Invalid JSON received: {e}")
                except Exception as e:
                    logger.error(f"Error handling message: {e}")

        except asyncio.CancelledError:
            pass
        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket connection closed for call {self.call_id}")
        except Exception as e:
            logger.error(f"Receive loop error: {e}")
            await self.on_error(self.call_id, f"Receive error: {e}")
        finally:
            if not self._finalized:
                self.is_connected = False
                if self._output_transcript_buffer:
                    await self._persist_transcript(
                        "assistant",
                        "".join(self._output_transcript_buffer),
                    )
                    self._output_transcript_buffer = []
                if self._input_transcript_buffer:
                    await self._persist_transcript(
                        "user",
                        "".join(self._input_transcript_buffer),
                    )
                    self._input_transcript_buffer = []
                await self._mark_call_ended()
                self._finalized = True


    def _extract_transcript_text(self, data: dict) -> str:
        """
        Extract transcript text from various Realtime payload shapes.
        """
        if not data:
            return ""
        if data.get("transcript"):
            return data.get("transcript", "")
        if data.get("text"):
            return data.get("text", "")
        delta = data.get("delta")
        if isinstance(delta, dict):
            if delta.get("text"):
                return delta.get("text", "")
            if delta.get("transcript"):
                return delta.get("transcript", "")
        if isinstance(delta, str):
            return delta
        transcription = data.get("transcription") or {}
        if isinstance(transcription, dict) and transcription.get("text"):
            return transcription.get("text", "")
        item = data.get("item") or {}
        content = item.get("content") or []
        parts = []
        for part in content:
            if part.get("type") in ("text", "input_text"):
                parts.append(part.get("text", ""))
            elif part.get("type") == "input_audio" and part.get("transcript"):
                parts.append(part.get("transcript", ""))
        return "".join(parts)

    async def _handle_message(self, data: dict) -> None:
        """
        Handle incoming messages from OpenAI.
        """
        msg_type = data.get("type", "")

        # Log all messages for debugging (temporarily elevated to INFO)
        if "dtmf" in msg_type.lower() or msg_type.startswith("input"):
            logger.info(f"[WS DEBUG] Received potentially relevant: {msg_type}")
        else:
            logger.debug(f"Received: {msg_type}")

        # Handle different message types
        if msg_type == "error":
            error = data.get("error", {})
            logger.error(f"OpenAI error: {error}")
            await self.on_error(self.call_id, f"OpenAI error: {error.get('message')}")

        elif msg_type == "session.created":
            logger.info("Session created successfully")

        elif msg_type == "session.updated":
            logger.info("Session updated successfully")

        elif msg_type == "conversation.item.created":
            # Track transcript items
            item = data.get("item", {})
            await self._process_transcript_item(item)

        elif msg_type in ("response.output_audio_transcript.done", "response.audio_transcript.done"):
            # AI speech transcript completed
            transcript = self._extract_transcript_text(data)
            if not transcript and self._output_transcript_buffer:
                transcript = "".join(self._output_transcript_buffer)
                self._output_transcript_buffer = []
            logger.debug(f"AI said: {transcript[:100]}")
            await self._persist_transcript("assistant", transcript)
        elif msg_type in ("response.output_audio_transcript.delta", "response.audio_transcript.delta"):
            delta = self._extract_transcript_text(data)
            if delta:
                self._output_transcript_buffer.append(delta)

        elif msg_type in (
            "conversation.item.input_audio_transcription.completed",
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.segment",
            "input_audio_transcription.completed",
            "input_audio_transcription.segment",
            "input_audio_transcription.delta",
        ):
            # User speech transcript
            transcript = self._extract_transcript_text(data)
            if msg_type.endswith(".delta") and transcript:
                self._input_transcript_buffer.append(transcript)
                return
            if not transcript and self._input_transcript_buffer:
                transcript = "".join(self._input_transcript_buffer)
                self._input_transcript_buffer = []
            logger.debug(f"User said: {transcript[:100]}")
            await self._persist_transcript("user", transcript)

            # Check for voice-based cancellation (fallback for DTMF)
            if transcript and not self._dtmf_cancelled:
                await self._check_voice_cancellation(transcript)

        elif msg_type == "input_audio_buffer.speech_started":
            logger.debug("User started speaking")

        elif msg_type == "input_audio_buffer.speech_stopped":
            logger.debug("User stopped speaking")

        elif msg_type in (
            "input_audio_buffer.dtmf_event_received",
            "input.dtmf",
            "realtime.dtmf",
            "dtmf",
            "input_audio_buffer.dtmf",
        ):
            # Enhanced logging for DTMF debugging
            logger.info(f"[WS DTMF DEBUG] Received DTMF event: msg_type={msg_type}, data={data}")

            digit = data.get("digit")
            if digit is None:
                digit = (data.get("dtmf") or {}).get("digit")
            if digit is None:
                # 'event' can be the digit directly (string) or an object with 'digit' key
                event_val = data.get("event")
                if isinstance(event_val, str):
                    digit = event_val  # e.g., {'event': '9'}
                elif isinstance(event_val, dict):
                    digit = event_val.get("digit")
            if digit is None:
                digit = (data.get("input") or {}).get("digit")

            logger.info(f"[WS DTMF DEBUG] Extracted digit={digit}")

            if digit is not None:
                digit_str = str(digit)
                logger.info(f"DTMF received via WebSocket: {digit_str} for call {self.call_id}")
                if (
                    digit_str == self.settings.dtmf_cancel_key
                    and not self._dtmf_cancelled
                ):
                    logger.info(f"[WS DTMF DEBUG] Cancel key detected! Triggering cancellation...")
                    self._dtmf_cancelled = True
                    await self.on_dtmf_cancel(self.call_id, self.openai_session_id)

        elif msg_type == "response.done":
            # AI finished responding
            pass

    async def _process_transcript_item(self, item: dict) -> None:
        """
        Process and buffer transcript items.
        """
        role = item.get("role", "")
        content = item.get("content", [])

        # Extract text from content
        text = ""
        for part in content:
            if part.get("type") == "text":
                text += part.get("text", "")
            elif part.get("type") == "input_text":
                text += part.get("text", "")
            elif part.get("type") == "input_audio" and part.get("transcript"):
                text += part.get("transcript", "")

        if text:
            self.transcript_buffer.append({
                "role": role,
                "content": text,
                "timestamp": asyncio.get_event_loop().time()
            })
            await self._persist_transcript(role or "assistant", text)

    async def _persist_transcript(self, role: str, text: str) -> None:
        """
        Persist a transcript item to the database and check consent if needed.
        """
        if not text:
            return

        db = get_database()
        try:
            await db.execute(
                """
                INSERT INTO transcripts (call_id, role, content, timestamp)
                VALUES (:call_id, :role, :content, :timestamp)
                """,
                {
                    "call_id": str(self.call_id),
                    "role": role,
                    "content": text,
                    "timestamp": datetime.utcnow(),
                },
            )
        except Exception as e:
            logger.error(f"Failed to persist transcript for call {self.call_id}: {e}")

        if role == "user":
            await self._check_for_consent(text)

    async def _check_for_consent(self, transcript: str) -> None:
        """
        Check if the user's response indicates consent.
        """
        if self.consent_given:
            return  # Already handled

        transcript_lower = transcript.lower()

        # Positive consent keywords
        positive_keywords = ["sì", "si", "accetto", "va bene", "ok", "okay", "d'accordo", "certo"]
        # Negative keywords
        negative_keywords = ["no", "non accetto", "rifiuto", "negativo"]

        # Check for positive consent
        if any(keyword in transcript_lower for keyword in positive_keywords):
            logger.info(f"Consent detected (positive) for call {self.call_id}")
            await self.on_consent_received(self.call_id, True)

        # Check for negative consent
        elif any(keyword in transcript_lower for keyword in negative_keywords):
            logger.info(f"Consent detected (negative) for call {self.call_id}")
            await self.on_consent_received(self.call_id, False)

    async def _send_message(self, message: dict) -> None:
        """
        Send a message to OpenAI via WebSocket.
        """
        if not self.is_connected or not self.ws:
            logger.warning("Cannot send message: WebSocket not connected")
            return

        try:
            await self.ws.send(json.dumps(message))
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise


    async def _mark_call_ended(self) -> None:
        """
        Mark call as ended. Duration is automatically calculated by database.
        Idempotent - safe to call multiple times.
        """
        db = get_database()

        try:
            # Fetch current state
            call = await db.fetch_one(
                """
                SELECT id, ended_at, status
                FROM calls
                WHERE id = :id
                """,
                {"id": str(self.call_id)},
            )

            if not call:
                logger.warning(f"Call {self.call_id} not found in database")
                return

            # Calculate end time (use existing if already set)
            ended_at = call["ended_at"] or datetime.utcnow()

            # Determine final status
            current_status = call["status"]
            if current_status in ("in_progress", "consented"):
                new_status = "completed"
            elif current_status == "pending_consent":
                new_status = "declined"
            else:
                new_status = current_status  # Preserve cancelled/declined/failed

            # Update with idempotent logic - don't overwrite existing ended_at
            # Note: duration_seconds is automatically calculated by database
            await db.execute(
                """
                UPDATE calls
                SET ended_at = COALESCE(ended_at, :ended_at),
                    status = :status
                WHERE id = :id
                """,
                {
                    "id": str(self.call_id),
                    "ended_at": ended_at,
                    "status": new_status,
                },
            )

            logger.info(
                f"Call {self.call_id} finalized: status={new_status}, "
                f"ended_at={ended_at.isoformat()}"
            )

        except Exception as e:
            logger.error(
                f"CRITICAL: Failed to mark call {self.call_id} as ended: {e}",
                exc_info=True,
            )
            # Attempt fallback update without transaction lock
            try:
                await db.execute(
                    """
                    UPDATE calls
                    SET ended_at = COALESCE(ended_at, :ended_at),
                        status = 'declined'
                    WHERE id = :id
                    """,
                    {
                        "id": str(self.call_id),
                        "ended_at": datetime.utcnow(),
                    },
                )
                logger.warning(f"Fallback update succeeded for call {self.call_id}")
            except Exception as fallback_error:
                logger.error(
                    f"CRITICAL: Fallback update failed for call {self.call_id}: {fallback_error}"
                )

    def get_transcript(self) -> list:
        """
        Get the current transcript buffer.
        """
        return self.transcript_buffer.copy()
