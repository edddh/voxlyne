"""
Voxlyne - CRM Retry Manager

Handles retry logic with exponential backoff for CRM operations.
"""

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional, Tuple

from app.database.db import get_database
from app.services.crm.base import CRMSyncResult, CRMSyncStatus

logger = logging.getLogger(__name__)


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        initial_delay: float = 5.0,
        max_delay: float = 300.0,
        exponential_base: float = 2.0,
        jitter_factor: float = 0.2,
    ):
        self.max_attempts = max_attempts
        self.initial_delay = initial_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter_factor = jitter_factor


class RetryManager:
    """
    Manages retry logic with exponential backoff.

    Features:
    - Exponential backoff with jitter
    - Database tracking of attempts
    - Configurable retry limits
    - Respects should_retry flag from results
    """

    def __init__(self, config: Optional[RetryConfig] = None):
        self.config = config or RetryConfig()

    def calculate_delay(self, attempt: int) -> float:
        """
        Calculate delay for next retry with exponential backoff and jitter.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            Delay in seconds
        """
        # Exponential backoff
        delay = self.config.initial_delay * (
            self.config.exponential_base ** (attempt - 1)
        )

        # Cap at max delay
        delay = min(delay, self.config.max_delay)

        # Add jitter (±jitter_factor%)
        jitter_range = delay * self.config.jitter_factor
        jitter = random.uniform(-jitter_range, jitter_range)

        return max(0.1, delay + jitter)

    async def execute_with_retry(
        self,
        func: Callable[..., Awaitable[CRMSyncResult]],
        args: Tuple[Any, ...],
        log_id: int,
    ) -> CRMSyncResult:
        """
        Execute function with retry logic.

        Args:
            func: Async function to execute
            args: Arguments for the function
            log_id: ID in crm_sync_log table for tracking

        Returns:
            Final CRMSyncResult after all attempts
        """
        db = get_database()
        last_result: Optional[CRMSyncResult] = None

        for attempt in range(1, self.config.max_attempts + 1):
            # Update attempt count in database
            status = CRMSyncStatus.RETRYING.value if attempt > 1 else CRMSyncStatus.PENDING.value
            await db.execute(
                """
                UPDATE crm_sync_log
                SET attempt_count = :attempt,
                    status = :status,
                    updated_at = :updated_at
                WHERE id = :id
                """,
                {
                    "id": log_id,
                    "attempt": attempt,
                    "status": status,
                    "updated_at": datetime.now(timezone.utc),
                },
            )

            try:
                # Execute the function
                result = await func(*args)
                last_result = result

                if result.success:
                    logger.info(f"CRM sync succeeded on attempt {attempt}")
                    return result

                if not result.should_retry:
                    logger.warning(
                        f"CRM sync failed (non-retryable): {result.error_message}"
                    )
                    return result

                # Log retry info
                if attempt < self.config.max_attempts:
                    delay = self.calculate_delay(attempt)
                    next_retry = datetime.now(timezone.utc) + timedelta(seconds=delay)

                    logger.info(
                        f"CRM sync attempt {attempt} failed, retrying in {delay:.1f}s: "
                        f"{result.error_message}"
                    )

                    # Update next retry time
                    await db.execute(
                        """
                        UPDATE crm_sync_log
                        SET next_retry_at = :next_retry,
                            error_message = :error,
                            response_code = :code,
                            updated_at = :updated_at
                        WHERE id = :id
                        """,
                        {
                            "id": log_id,
                            "next_retry": next_retry,
                            "error": result.error_message,
                            "code": result.response_code,
                            "updated_at": datetime.now(timezone.utc),
                        },
                    )

                    # Wait before retry
                    await asyncio.sleep(delay)

            except Exception as e:
                logger.error(f"CRM sync attempt {attempt} raised exception: {e}")
                last_result = CRMSyncResult(
                    success=False,
                    error_message=str(e),
                    should_retry=True,
                )

                if attempt < self.config.max_attempts:
                    delay = self.calculate_delay(attempt)
                    logger.info(f"Retrying in {delay:.1f}s after exception")
                    await asyncio.sleep(delay)

        # All attempts exhausted
        logger.error(
            f"CRM sync failed after {self.config.max_attempts} attempts"
        )

        return last_result or CRMSyncResult(
            success=False,
            error_message="All retry attempts exhausted",
            should_retry=False,
        )

    async def update_final_status(
        self,
        log_id: int,
        result: CRMSyncResult,
    ) -> None:
        """
        Update final status in database after all retries.

        Args:
            log_id: ID in crm_sync_log table
            result: Final result
        """
        db = get_database()

        status = (
            CRMSyncStatus.SUCCESS.value
            if result.success
            else CRMSyncStatus.FAILED.value
        )

        await db.execute(
            """
            UPDATE crm_sync_log
            SET status = :status,
                external_id = :external_id,
                response_code = :response_code,
                response_body = :response_body,
                error_message = :error_message,
                completed_at = :completed_at,
                next_retry_at = NULL,
                updated_at = :updated_at
            WHERE id = :id
            """,
            {
                "id": log_id,
                "status": status,
                "external_id": result.external_id,
                "response_code": result.response_code,
                "response_body": (
                    result.response_body[:2000]
                    if result.response_body
                    else None
                ),
                "error_message": result.error_message,
                "completed_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
            },
        )
