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

GESTIONE CANCELLAZIONE DATI:
- Se l'utente chiede di cancellare i dati o revoca il consenso, rispondi con la frase ESATTA:
"{cancel_phrase}"
- Dopo questa frase, non fare altre domande e termina la conversazione.

DOPO IL CONSENSO, conduci il colloquio:

1. Presentati brevemente
2. Chiedi: "Per quale ruolo ti stai candidando?"
   - Approfondisci il ruolo (responsabilità, settore, contesto) con domande di follow-up
3. Chiedi: "Raccontami un'esperienza lavorativa di cui vai particolarmente fiero"
   - Approfondisci risultati, impatto, strumenti usati, dimensione del team
4. Chiedi: "Quali sono le tue principali competenze tecniche?"
   - Approfondisci esempi concreti di utilizzo delle competenze
   - DOPO aver raccolto le skills, chiedi: "Puoi elencare le posizioni lavorative passate (ruolo, azienda, periodo)?"
5. Chiedi: "Come ti trovi a lavorare in squadra? Fammi un esempio"
   - Approfondisci il contesto e il tuo contributo
6. Chiedi: "Disponibilità: puoi lavorare in trasferta o su turni se necessario?"
   - Approfondisci eventuali limiti o preferenze

LOGICA DI APPROFONDIMENTO:
- Dopo ogni risposta, fai domande di approfondimento se la risposta è breve o poco informativa.
- NON fare più di 5 domande di approfondimento per ciascun punto.
- Fai una domanda alla volta e passa al punto successivo quando hai raccolto abbastanza.

