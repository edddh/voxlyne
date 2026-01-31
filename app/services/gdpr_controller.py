"""
Ascolta - GDPR Controller
Handles data deletion and privacy compliance
"""

import logging
from datetime import date
from uuid import UUID

from app.database.db import get_database

logger = logging.getLogger(__name__)


class GDPRController:
    """
    Manages GDPR compliance operations.

    Key responsibilities:
    - Hard delete all user data on request
    - Ensure no PII remains in logs
    - Track anonymous cancellation metrics
    """

    async def hard_delete(self, call_id: UUID) -> int:
        """
        Perform complete data deletion for a call.

        This deletes:
        - Call record
        - All transcripts (via CASCADE)
        - Any records/candidates (in M2, via CASCADE)
        - PDF files (in M2)

        Returns the number of records deleted.

        Note: This increments the anonymous cancellation counter
        but stores NO PII about the deletion.
        """
        db = get_database()
        records_deleted = 0

        logger.info(f"Starting GDPR hard delete for call (ID redacted for privacy)")

        try:
            # 1. Check if call exists
            call = await db.fetch_one(
                "SELECT id, status FROM calls WHERE id = :id",
                {"id": str(call_id)}
            )

            if not call:
                logger.warning("Call not found for deletion")
                return 0

            # 2. Count transcripts before deletion (for reporting)
            transcript_count = await db.fetch_one(
                "SELECT COUNT(*) as count FROM transcripts WHERE call_id = :call_id",
                {"call_id": str(call_id)}
            )
            records_deleted += transcript_count["count"] if transcript_count else 0

            # 3. Delete the call (CASCADE will delete transcripts)
            result = await db.execute(
                "DELETE FROM calls WHERE id = :id",
                {"id": str(call_id)}
            )
            records_deleted += 1  # The call record itself

            # 4. Increment anonymous cancellation counter
            await self._increment_cancellation_counter()

            # 5. Log success (NO PII)
            logger.info(f"GDPR hard delete completed: {records_deleted} records removed")

            return records_deleted

        except Exception as e:
            logger.error(f"GDPR hard delete failed: {e}")
            raise

    async def _increment_cancellation_counter(self) -> None:
        """
        Increment the anonymous cancellation counter for today.
        This is the ONLY data that survives a hard delete.
        No PII is stored - just a count.
        """
        db = get_database()
        today = date.today()

        try:
            # Check if metrics table exists (might not in M1)
            # We'll create a simple version for M1
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS _gdpr_metrics (
                    date DATE PRIMARY KEY,
                    cancelled_calls INTEGER DEFAULT 0
                )
                """
            )

            # Upsert the counter
            await db.execute(
                """
                INSERT INTO _gdpr_metrics (date, cancelled_calls)
                VALUES (:date, 1)
                ON CONFLICT (date) DO UPDATE
                SET cancelled_calls = _gdpr_metrics.cancelled_calls + 1
                """,
                {"date": today}
            )

            logger.debug("Cancellation counter incremented")

        except Exception as e:
            # Non-critical - log but don't fail the deletion
            logger.warning(f"Failed to increment cancellation counter: {e}")

    async def get_cancellation_stats(self) -> dict:
        """
        Get anonymous cancellation statistics.
        This is safe to expose as it contains no PII.
        """
        db = get_database()

        try:
            # Get total cancellations
            result = await db.fetch_one(
                """
                SELECT
                    COALESCE(SUM(cancelled_calls), 0) as total_cancellations,
                    COUNT(*) as days_with_data
                FROM _gdpr_metrics
                """
            )

            # Get today's cancellations
            today_result = await db.fetch_one(
                """
                SELECT COALESCE(cancelled_calls, 0) as today_cancellations
                FROM _gdpr_metrics
                WHERE date = :today
                """,
                {"date": date.today()}
            )

            return {
                "total_cancellations": result["total_cancellations"] if result else 0,
                "days_with_data": result["days_with_data"] if result else 0,
                "today_cancellations": today_result["today_cancellations"] if today_result else 0,
            }

        except Exception as e:
            logger.warning(f"Failed to get cancellation stats: {e}")
            return {
                "total_cancellations": 0,
                "days_with_data": 0,
                "today_cancellations": 0,
            }

    async def verify_deletion(self, call_id: UUID) -> bool:
        """
        Verify that all data for a call has been deleted.
        Used for compliance auditing.
        """
        db = get_database()

        # Check calls table
        call = await db.fetch_one(
            "SELECT id FROM calls WHERE id = :id",
            {"id": str(call_id)}
        )

        if call:
            return False

        # Check transcripts (should be deleted via CASCADE, but verify)
        transcript = await db.fetch_one(
            "SELECT id FROM transcripts WHERE call_id = :call_id",
            {"call_id": str(call_id)}
        )

        if transcript:
            return False

        # TODO (M2): Check records table
        # TODO (M2): Check S3 for PDF files

        return True
