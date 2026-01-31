"""
Session Cleanup Service
Detects and cleans up stuck/orphaned sessions
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

from app.config import get_settings
from app.database.db import get_database

logger = logging.getLogger(__name__)


class SessionCleanup:
    """
    Background service that cleans up stuck sessions.

    Runs periodically to find and fix:
    - Sessions without ended_at after max_call_duration
    - Sessions with ended_at but no duration_seconds
    - Sessions stuck in 'consented' or 'in_progress' status
    """

    def __init__(self):
        self.settings = get_settings()
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Start the cleanup service."""
        if self._running:
            logger.warning("Cleanup service already running")
            return

        self._running = True
        self._task = asyncio.create_task(self._cleanup_loop())
        logger.info("Session cleanup service started")

    async def stop(self) -> None:
        """Stop the cleanup service."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Session cleanup service stopped")

    async def _cleanup_loop(self) -> None:
        """Main cleanup loop - runs every 5 minutes."""
        while self._running:
            try:
                await self._cleanup_stuck_sessions()
                await asyncio.sleep(300)  # 5 minutes
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Wait 1 minute on error

    async def _cleanup_stuck_sessions(self) -> None:
        """Find and clean up stuck sessions."""
        db = get_database()
        max_duration = self.settings.max_call_duration_seconds
        cutoff_time = datetime.utcnow() - timedelta(seconds=max_duration + 300)

        try:
            # Find stuck sessions (started > max_duration ago, no ended_at)
            stuck_calls = await db.fetch_all(
                """
                SELECT id, started_at, status
                FROM calls
                WHERE ended_at IS NULL
                  AND started_at < :cutoff
                  AND status NOT IN ('cancelled', 'declined', 'completed')
                ORDER BY started_at
                """,
                {"cutoff": cutoff_time}
            )

            if stuck_calls:
                logger.warning(f"Found {len(stuck_calls)} stuck sessions to clean up")

                for call in stuck_calls:
                    call_id = call["id"]
                    started_at = call["started_at"]
                    duration = int((datetime.utcnow() - started_at).total_seconds())

                    logger.warning(
                        f"Cleaning up stuck call {call_id}: "
                        f"started {duration}s ago, status={call['status']}"
                    )

                    await db.execute(
                        """
                        UPDATE calls
                        SET ended_at = :ended_at,
                            duration_seconds = :duration,
                            status = 'declined'
                        WHERE id = :id
                        """,
                        {
                            "id": str(call_id),
                            "ended_at": datetime.utcnow(),
                            "duration": duration,
                        }
                    )

            # Fix sessions with ended_at but missing duration
            result = await db.execute(
                """
                UPDATE calls
                SET duration_seconds = EXTRACT(EPOCH FROM (ended_at - started_at))::INTEGER
                WHERE ended_at IS NOT NULL
                  AND duration_seconds IS NULL
                  AND started_at IS NOT NULL
                """
            )

            logger.debug("Session cleanup completed")

        except Exception as e:
            logger.error(f"Error cleaning up stuck sessions: {e}", exc_info=True)