CHIUSURA:
- Prima di chiudere la chiamata, chiedi sempre: nome e cognome, numero di telefono, email.
- Se non capisci bene o manca una risposta, chiedi di ripetere UNA SOLA volta; se resta poco chiaro, segnala che l'informazione manca e vai avanti.
- Concludi sempre con la frase ESATTA: "{goodbye_phrase}"

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
        on_standard_hangup: Callable[[UUID, str], Awaitable[None]],
    ):
        self.call_id = call_id
        self.openai_session_id = openai_session_id
        self.on_consent_received = on_consent_received
        self.on_interview_complete = on_interview_complete
        self.on_error = on_error
        self.on_dtmf_cancel = on_dtmf_cancel
        self.on_standard_hangup = on_standard_hangup

        self.settings = get_settings()
        self.ws: Optional[WebSocketClientProtocol] = None
        self.is_connected = False
        self.consent_given = False
        self.transcript_buffer = []
        self._output_transcript_buffer: list[str] = []
        self._input_transcript_buffer: list[str] = []
        self._finalized = False
        self._dtmf_cancelled = False
        self._skip_transcript_save = False  # Set to True during cancellation to prevent saving
        self._cancel_after_output_stop = False
        self._assistant_cancel_confirmed = False
        self._hangup_after_output_stop = False
        self._assistant_goodbye_confirmed = False

        # Task management
        self._receive_task: Optional[asyncio.Task] = None
        self._heartbeat_task: Optional[asyncio.Task] = None
        self._timeout_task: Optional[asyncio.Task] = None
        self._cancel_tts_event: Optional[asyncio.Event] = None
        self._cancel_tts_waiting = False

    def mark_cancelled(self) -> None:
        """Mark the session as cancelled to stop transcript saves and avoid re-entrance."""
        self._dtmf_cancelled = True
        self._skip_transcript_save = True

    def is_cancelled(self) -> bool:
        """Check if this session has been cancelled."""
        return self._dtmf_cancelled

    def has_assistant_cancel_confirmed(self) -> bool:
        """Check if the assistant already confirmed cancellation to the caller."""
        return self._assistant_cancel_confirmed

    def _normalize_text(self, text: str) -> str:
        """Normalize text for simple keyword matching."""
        lowered = text.lower().strip()
        return "".join(ch if ch.isalnum() or ch.isspace() else " " for ch in lowered)

    def _is_cancel_confirmation_from_ai(self, transcript: str) -> bool:
        """
        Return True if the assistant output matches the standard cancellation phrase.
        """
        if not transcript:
            return False
        message_text = (self.settings.cancellation_message_text or "").strip()
        if not message_text:
            message_text = "Va bene, procedo con la cancellazione della telefonata."
        normalized_transcript = self._normalize_text(transcript)
        normalized_phrase = self._normalize_text(message_text)
        return normalized_phrase and normalized_phrase in normalized_transcript

    def _is_standard_goodbye_from_ai(self, transcript: str) -> bool:
        """
        Return True if the assistant output matches the standard goodbye phrase.
        """
        if not transcript:
            return False
        message_text = (self.settings.goodbye_message_text or "").strip()
        if not message_text:
            message_text = "Le auguro una buona giornata! Arrivederci."
        normalized_transcript = self._normalize_text(transcript)
        normalized_phrase = self._normalize_text(message_text)
        return normalized_phrase and normalized_phrase in normalized_transcript

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
        # Skip if cancellation was triggered (transcripts will be deleted anyway)
        if not self._skip_transcript_save:
            try:
                if self._output_transcript_buffer:
                    await self._persist_transcript("assistant", "".join(self._output_transcript_buffer))
                    self._output_transcript_buffer = []
                if self._input_transcript_buffer:
                    await self._persist_transcript("user", "".join(self._input_transcript_buffer))
                    self._input_transcript_buffer = []
            except Exception as e:
                logger.error(f"Error flushing transcripts for call {self.call_id}: {e}")
        else:
            logger.info(f"Skipping transcript flush for cancelled call {self.call_id}")
            self._output_transcript_buffer = []
            self._input_transcript_buffer = []

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
        cancel_phrase = (self.settings.cancellation_message_text or "").strip()
        if not cancel_phrase:
            cancel_phrase = "Va bene, procedo con la cancellazione della telefonata."
        goodbye_phrase = (self.settings.goodbye_message_text or "").strip()
        if not goodbye_phrase:
            goodbye_phrase = "Le auguro una buona giornata! Arrivederci."
        instructions = DEFAULT_PROMPT_A.format(
            cancel_phrase=cancel_phrase,
            goodbye_phrase=goodbye_phrase,
        )

        # SIP calls are configured via the accept() request; keep session.update minimal.
        if is_sip_call:
            session_config = {
                "type": "realtime",
                "instructions": instructions,
            }
        else:
            session_config = {
                "type": "realtime",
                "instructions": instructions,
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
                        "type": "output_text",
                        "text": "Capisco. Grazie per il suo tempo. Arrivederci."
                    }
                ]
            }
        }

        await self._send_message(message)
        await self._send_message({"type": "response.create"})

    async def interrupt_ai_and_clear_buffers(self) -> None:
        """
        Interrupt any ongoing AI response and clear audio buffers.
        This prevents the AI from responding to DTMF or continuing to speak
        when we want to send our own cancellation message.
        """
        logger.info(f"Interrupting AI and clearing buffers for call {self.call_id}")

        try:
            # Cancel any ongoing response from the AI
            await self._send_message({"type": "response.cancel"})

            # Clear the input audio buffer to prevent further processing
            await self._send_message({"type": "input_audio_buffer.clear"})
            # Clear any pending output audio so TTS stops immediately
            await self._send_message({"type": "output_audio_buffer.clear"})

            # Small delay to ensure commands are processed by OpenAI
            await asyncio.sleep(0.2)

            logger.info(f"AI interrupted and buffers cleared for call {self.call_id}")
        except Exception as e:
            logger.error(f"Error interrupting AI: {e}")

    async def send_cancellation_message(self) -> None:
        """
        Send goodbye message for DTMF cancellation.
        """
        await self.send_cancellation_tts_message()

    async def send_cancellation_tts_message(self) -> None:
        """
        Speak a preconfigured cancellation message without continuing the dialog.
        Uses a dedicated response with isolated context.
        """
        if not self.is_connected or not self.ws:
            logger.warning("Cannot send cancellation TTS: WebSocket not connected")
            return

        message_text = (self.settings.cancellation_confirmation_text or "").strip()
        if not message_text:
            message_text = "Cancellazione dei dati della telefonata eseguita."

        if self._cancel_tts_waiting:
            logger.debug("Cancellation TTS already in progress")
            return

        self._cancel_tts_waiting = True
        self._cancel_tts_event = asyncio.Event()

        response_payload = {
            "type": "response.create",
            "response": {
                "conversation": "none",
                "metadata": {"purpose": "cancellation_tts"},
                "instructions": (
                    "Ripeti esattamente la frase seguente senza aggiungere altro: "
                    f"\"{message_text}\""
                ),
                "input": [
                    {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": message_text,
                            }
                        ],
                    }
                ],
            },
        }

        await self._send_message(response_payload)

        try:
            await asyncio.wait_for(self._cancel_tts_event.wait(), timeout=6.0)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for cancellation TTS playback")
        finally:
            self._cancel_tts_waiting = False
            self._cancel_tts_event = None

    def _extract_single_digit(self, transcript: str) -> Optional[str]:
        """
        Extract a single digit if the transcript contains only that digit
        (optionally surrounded by whitespace/punctuation).
        """
        if not transcript:
            return None
        cleaned = transcript.strip()
        if not cleaned:
            return None
        if any(char.isalpha() for char in cleaned):
            return None
        digits = "".join(char for char in cleaned if char.isdigit())
        if len(digits) == 1:
            return digits
        return None

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
                        "type": "output_text",
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

    async def force_close_websocket(self) -> None:
        """
        Force close the WebSocket connection immediately.
        Used for DTMF cancellation from within receive loop.
        """
        logger.info(f"Force closing WebSocket for call {self.call_id}")

        # Set flag to prevent saving transcripts
        self.is_connected = False

        # Close WebSocket if still open
        if self.ws:
            try:
                if not self.ws.closed:
                    await self.ws.close(code=1000, reason="User cancelled")
                    logger.info(f"WebSocket force closed for call {self.call_id}")
                else:
                    logger.info(f"WebSocket already closed for call {self.call_id}")
            except Exception as e:
                logger.error(f"Error force closing WebSocket: {e}")
        else:
            logger.warning(f"No WebSocket to close for call {self.call_id}")

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
                # Only save transcripts if not cancelled (they will be deleted anyway)
                if not self._skip_transcript_save:
                    if self._output_transcript_buffer:
                        await self._persist_transcript(
                            "assistant",
                            "".join(self._output_transcript_buffer),
                        )
                    if self._input_transcript_buffer:
                        await self._persist_transcript(
                            "user",
                            "".join(self._input_transcript_buffer),
                        )
                else:
                    logger.info(f"Skipping transcript save in finally block for cancelled call {self.call_id}")
                self._output_transcript_buffer = []
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
            if part.get("type") in ("text", "input_text", "output_text"):
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
            error_code = error.get("code")
            if error_code == "response_cancel_not_active":
                logger.debug("Ignoring response_cancel_not_active error")
                return
            if self._dtmf_cancelled:
                logger.info(f"Ignoring error after cancellation: {error}")
                return
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
            if self._is_cancel_confirmation_from_ai(transcript):
                logger.info("Assistant confirmed cancellation; will hang up after audio stops")
                self._assistant_cancel_confirmed = True
                self._cancel_after_output_stop = True
            elif not self._dtmf_cancelled and self._is_standard_goodbye_from_ai(transcript):
                logger.info("Assistant spoke standard goodbye; will hang up after audio stops")
                self._assistant_goodbye_confirmed = True
                self._hangup_after_output_stop = True
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
            if self._dtmf_cancelled:
                logger.debug("Skipping user transcript after cancellation")
                return
            digit = self._extract_single_digit(transcript)
            if (
                digit
                and digit == self.settings.dtmf_cancel_key
                and not self._dtmf_cancelled
            ):
                logger.info(
                    f"DTMF cancel detected via transcription: {digit} for call {self.call_id}"
                )
                self.mark_cancelled()
                await self.interrupt_ai_and_clear_buffers()
                await self.on_dtmf_cancel(self.call_id, self.openai_session_id)
                return
            logger.debug(f"User said: {transcript[:100]}")
            await self._persist_transcript("user", transcript)

        elif msg_type == "input_audio_buffer.speech_started":
            logger.debug("User started speaking")

        elif msg_type == "input_audio_buffer.speech_stopped":
            logger.debug("User stopped speaking")

        elif msg_type == "output_audio_buffer.stopped":
            logger.debug("Output audio buffer stopped")
            if self._cancel_after_output_stop and not self._dtmf_cancelled:
                self._cancel_after_output_stop = False
                self.mark_cancelled()
                await self.on_dtmf_cancel(self.call_id, self.openai_session_id)
            elif self._hangup_after_output_stop and not self._dtmf_cancelled:
                self._hangup_after_output_stop = False
                await self.on_standard_hangup(self.call_id, self.openai_session_id)
            if self._cancel_tts_waiting and self._cancel_tts_event:
                self._cancel_tts_event.set()

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
                    self.mark_cancelled()
                    await self.interrupt_ai_and_clear_buffers()
                    await self.on_dtmf_cancel(self.call_id, self.openai_session_id)

        elif msg_type == "response.done":
            if self._cancel_tts_waiting and self._cancel_tts_event:
                response = data.get("response") or {}
                metadata = response.get("metadata") or {}
                if metadata.get("purpose") == "cancellation_tts":
                    self._cancel_tts_event.set()

    async def _process_transcript_item(self, item: dict) -> None:
        """
        Process and buffer transcript items.
        """
        if self._dtmf_cancelled:
            logger.debug("Skipping transcript item after cancellation")
            return
        role = item.get("role", "")
        content = item.get("content", [])

        # Extract text from content
        text = ""
        for part in content:
            if part.get("type") == "text":
                text += part.get("text", "")
            elif part.get("type") == "input_text":
                text += part.get("text", "")
            elif part.get("type") == "output_text":
                text += part.get("text", "")
            elif part.get("type") == "input_audio" and part.get("transcript"):
                text += part.get("transcript", "")

        if text:
            if role == "user":
                digit = self._extract_single_digit(text)
                if (
                    digit
                    and digit == self.settings.dtmf_cancel_key
                    and not self._dtmf_cancelled
                ):
                    logger.info(
                        f"DTMF cancel detected via transcript item: {digit} for call {self.call_id}"
                    )
                    self.mark_cancelled()
                    await self.interrupt_ai_and_clear_buffers()
                    await self.on_dtmf_cancel(self.call_id, self.openai_session_id)
                    return
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

        # Skip saving if cancellation was triggered (transcripts will be deleted)
        if self._skip_transcript_save:
            logger.debug(f"Skipping transcript save for cancelled call {self.call_id}")
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
