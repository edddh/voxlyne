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


async def _can_view_costs(db, current_user: CurrentUser) -> bool:
    """
    Real call costs are always visible to super_admin. Tenant admins can
    optionally see them when the tenant-level setting
    settings.show_costs_to_tenant_admin is enabled by a super_admin.
    """
    if current_user.is_super_admin:
        return True
    if current_user.role != "admin" or not current_user.tenant_id:
        return False
    tenant_row = await db.fetch_one(
        "SELECT settings FROM tenants WHERE id = :id",
        {"id": str(current_user.tenant_id)},
    )
    if not tenant_row or not tenant_row["settings"]:
        return False
    settings = tenant_row["settings"]
    if isinstance(settings, str):
        try:
            settings = json.loads(settings)
        except json.JSONDecodeError:
            settings = {}
    return bool((settings or {}).get("show_costs_to_tenant_admin"))


@router.get("")
async def list_calls(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[CallStatus] = None,
    project_id: Optional[UUID] = None,
    phone_search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    origin: Optional[str] = Query("production", pattern="^(production|voice_simulation|all)$"),
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
    can_view_costs = await _can_view_costs(db, current_user)

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

    if origin != "all":
        base_query += " AND c.origin = :origin"
        count_query += " AND c.origin = :origin"
        params["origin"] = origin

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
                # Costo reale in $ - solo super_admin (maintainer, 20/08:
                # "i costi reali delle chiamate devono essere visibili
                # solo dal superadmin"). Il resto degli utenti (sempre
                # tenant-scoped) ha /stats con minutes_used/
                # minutes_included invece.
                "cost_usd": (
                    float(c["cost_usd"])
                    if can_view_costs and c["cost_usd"] is not None
                    else None
                ),
                "project_id": str(c["project_id"]) if c["project_id"] else None,
                "project_name": c["project_name"],
                "project_slug": c["project_slug"],
                "has_record": c["record_id"] is not None,
                "has_pdf": c["pdf_key"] is not None,
                "candidate_name": _extract_json_field(c["json_data"], "candidate_name"),
                "created_at": c["created_at"],
                "origin": c["origin"] or "production",
                "channel": c["channel"],
            }
            for c in calls
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
        "can_view_costs": can_view_costs,
    }


