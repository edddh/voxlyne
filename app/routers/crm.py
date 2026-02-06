"""
Ascolta - CRM Admin API Routes

Endpoints for CRM synchronization management and monitoring.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.database.db import get_database
from app.models.schemas import (
    CRMProvider,
    CRMStatsResponse,
    CRMStatusResponse,
    CRMSyncLog,
    CRMTestConnectionRequest,
    CRMTestConnectionResponse,
    CRMRetryRequest,
    CRMRetryResponse,
)
from app.services.crm.dispatcher import CRMDispatcher

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/crm", tags=["CRM"])


@router.get("/calls/{call_id}/status", response_model=CRMStatusResponse)
async def get_crm_status(call_id: UUID):
    """
    Get CRM sync status for a specific call.

    Returns sync status, external ID, and sync log history.
    """
    db = get_database()

    # Get record CRM status
    record = await db.fetch_one(
        """
        SELECT crm_synced, crm_synced_at, crm_external_id, crm_provider, crm_error
        FROM records
        WHERE call_id = :call_id
        """,
        {"call_id": str(call_id)},
    )

    # Get sync logs
    logs = await db.fetch_all(
        """
        SELECT id, call_id, record_id, provider, operation, status,
               external_id, response_code, error_message, attempt_count,
               max_attempts, next_retry_at, created_at, completed_at
        FROM crm_sync_log
        WHERE call_id = :call_id
        ORDER BY created_at DESC
        LIMIT 10
        """,
        {"call_id": str(call_id)},
    )

    # Get last error from logs if not in record
    last_error = None
    if record and record["crm_error"]:
        last_error = record["crm_error"]
    elif logs:
        failed_log = next(
            (l for l in logs if l["status"] == "failed"),
            None
        )
        if failed_log:
            last_error = failed_log["error_message"]

    return CRMStatusResponse(
        call_id=call_id,
        synced=record["crm_synced"] if record else False,
        provider=record["crm_provider"] if record else None,
        external_id=record["crm_external_id"] if record else None,
        synced_at=record["crm_synced_at"] if record else None,
        last_error=last_error,
        sync_log=[CRMSyncLog(**dict(l)) for l in logs],
    )


@router.post("/calls/{call_id}/retry", response_model=CRMRetryResponse)
async def retry_crm_sync(call_id: UUID):
    """
    Manually retry CRM sync for a call.

    Useful when automatic retries have been exhausted or
    credentials have been updated.
    """
    db = get_database()

    # Verify call and record exist
    record = await db.fetch_one(
        """
        SELECT r.id, r.json_data, c.started_at, c.duration_seconds, c.phone_number
        FROM records r
        JOIN calls c ON r.call_id = c.id
        WHERE r.call_id = :call_id
        """,
        {"call_id": str(call_id)},
    )

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Record not found for this call"
        )

    # Trigger retry
    dispatcher = CRMDispatcher()
    success = await dispatcher.retry_sync(call_id)

    return CRMRetryResponse(
        success=success,
        message="CRM sync retry initiated" if success else "CRM sync retry failed",
        call_id=call_id,
    )


@router.get("/sync-log", response_model=List[CRMSyncLog])
async def list_sync_logs(
    status: Optional[str] = Query(None, description="Filter by status"),
    provider: Optional[str] = Query(None, description="Filter by provider"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """
    List CRM sync log entries.

    Supports filtering by status and provider.
    """
    db = get_database()

    # Build query dynamically
    conditions = []
    params = {"limit": limit, "offset": offset}

    if status:
        conditions.append("status = :status")
        params["status"] = status

    if provider:
        conditions.append("provider = :provider")
        params["provider"] = provider

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""

    query = f"""
        SELECT id, call_id, record_id, provider, operation, status,
               external_id, response_code, error_message, attempt_count,
               max_attempts, next_retry_at, created_at, completed_at
        FROM crm_sync_log
        {where_clause}
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
    """

    logs = await db.fetch_all(query, params)
    return [CRMSyncLog(**dict(l)) for l in logs]


@router.get("/stats", response_model=CRMStatsResponse)
async def get_crm_stats():
    """
    Get CRM synchronization statistics.

    Returns aggregate counts and recent failures.
    """
    db = get_database()

    # Total counts by status
    status_counts = await db.fetch_all(
        """
        SELECT status, COUNT(*) as count
        FROM crm_sync_log
        GROUP BY status
        """
    )

    status_map = {row["status"]: row["count"] for row in status_counts}

    # Counts by provider (successful only)
    provider_counts = await db.fetch_all(
        """
        SELECT provider, COUNT(*) as count
        FROM crm_sync_log
        WHERE status = 'success'
        GROUP BY provider
        """
    )

    by_provider = {row["provider"]: row["count"] for row in provider_counts}

    # Recent failures
    failures = await db.fetch_all(
        """
        SELECT id, call_id, record_id, provider, operation, status,
               external_id, response_code, error_message, attempt_count,
               max_attempts, next_retry_at, created_at, completed_at
        FROM crm_sync_log
        WHERE status = 'failed'
        ORDER BY created_at DESC
        LIMIT 10
        """
    )

    return CRMStatsResponse(
        total_syncs=sum(status_map.values()),
        successful=status_map.get("success", 0),
        failed=status_map.get("failed", 0),
        pending=status_map.get("pending", 0) + status_map.get("retrying", 0),
        by_provider=by_provider,
        recent_failures=[CRMSyncLog(**dict(f)) for f in failures],
    )


@router.post("/test-connection", response_model=CRMTestConnectionResponse)
async def test_crm_connection(request: CRMTestConnectionRequest):
    """
    Test CRM connection with provided credentials.

    Validates that credentials are correct and the CRM is reachable.
    """
    dispatcher = CRMDispatcher()

    try:
        success = await dispatcher.test_connection(
            provider=request.provider.value,
            credentials=request.credentials,
            config=request.config,
        )

        return CRMTestConnectionResponse(
            success=success,
            message="Connection successful" if success else "Connection failed",
            provider=request.provider.value,
            details={"tested_at": "now"},
        )

    except ValueError as e:
        return CRMTestConnectionResponse(
            success=False,
            message=f"Configuration error: {str(e)}",
            provider=request.provider.value,
        )

    except Exception as e:
        logger.error(f"CRM connection test error: {e}")
        return CRMTestConnectionResponse(
            success=False,
            message=f"Connection test failed: {str(e)}",
            provider=request.provider.value,
        )


@router.get("/providers", response_model=List[dict])
async def list_providers():
    """
    List available CRM providers with their configuration requirements.
    """
    return [
        {
            "name": "hubspot",
            "display_name": "HubSpot",
            "description": "Create contacts and deals in HubSpot CRM",
            "credentials_required": ["access_token"],
            "credentials_optional": ["api_key"],
            "config_options": {
                "create_contact": "boolean - Create contact (default: true)",
                "create_deal": "boolean - Also create deal linked to contact",
                "deal_pipeline": "string - HubSpot pipeline ID",
                "deal_stage": "string - HubSpot deal stage ID",
            },
        },
        {
            "name": "generic_webhook",
            "display_name": "Generic Webhook",
            "description": "Send candidate data to any HTTP endpoint",
            "credentials_required": [],
            "credentials_optional": ["secret"],
            "config_options": {
                "url": "string - Webhook endpoint URL (required)",
                "method": "string - HTTP method (default: POST)",
                "headers": "object - Custom headers to include",
            },
        },
    ]
