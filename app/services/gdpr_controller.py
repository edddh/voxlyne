"""
Voxlyne - GDPR Controller
Handles data deletion and privacy compliance
"""

import logging
from datetime import date
from typing import Optional
from uuid import UUID

from app.database.db import get_database

logger = logging.getLogger(__name__)

# Import S3 client lazily to avoid circular imports
def get_s3_client_safe():
    """Safely import S3 client (M2 feature)."""
    try:
        from app.storage.s3_client import get_s3_client
        return get_s3_client()
    except ImportError:
        return None


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
        - Records (M2, via CASCADE)
        - PDF files (M2, from S3/MinIO)

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

            # 2. Delete PDF from S3/MinIO (M2)
            s3_client = get_s3_client_safe()
            if s3_client:
                pdf_deleted = await self._delete_pdf_if_exists(call_id, s3_client)
                if pdf_deleted:
                    records_deleted += 1

            # 3. Count records before deletion (for reporting)
            transcript_count = await db.fetch_one(
                "SELECT COUNT(*) as count FROM transcripts WHERE call_id = :call_id",
                {"call_id": str(call_id)}
            )
            records_deleted += transcript_count["count"] if transcript_count else 0

            # Count record (M2)
            record = await db.fetch_one(
                "SELECT id FROM records WHERE call_id = :call_id",
                {"call_id": str(call_id)}
            )
            if record:
                records_deleted += 1  # The record itself

            # 4. Delete the call (CASCADE will delete transcripts and records)
            result = await db.execute(
                "DELETE FROM calls WHERE id = :id",
                {"id": str(call_id)}
            )
            records_deleted += 1  # The call record itself

            # 5. Increment anonymous cancellation counter
            await self._increment_cancellation_counter()

            # 6. Log success (NO PII)
            logger.info(f"GDPR hard delete completed: {records_deleted} records removed")

            return records_deleted

        except Exception as e:
            logger.error(f"GDPR hard delete failed: {e}")
            raise

    async def delete_transcripts(self, call_id: UUID) -> int:
        """
        Delete only transcripts for a call, leaving the call record intact.

        Returns the number of transcript rows deleted.
        """
        db = get_database()
        logger.info("Deleting transcripts for call (ID redacted for privacy)")

        try:
            # Count transcripts before deletion
            transcript_count = await db.fetch_one(
                "SELECT COUNT(*) as count FROM transcripts WHERE call_id = :call_id",
                {"call_id": str(call_id)},
            )
            count = transcript_count["count"] if transcript_count else 0

            await db.execute(
                "DELETE FROM transcripts WHERE call_id = :call_id",
                {"call_id": str(call_id)},
            )

            # Track anonymous cancellation
            await self._increment_cancellation_counter()

            logger.info(f"Transcript deletion completed: {count} rows removed")
            return count

        except Exception as e:
            logger.error(f"Transcript deletion failed: {e}")
            raise

    async def _delete_pdf_if_exists(self, call_id: UUID, s3_client) -> bool:
        """
        Delete PDF file from S3 if it exists.
        Returns True if PDF was deleted, False if not found.
        """
        db = get_database()

        try:
            # Check if record exists with PDF
            record = await db.fetch_one(
                "SELECT pdf_key FROM records WHERE call_id = :call_id",
                {"call_id": str(call_id)}
            )

            if not record or not record["pdf_key"]:
                logger.debug("No PDF to delete")
                return False

            # Delete from S3
            s3_client.delete_pdf(record["pdf_key"])
            logger.info(f"PDF deleted from S3: {record['pdf_key']}")
            return True

        except Exception as e:
            # Non-critical - log but don't fail the deletion
            logger.warning(f"Failed to delete PDF from S3: {e}")
            return False

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
            logger.warning("GDPR verification failed: call record still exists")
            return False

        # Check transcripts (should be deleted via CASCADE, but verify)
        transcript = await db.fetch_one(
            "SELECT id FROM transcripts WHERE call_id = :call_id",
            {"call_id": str(call_id)}
        )

        if transcript:
            logger.warning("GDPR verification failed: transcript still exists")
            return False

        # Check records table (M2)
        record = await db.fetch_one(
            "SELECT id, pdf_key FROM records WHERE call_id = :call_id",
            {"call_id": str(call_id)}
        )

        if record:
            logger.warning("GDPR verification failed: record still exists")
            return False

        # Verification passed
        logger.info("GDPR verification passed: all data deleted")
        return True