@router.get("/stats")
async def get_calls_stats(
    status: Optional[CallStatus] = None,
    project_id: Optional[UUID] = None,
    phone_search: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    origin: Optional[str] = Query("production", pattern="^(production|voice_simulation|all)$"),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Real aggregate counts for the Chiamate page's stat cards.

    maintainer, 20/08: the old cards ("Completate (in lista)" etc.) were
    computed client-side from whatever page of results happened to be
    loaded (up to page_size rows) - not a real total, and it changed
    depending on which page you were looking at. "che cagata e', io
    voglio sapere piuttosto quante effettuate oggi, quante in totale" -
    these are real COUNT(*) queries over ALL of the tenant's calls, not
    just the current page. Must be registered before GET /{call_id} or
    FastAPI would try to parse "stats" as a UUID path param.

    "i costi reali delle chiamate devono essere visibili solo dal
    superadmin e aggregabili anche per tenant, gli utenti del tenant
    devono vedere quanto del pacchetto hanno utilizzato" (20/08) - two
    different responses depending on who's asking, not the same payload
    with some fields hidden client-side (a tenant admin could just read
    the network tab):
    - super_admin: real $ costs, totals AND broken down per tenant
      (by_tenant).
    - everyone else (admin/power_user/creator, always tenant-scoped):
      no $ figure anywhere in the response - minutes used against their
      package allowance instead (tenants.settings->>'included_minutes',
      no UI to set it yet, None = no package configured).
    """
    db = get_database()
    can_view_costs = await _can_view_costs(db, current_user)
    where = "WHERE 1=1"
    params = {}
    if not current_user.is_super_admin:
        where += " AND tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    if origin != "all":
        where += " AND origin = :origin"
        params["origin"] = origin

    if status:
        where += " AND status = :status"
        params["status"] = status.value

    if project_id:
        where += " AND project_id = :project_id"
        params["project_id"] = str(project_id)

    if phone_search:
        where += " AND phone_number ILIKE :phone_search"
        params["phone_search"] = f"%{phone_search}%"

    if date_from:
        where += " AND created_at >= :date_from"
        params["date_from"] = date_from

    if date_to:
        where += " AND created_at <= :date_to"
        params["date_to"] = date_to

    # 20/08 (maintainer): "in_progress" (chiamata dal vivo adesso) e
    # "processing" (post-elaborazione automatica di pochi secondi dopo
    # che la chiamata e' gia' finita: estrazione dati, PDF, email, CRM)
    # erano sommati in un unico numero "In Elaborazione" - due momenti
    # diversi del ciclo di vita. Alla domanda "in elaborazione che vuol
    # dire? secondo me non ha senso" - non ne ha, come card fissa: dura
    # pochi secondi, quasi sempre 0, nessuna informazione utile a colpo
    # d'occhio. Tolto (era "La tolgo" nella risposta) - resta solo
    # in_progress, che invece ha un senso chiaro ("c'e' qualcuno al
    # telefono adesso").
    row = await db.fetch_one(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (
                WHERE (created_at AT TIME ZONE 'Europe/Rome')::date = (now() AT TIME ZONE 'Europe/Rome')::date
            ) AS today,
            COUNT(*) FILTER (WHERE status IN ('completed', 'processed')) AS completed,
            COUNT(*) FILTER (WHERE status = 'in_progress') AS in_progress,
            AVG(duration_seconds) FILTER (WHERE duration_seconds IS NOT NULL) AS avg_duration_seconds,
            SUM(cost_usd) FILTER (WHERE cost_usd IS NOT NULL) AS total_cost_usd,
            SUM(cost_usd) FILTER (
                WHERE cost_usd IS NOT NULL
                AND (created_at AT TIME ZONE 'Europe/Rome')::date = (now() AT TIME ZONE 'Europe/Rome')::date
            ) AS today_cost_usd,
            SUM(duration_seconds) FILTER (
                WHERE duration_seconds IS NOT NULL
                AND date_trunc('month', created_at AT TIME ZONE 'Europe/Rome') =
                    date_trunc('month', now() AT TIME ZONE 'Europe/Rome')
            ) AS duration_seconds_current_month,
            SUM(duration_seconds) FILTER (
                WHERE duration_seconds IS NOT NULL
                AND date_trunc('year', created_at AT TIME ZONE 'Europe/Rome') =
                    date_trunc('year', now() AT TIME ZONE 'Europe/Rome')
            ) AS duration_seconds_current_year
        FROM calls
        {where}
        """,
        params,
    )

    result = {
        "total": row["total"],
        "today": row["today"],
        "completed": row["completed"],
        "in_progress": row["in_progress"],
        "avg_duration_seconds": float(row["avg_duration_seconds"]) if row["avg_duration_seconds"] is not None else None,
        # Coerenza esplicita richiesta: questi minuti devono combaciare
        # con la lista chiamate sotto, quindi derivano dalla stessa
        # popolazione filtrata e dalla durata chiamata, non da un
        # contatore tecnico separato.
        "minutes_used": round((row["duration_seconds_current_month"] or 0) / 60, 2),
        "minutes_used_current_month": round((row["duration_seconds_current_month"] or 0) / 60, 2),
        "minutes_used_current_year": round((row["duration_seconds_current_year"] or 0) / 60, 2),
    }

    if can_view_costs:
        result["total_cost_usd"] = float(row["total_cost_usd"]) if row["total_cost_usd"] is not None else 0.0
        result["today_cost_usd"] = float(row["today_cost_usd"]) if row["today_cost_usd"] is not None else 0.0

        if current_user.is_super_admin:
            tenant_origin_clause = "" if origin == "all" else " AND c.origin = :origin"
            by_tenant_rows = await db.fetch_all(
                f"""
                SELECT t.id AS tenant_id, t.name AS tenant_name,
                       COUNT(c.id) AS calls_count,
                       SUM(c.cost_usd) FILTER (WHERE c.cost_usd IS NOT NULL) AS cost_usd,
                       SUM(c.billable_audio_seconds) FILTER (WHERE c.billable_audio_seconds IS NOT NULL) AS billable_audio_seconds
                FROM tenants t
                LEFT JOIN calls c ON c.tenant_id = t.id{tenant_origin_clause}
                GROUP BY t.id, t.name
                HAVING COUNT(c.id) > 0
                ORDER BY cost_usd DESC NULLS LAST
                """,
                {"origin": origin} if origin != "all" else {},
            )
            result["by_tenant"] = [
                {
                    "tenant_id": str(r["tenant_id"]),
                    "tenant_name": r["tenant_name"],
                    "calls_count": r["calls_count"],
                    "cost_usd": float(r["cost_usd"]) if r["cost_usd"] is not None else 0.0,
                    "minutes_used": round((r["billable_audio_seconds"] or 0) / 60, 2),
                }
                for r in by_tenant_rows
            ]
        if not current_user.is_super_admin and current_user.tenant_id:
            tenant_row = await db.fetch_one(
                "SELECT settings FROM tenants WHERE id = :id", {"id": str(current_user.tenant_id)},
            )
            included_minutes = None
            if tenant_row and tenant_row["settings"]:
                settings = tenant_row["settings"]
                if isinstance(settings, str):
                    settings = json.loads(settings)
                included_minutes = (settings or {}).get("included_minutes")
            result["minutes_included"] = included_minutes
            result["percent_used"] = (
                round(min(result["minutes_used"] / included_minutes, 1.0) * 100, 1)
                if included_minutes else None
            )
    else:
        included_minutes = None
        tenant_row = await db.fetch_one(
            "SELECT settings FROM tenants WHERE id = :id", {"id": str(current_user.tenant_id)},
        )
        if tenant_row and tenant_row["settings"]:
            settings = tenant_row["settings"]
            if isinstance(settings, str):
                settings = json.loads(settings)
            included_minutes = (settings or {}).get("included_minutes")

        result["minutes_included"] = included_minutes
        result["percent_used"] = (
            round(min(result["minutes_used"] / included_minutes, 1.0) * 100, 1)
            if included_minutes else None
        )

    result["can_view_costs"] = can_view_costs
    return result


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
    can_view_costs = await _can_view_costs(db, current_user)

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
            # Solo super_admin, stesso motivo di list_calls sopra.
            "billable_audio_seconds": call["billable_audio_seconds"] if can_view_costs else None,
            "cost_usd": (
                float(call["cost_usd"])
                if can_view_costs and call["cost_usd"] is not None
                else None
            ),
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
            "can_view_costs": can_view_costs,
            "origin": call["origin"] or "production",
            "channel": call["channel"],
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
