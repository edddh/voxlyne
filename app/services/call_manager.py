"""
Ascolta - Call Manager Service
Manages call lifecycle and OpenAI Realtime session orchestration
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional
from uuid import UUID

import httpx

from app.config import get_settings
from app.database.db import get_database
from app.models.schemas import CallStatus
from app.services.gdpr_controller import GDPRController
from app.services.realtime_session import RealtimeSession

logger = logging.getLogger(__name__)


class CallManager:
    """
    Manages active calls and their associated Realtime sessions.

    Responsibilities:
    - Track active calls
    - Manage OpenAI Realtime WebSocket sessions
    - Handle consent flow
    - Process DTMF cancellation
    - Coordinate with GDPR controller
    """

    def __init__(self):
        self.active_sessions: Dict[UUID, RealtimeSession] = {}
        self.settings = get_settings()
        self.gdpr_controller = GDPRController()
        self._post_processing_inflight: set[UUID] = set()

    async def start_session(
        self,
        call_id: UUID,
        session_id: str,
    ) -> None:
        """
        Start a new call session.
        Initializes the Realtime session and begins the consent flow.
        """
        logger.info(f"Starting session for call {call_id}")

        try:
            # Create Realtime session
            session = RealtimeSession(
                call_id=call_id,
                openai_session_id=session_id,
                on_consent_received=self._handle_consent,
                on_interview_complete=self._handle_interview_complete,
                on_error=self._handle_session_error,
                on_dtmf_cancel=self.handle_cancellation,
                on_standard_hangup=self.handle_standard_hangup,
            )

            # Store session
            self.active_sessions[call_id] = session

            # Connect and start the conversation
            await session.connect()

            # Send initial consent prompt
            await session.send_consent_prompt()

            logger.info(f"Session started for call {call_id}")

        except Exception as e:
            logger.error(f"Failed to start session for call {call_id}: {e}")
            await self._mark_call_failed(call_id, str(e))

    async def end_session(self, call_id: UUID) -> None:
        """
        End a call session and clean up resources.
        """
        logger.info(f"Ending session for call {call_id}")

        session = self.active_sessions.pop(call_id, None)
        if session:
            await session.disconnect()

        logger.info(f"Session ended for call {call_id}")

    async def _delayed_cleanup(self, call_id: UUID) -> None:
        """
        Clean up session after a delay to allow receive loop to terminate.
        Used after DTMF cancellation.
        """
        try:
            # Wait for receive loop to finish
            await asyncio.sleep(2)

            # Remove session from active sessions
            session = self.active_sessions.pop(call_id, None)
            if session:
                logger.info(f"Delayed cleanup: removed session for call {call_id}")
            else:
                logger.debug(f"Delayed cleanup: session already removed for call {call_id}")

        except Exception as e:
            logger.error(f"Error in delayed cleanup for call {call_id}: {e}")

    async def _hangup_sip_call(self, openai_session_id: str) -> None:
        """
        Terminate a SIP call using OpenAI Realtime API hangup endpoint.
        See: https://platform.openai.com/docs/api-reference/realtime-calls
        """
        if not openai_session_id or not openai_session_id.startswith("rtc_"):
            logger.warning(f"Invalid OpenAI session ID for hangup: {openai_session_id}")
            return

        try:
            url = f"https://api.openai.com/v1/realtime/calls/{openai_session_id}/hangup"
            headers = {
                "Authorization": f"Bearer {self.settings.openai_api_key}",
                "Content-Type": "application/json",
            }

            logger.info(f"Sending SIP hangup request for session {openai_session_id}")

            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, headers=headers)

                if response.status_code == 200:
                    logger.info(f"SIP call hangup successful for session {openai_session_id}")
                else:
                    logger.warning(
                        f"SIP hangup returned {response.status_code}: {response.text}"
                    )

        except httpx.TimeoutException:
            logger.error(f"Timeout calling OpenAI hangup API for session {openai_session_id}")
        except Exception as e:
            logger.error(f"Error calling OpenAI hangup API: {e}")

    async def handle_cancellation(
        self,
        call_id: UUID,
        session_id: str,
    ) -> None:
        """
        Handle DTMF cancellation request.
        This triggers immediate call termination and transcript deletion.

        IMPORTANT: This is called from within the receive loop, so we CANNOT call
        hangup() directly (it would cancel the current task). Instead, we trigger
        SIP hangup and let the receive loop terminate naturally.
        """
        logger.info(f"Processing cancellation for call {call_id}")

        try:
            db = get_database()

            # If cancellation came from webhook (no WS DTMF), stop any ongoing response
            session = self.active_sessions.get(call_id)
            if session and not session.is_cancelled():
                try:
                    session.mark_cancelled()
                    await session.interrupt_ai_and_clear_buffers()
                except Exception as e:
                    logger.warning(f"Error interrupting AI: {e}")

            # Mark the call as declined to preserve the record
            await db.execute(
                """
                UPDATE calls
                SET status = :status
                WHERE id = :id
                """,
                {
                    "id": str(call_id),
                    "status": CallStatus.DECLINED.value,
                },
            )

            # Get the session
            session = self.active_sessions.get(call_id)

            # Delete transcripts immediately (keep call record)
            await self.gdpr_controller.delete_transcripts(call_id)
            logger.info(f"Transcripts deleted for call {call_id}")

            # Get the session for cleanup
            session = self.active_sessions.get(call_id)

            if session:
                # Play cancellation TTS message before hangup (no AI dialog)
                try:
                    logger.info(f"Playing cancellation TTS message for call {call_id}")
                    await session.send_cancellation_tts_message()
                except Exception as e:
                    logger.warning(f"Error playing cancellation TTS message: {e}")

                # Now terminate the SIP call using OpenAI API
                try:
                    await self._hangup_sip_call(session_id)
                except Exception as e:
                    logger.error(f"Error hanging up SIP call: {e}")

                # The hangup API will close the SIP call and WebSocket
                # We don't force close the WebSocket here to avoid interrupting the hangup

                # Schedule cleanup in background (can't await receive_task from inside it)
                asyncio.create_task(self._delayed_cleanup(call_id))
            else:
                logger.warning(f"No active session found for call {call_id}")

            logger.info(f"Cancellation processing completed for call {call_id}")

        except Exception as e:
            logger.error(f"Cancellation error for call {call_id}: {e}")
            # Still try to delete transcripts even if there was an error
            try:
                await self.gdpr_controller.delete_transcripts(call_id)
                logger.info(f"Transcripts deleted after error for call {call_id}")
            except Exception as delete_error:
                logger.error(f"CRITICAL: Failed to delete transcripts: {delete_error}")

    async def handle_standard_hangup(
        self,
        call_id: UUID,
        session_id: str,
    ) -> None:
        """
        Handle standard AI goodbye by hanging up the SIP call.
        Also triggers post-processing (JSON extraction, PDF, email).
        """
        logger.info(f"Processing standard hangup for call {call_id}")

        # First, mark interview as complete and trigger post-processing
        await self._handle_interview_complete(call_id)

        # Then hang up the SIP call
        try:
            await self._hangup_sip_call(session_id)
        except Exception as e:
            logger.error(f"Error hanging up SIP call: {e}")

        # Schedule cleanup in background (can't await receive_task from inside it)
        asyncio.create_task(self._delayed_cleanup(call_id))

    async def _handle_consent(
        self,
        call_id: UUID,
        consent_given: bool,
    ) -> None:
        """
        Handle consent response from the user.
        """
        db = get_database()

        if consent_given:
            logger.info(f"Consent received for call {call_id}")

            # Update call status
            await db.execute(
                """
                UPDATE calls
                SET consent_given = TRUE,
                    consent_timestamp = :timestamp,
                    status = :status
                WHERE id = :id
                """,
                {
                    "id": str(call_id),
                    "timestamp": datetime.utcnow(),
                    "status": CallStatus.CONSENTED.value,
                }
            )

            # Start the interview
            session = self.active_sessions.get(call_id)
            if session:
                await session.start_interview()

        else:
            logger.info(f"Consent declined for call {call_id}")

            # Update call status only; end time is set on disconnect.
            await db.execute(
                """
                UPDATE calls
                SET status = :status
                WHERE id = :id
                """,
                {
                    "id": str(call_id),
                    "status": CallStatus.DECLINED.value,
                }
            )

            # Send goodbye and hang up
            session = self.active_sessions.get(call_id)
            if session:
                await session.send_decline_message()
                await asyncio.sleep(2)
                await session.hangup()

            # Clean up session
            await self.end_session(call_id)

    async def _handle_interview_complete(self, call_id: UUID) -> None:
        """
        Handle interview completion.
        Updates call status and triggers post-processing.
        """
        logger.info(f"Interview complete for call {call_id}")

        db = get_database()

        # Guard against duplicate post-processing runs
        if call_id in self._post_processing_inflight:
            logger.info(f"Post-processing already in flight for call {call_id}")
            return

        call = await db.fetch_one(
            "SELECT status FROM calls WHERE id = :id",
            {"id": str(call_id)},
        )
        if not call:
            logger.warning(f"Call {call_id} not found during completion handling")
            return
        current_status = call["status"]
        if current_status in (
            CallStatus.PROCESSING.value,
            CallStatus.PROCESSED.value,
        ):
            logger.info(
                f"Skipping post-processing for call {call_id}: status={current_status}"
            )
            return
        if current_status not in (
            CallStatus.IN_PROGRESS.value,
            CallStatus.CONSENTED.value,
            CallStatus.COMPLETED.value,
        ):
            logger.info(
                f"Skipping post-processing for call {call_id}: status={current_status}"
            )
            return

        await db.execute(
            """
            UPDATE calls
            SET status = :status
            WHERE id = :id
            """,
            {
                "id": str(call_id),
                "status": CallStatus.COMPLETED.value,
            }
        )

        self._post_processing_inflight.add(call_id)

        # Schedule post-processing in background (JSON extraction, PDF, email)
        asyncio.create_task(self._post_process_interview(call_id))

    async def _post_process_interview(self, call_id: UUID) -> None:
        """
        Post-process completed interview:
        1. Extract JSON from transcript (GPT-4)
        2. Generate PDF report
        3. Send email with PDF attachment
        """
        try:
            logger.info(f"Starting post-processing for call {call_id}")

            # 1. Extract JSON from transcript
            from app.services.post_processor import PostProcessor
            post_processor = PostProcessor()
            json_data = await post_processor.process_call(call_id)
            logger.info(f"JSON extraction completed for call {call_id}")

            # 2. Generate PDF
            from app.services.pdf_generator import PDFGenerator
            pdf_generator = PDFGenerator()
            await pdf_generator.generate_and_upload_pdf(call_id, json_data)
            logger.info(f"PDF generated for call {call_id}")

            # 3. Send email with PDF attachment (if enabled)
            from app.services.email_service import EmailService
            email_service = EmailService()

            if email_service.is_enabled():
                try:
                    # Download PDF bytes for attachment
                    pdf_bytes = await pdf_generator.download_pdf(call_id)

                    # Fetch call metadata for email body
                    db = get_database()
                    call_metadata = await db.fetch_one(
                        """
                        SELECT id, started_at, duration_seconds
                        FROM calls WHERE id = :id
                        """,
                        {"id": str(call_id)}
                    )

                    await email_service.send_candidate_report(
                        pdf_bytes=pdf_bytes,
                        json_data=json_data,
                        call_metadata=dict(call_metadata) if call_metadata else None,
                    )
                    logger.info(f"Email sent for call {call_id}")
                except Exception as email_error:
                    logger.error(f"Failed to send email for call {call_id}: {email_error}")
            else:
                logger.debug(f"Email not enabled, skipping for call {call_id}")

            logger.info(f"Post-processing completed for call {call_id}")

        except Exception as e:
            logger.error(f"Post-processing failed for call {call_id}: {e}", exc_info=True)
        finally:
            self._post_processing_inflight.discard(call_id)

    async def _handle_session_error(
        self,
        call_id: UUID,
        error: str,
    ) -> None:
        """
        Handle session errors.
        Sends an apology message and terminates the call gracefully.
        """
        logger.error(f"Session error for call {call_id}: {error}")

        session = self.active_sessions.get(call_id)
        # If we have a live session, let disconnect finalize end time/duration.
        await self._mark_call_failed(call_id, error, finalize=not bool(session))

        if session:
            try:
                await session.send_error_message()
                await asyncio.sleep(3)
                await session.hangup()
            except Exception as e:
                logger.error(f"Failed to send error message: {e}")

        await self.end_session(call_id)

    async def _mark_call_failed(
        self,
        call_id: UUID,
        reason: str,
        finalize: bool = True,
    ) -> None:
        """
        Mark a call as failed in the database.
        """
        db = get_database()
        ended_at = None

        if finalize:
            ended_at = datetime.utcnow()

        await db.execute(
            """
            UPDATE calls
            SET status = 'declined',
                ended_at = COALESCE(:ended_at, ended_at)
            WHERE id = :id
            """,
            {
                "id": str(call_id),
                "ended_at": ended_at,
            }
        )

        logger.warning(f"Call {call_id} marked as failed: {reason}")

    def get_active_call_count(self) -> int:
        """Get the number of currently active calls."""
        return len(self.active_sessions)

    def is_call_active(self, call_id: UUID) -> bool:
        """Check if a call is currently active."""
        return call_id in self.active_sessions
