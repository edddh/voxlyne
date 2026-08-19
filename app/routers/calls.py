"""
Ascolta - Calls API Routes (M4 Extended)

Enhanced calls management with tenant filtering, search, and transcript viewer.
"""

import logging
from datetime import datetime
from typing import List, Optional
from uuid import UUID

import json

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse

from app.database.db import get_database
from app.middleware.auth_middleware import (
    CurrentUser,
    TenantContext,
    get_current_user,
    get_tenant_context,
    require_roles,
)
from app.models.schemas import (
    Call,
    CallComplete,
    CallStatus,
    Record,
    Transcript,
)
from app.services.pdf_generator import PDFGenerator, PDFGeneratorError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v2/calls", tags=["Calls V2"])


def _extract_json_field(json_data, key: str):
    """
    Pull one field out of a record's extracted JSON (Prompt B output) -
    shared by list_calls (candidate_name) and get_call_detail
    (candidate_name + email), which each read it independently before this
    helper existed. json_data can arrive already parsed (dict) or as a raw
    string depending on the driver/column, so both are handled.
    """
    if not json_data:
        return None
    if isinstance(json_data, str):
        try:
            json_data = json.loads(json_data)
        except json.JSONDecodeError:
            return None
    if isinstance(json_data, dict):
        return json_data.get(key)
    return None


