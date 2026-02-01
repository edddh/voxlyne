"""
Ascolta - Call Manager Service
Manages call lifecycle and OpenAI Realtime session orchestration
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Optional
from uuid import UUID

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

    async def handle_cancellation(
        self,
        call_id: UUID,
        session_id: str,
    ) -> None:
        """
        Handle DTMF cancellation request.
        This triggers immediate call termination and transcript deletion.

        IMPORTANT: This is called from within the receive loop, so we CANNOT call
        hangup() directly (it would cancel the current task). Instead, we close
        the WebSocket directly and let the receive loop terminate naturally.
        """
        logger.info(f"Processing cancellation for call {call_id}")

        try:
            db = get_database()

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

            if session:
                # Send goodbye message
                try:
                    await session.send_cancellation_message()
                    await asyncio.sleep(2)  # Wait for message to play
                except Exception as e:
                    logger.warning(f"Error sending cancellation message: {e}")

                # Close the WebSocket directly (without cancelling tasks)
                # This will cause the receive loop to terminate naturally with ConnectionClosed
                if session.ws:
                    try:
                        await session.ws.close()
                        logger.info(f"WebSocket closed for call {call_id}")
                    except Exception as e:
                        logger.warning(f"Error closing WebSocket: {e}")

                # Wait for receive loop to terminate gracefully
                if session._receive_task:
                    try:
                        await asyncio.wait_for(session._receive_task, timeout=3.0)
                        logger.info(f"Receive task completed for call {call_id}")
                    except asyncio.TimeoutError:
                        logger.warning(f"Receive task did not complete within timeout for call {call_id}")
                    except asyncio.CancelledError:
                        logger.debug(f"Receive task was cancelled for call {call_id}")
                    except Exception as e:
                        logger.warning(f"Error waiting for receive task: {e}")

            # Delete transcripts only (keep call record)
            await self.gdpr_controller.delete_transcripts(call_id)
            logger.info(f"Transcripts deleted for call {call_id}")

            # Clean up session now that receive loop has terminated
            await self.end_session(call_id)

            logger.info(f"Cancellation completed for call {call_id}")

        except Exception as e:
            logger.error(f"Cancellation error for call {call_id}: {e}")
            # Still try to delete transcripts even if there was an error
            try:
                await self.gdpr_controller.delete_transcripts(call_id)
                logger.info(f"Transcripts deleted after error for call {call_id}")
            except Exception as delete_error:
                logger.error(f"CRITICAL: Failed to delete transcripts: {delete_error}")

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
        Updates call status and triggers post-processing (in M2).
        """
        logger.info(f"Interview complete for call {call_id}")

        db = get_database()

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

        # TODO (M2): Trigger post-processing (JSON + PDF generation)

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
        duration = None

        if finalize:
            ended_at = datetime.utcnow()
            started_at = await db.fetch_val(
                "SELECT started_at FROM calls WHERE id = :id",
                {"id": str(call_id)},
            )
            if started_at:
                duration = int((ended_at - started_at).total_seconds())

        await db.execute(
            """
            UPDATE calls
            SET status = 'declined',
                ended_at = COALESCE(:ended_at, ended_at),
                duration_seconds = COALESCE(:duration, duration_seconds)
            WHERE id = :id
            """,
            {
                "id": str(call_id),
                "ended_at": ended_at,
                "duration": duration,
            }
        )

        logger.warning(f"Call {call_id} marked as failed: {reason}")

    def get_active_call_count(self) -> int:
        """Get the number of currently active calls."""
        return len(self.active_sessions)

    def is_call_active(self, call_id: UUID) -> bool:
        """Check if a call is currently active."""
        return call_id in self.active_sessions