@router.get("")
async def list_calls(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[CallStatus] = None,
    project_id: Optional[UUID] = None,
    phone_search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    List calls with advanced filtering and pagination.

    Supports:
    - Status filter
    - Project filter
    - Phone number search
    - Date range filter
    - Tenant isolation (automatic for non-super-admin)
    """
    db = get_database()

    # Build base query
    base_query = """
        SELECT c.*, p.name as project_name, p.slug as project_slug,
               r.id as record_id, r.json_data, r.pdf_key
        FROM calls c
        LEFT JOIN projects p ON c.project_id = p.id
        LEFT JOIN records r ON r.call_id = c.id
        WHERE 1=1
    """
    count_query = "SELECT COUNT(*) FROM calls c WHERE 1=1"

    params = {}

    # Tenant filter
    if not current_user.is_super_admin:
        base_query += " AND c.tenant_id = :tenant_id"
        count_query += " AND c.tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    # Status filter
    if status:
        base_query += " AND c.status = :status"
        count_query += " AND c.status = :status"
        params["status"] = status.value

    # Project filter
    if project_id:
        base_query += " AND c.project_id = :project_id"
        count_query += " AND c.project_id = :project_id"
        params["project_id"] = str(project_id)

    # Phone search
    if phone_search:
        base_query += " AND c.phone_number ILIKE :phone_search"
        count_query += " AND c.phone_number ILIKE :phone_search"
        params["phone_search"] = f"%{phone_search}%"

    # Date range
    if date_from:
        base_query += " AND c.created_at >= :date_from"
        count_query += " AND c.created_at >= :date_from"
        params["date_from"] = date_from

    if date_to:
        base_query += " AND c.created_at <= :date_to"
        count_query += " AND c.created_at <= :date_to"
        params["date_to"] = date_to

    # Pagination
    offset = (page - 1) * page_size
    base_query += " ORDER BY c.created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = page_size
    params["offset"] = offset

    # Execute queries
    calls = await db.fetch_all(base_query, params)
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    total_result = await db.fetch_one(count_query, count_params)
    total = total_result[0] if total_result else 0

    return {
        "calls": [
            {
                "id": str(c["id"]),
                "phone_number": c["phone_number"],
                "status": c["status"],
                "consent_given": c["consent_given"],
                "started_at": c["started_at"],
                "ended_at": c["ended_at"],
                "duration_seconds": c["duration_seconds"],
                "project_id": str(c["project_id"]) if c["project_id"] else None,
                "project_name": c["project_name"],
                "project_slug": c["project_slug"],
                "has_record": c["record_id"] is not None,
                "has_pdf": c["pdf_key"] is not None,
                "candidate_name": _extract_json_field(c["json_data"], "candidate_name"),
                "created_at": c["created_at"],
            }
            for c in calls
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/{call_id}")
async def get_call_detail(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get detailed call information including transcript.
    """
    db = get_database()

    # Build query with tenant check
    query = """
        SELECT c.*, p.name as project_name, p.slug as project_slug
        FROM calls c
        LEFT JOIN projects p ON c.project_id = p.id
        WHERE c.id = :call_id
    """
    params = {"call_id": str(call_id)}

    if not current_user.is_super_admin:
        query += " AND c.tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    call = await db.fetch_one(query, params)

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    # Fetch transcript
    transcripts = await db.fetch_all(
        """
        SELECT id, role, content, timestamp
        FROM transcripts
        WHERE call_id = :call_id
        ORDER BY timestamp ASC
        """,
        {"call_id": str(call_id)},
    )

    # Fetch record
    record = await db.fetch_one(
        "SELECT * FROM records WHERE call_id = :call_id",
        {"call_id": str(call_id)},
    )

    # Fetch CRM sync info
    crm_sync = await db.fetch_one(
        """
        SELECT provider, status, external_id, completed_at, error_message
        FROM crm_sync_log
        WHERE call_id = :call_id
        ORDER BY created_at DESC
        LIMIT 1
        """,
        {"call_id": str(call_id)},
    )

    # Fetch calendar event
    calendar_event = await db.fetch_one(
        """
        SELECT ce.*
        FROM calendar_events ce
        JOIN records r ON ce.record_id = r.id
        WHERE r.call_id = :call_id
        ORDER BY ce.created_at DESC
        LIMIT 1
        """,
        {"call_id": str(call_id)},
    )

    return {
        "call": {
            "id": str(call["id"]),
            "phone_number": call["phone_number"],
            "status": call["status"],
            "consent_given": call["consent_given"],
            "consent_timestamp": call["consent_timestamp"],
            "started_at": call["started_at"],
            "ended_at": call["ended_at"],
            "duration_seconds": call["duration_seconds"],
            "project_id": str(call["project_id"]) if call["project_id"] else None,
            "project_name": call["project_name"],
            "project_slug": call["project_slug"],
            "openai_session_id": call["openai_session_id"],
            "created_at": call["created_at"],
            "updated_at": call["updated_at"],
            # Stessa estrazione di list_calls (_extract_json_field) - non
            # era mai stata portata qui, quindi la scheda dettaglio
            # mostrava sempre "-" anche quando il record estratto aveva
            # queste informazioni.
            "candidate_name": _extract_json_field(record["json_data"], "candidate_name") if record else None,
            "candidate_email": _extract_json_field(record["json_data"], "email") if record else None,
            "has_pdf": record["pdf_key"] is not None if record else False,
        },
        "transcript": [
            {
                "id": t["id"],
                "role": t["role"],
                "content": t["content"],
                "timestamp": t["timestamp"],
            }
            for t in transcripts
        ],
        "record": {
            "id": record["id"],
            "json_data": record["json_data"],
            "pdf_key": record["pdf_key"],
            "pdf_generated_at": record["pdf_generated_at"],
            "email_sent": record["email_sent"],
            "email_sent_at": record["email_sent_at"],
            "created_at": record["created_at"],
        } if record else None,
        "crm_sync": {
            "provider": crm_sync["provider"],
            "status": crm_sync["status"],
            "external_id": crm_sync["external_id"],
            "completed_at": crm_sync["completed_at"],
            "error_message": crm_sync["error_message"],
        } if crm_sync else None,
        "calendar_event": {
            "id": calendar_event["id"],
            "provider": calendar_event["provider"],
            "scheduled_at": calendar_event["scheduled_at"],
            "status": calendar_event["status"],
            "event_link": calendar_event["event_link"],
        } if calendar_event else None,
    }


@router.get("/{call_id}/transcript")
async def get_call_transcript(
    call_id: UUID,
    format: str = Query("json", regex="^(json|text)$"),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get call transcript.

    Format options:
    - json: Structured transcript with timestamps
    - text: Plain text conversation
    """
    db = get_database()

    # Verify call access
    query = "SELECT id, tenant_id FROM calls WHERE id = :call_id"
    params = {"call_id": str(call_id)}

    if not current_user.is_super_admin:
        query += " AND tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    call = await db.fetch_one(query, params)

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    # Fetch transcript
    transcripts = await db.fetch_all(
        """
        SELECT id, role, content, timestamp
        FROM transcripts
        WHERE call_id = :call_id
        ORDER BY timestamp ASC
        """,
        {"call_id": str(call_id)},
    )

    if format == "text":
        # Return as plain text
        lines = []
        for t in transcripts:
            role_label = {
                "user": "Candidato",
                "assistant": "AI",
                "system": "Sistema",
            }.get(t["role"], t["role"])
            lines.append(f"[{t['timestamp'].strftime('%H:%M:%S')}] {role_label}: {t['content']}")

        return Response(
            content="\n\n".join(lines),
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=transcript_{call_id}.txt"
            },
        )

    # Return as JSON
    return {
        "call_id": str(call_id),
        "messages": [
            {
                "id": t["id"],
                "role": t["role"],
                "content": t["content"],
                "timestamp": t["timestamp"],
            }
            for t in transcripts
        ],
        "total_messages": len(transcripts),
    }


@router.get("/{call_id}/pdf")
async def download_call_pdf(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Download PDF report for a call.
    """
    db = get_database()

    # Verify call access
    query = "SELECT id, tenant_id FROM calls WHERE id = :call_id"
    params = {"call_id": str(call_id)}

    if not current_user.is_super_admin:
        query += " AND tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    call = await db.fetch_one(query, params)

    if not call:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call not found",
        )

    pdf_generator = PDFGenerator()

    try:
        pdf_bytes = await pdf_generator.download_pdf(call_id)

        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=report_{call_id}.pdf"
            },
        )

    except PDFGeneratorError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{call_id}/json")
async def get_call_json(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get extracted JSON data for a call.
    """
    db = get_database()

    # Verify call access
    query = """
        SELECT c.id, r.json_data
        FROM calls c
        JOIN records r ON r.call_id = c.id
        WHERE c.id = :call_id
    """
    params = {"call_id": str(call_id)}

    if not current_user.is_super_admin:
        query += " AND c.tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    result = await db.fetch_one(query, params)

    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Call or record not found",
        )

    return {
        "call_id": str(call_id),
        "data": result["json_data"],
    }


# Import Response for text format
from fastapi import Response
