"""
Ascolta - Outbound Call Router
M5: API endpoints for initiating and managing outbound calls.
"""

import logging
from datetime import datetime
from typing import Any, Dict
from uuid import UUID, uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.config import get_settings
from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.models.schemas import (
    CallStatus,
    OutboundCallRequest,
    OutboundCallResponse,
    OutboundCallStatusResponse,
)
from app.services.telephony.twilio_client import normalize_phone_number, validate_e164
from app.services.voice.base import OutboundCallRequest as VoiceOutboundRequest
from app.services.voice.factory import get_voice_engine
from app.services.demo_showcase import is_demo_tenant

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/outbound")


@router.post("/call", response_model=OutboundCallResponse)
async def create_outbound_call(
    request: OutboundCallRequest,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> OutboundCallResponse:
    """
    Initiate a new outbound call.

    The call is placed via the voice engine configured for the project
    (currently Vapi + Twilio). The call lifecycle is managed asynchronously.
    """
    settings = get_settings()
    db = get_database()

    # 1. Validate phone number
    phone = normalize_phone_number(request.phone_number)
    if not phone:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid phone number format: {request.phone_number}. Use E.164 format (e.g. +4915123456789)",
        )

    # 2. Load project configuration
    project = await db.fetch_one(
        """
        SELECT id, tenant_id, name, voice_engine, call_direction, prompt_a, language,
               voice_name, vapi_assistant_id, twilio_phone_number,
               vapi_phone_number_id, elevenlabs_voice_id, is_active
        FROM projects
        WHERE id = :project_id
        """,
        {"project_id": str(request.project_id)},
    )

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Without this check, any creator/admin could place an outbound call
    # (and spend money, and use its credentials) against a project belonging
    # to a different tenant, just by knowing/guessing its project_id.
    if not check_tenant_access(current_user, project["tenant_id"]):
        raise HTTPException(status_code=404, detail="Project not found")

    if is_demo_tenant(project["tenant_id"]):
        raise HTTPException(status_code=403, detail="Demo projects cannot place calls")

    if not project["is_active"]:
        raise HTTPException(status_code=400, detail="Project is not active")

    # 3. Verify project supports outbound
    voice_engine = project["voice_engine"] or "xai_sip_direct"
    call_direction = project["call_direction"] or "inbound"

    if call_direction == "inbound":
        raise HTTPException(
            status_code=400,
            detail="Project is configured for inbound calls only. Update call_direction to 'outbound' or 'both'.",
        )

    if voice_engine == "openai_realtime":
        raise HTTPException(
            status_code=400,
            detail="OpenAI Realtime engine does not support outbound calls. Configure the project to use 'vapi' engine.",
        )

    # 4. Create call record in DB
    call_id = uuid4()
    await db.execute(
        """
        INSERT INTO calls (id, phone_number, status, project_id, tenant_id, voice_engine, direction, started_at)
        VALUES (:id, :phone_number, :status, :project_id, :tenant_id, :voice_engine, :direction, :started_at)
        """,
        {
            "id": str(call_id),
            "phone_number": phone,
            "status": CallStatus.PENDING_CONSENT.value,
            "project_id": str(request.project_id),
            "tenant_id": str(project["tenant_id"]) if project["tenant_id"] else None,
            "voice_engine": voice_engine,
            "direction": "outbound",
            "started_at": datetime.utcnow(),
        },
    )

    # 5. Initiate outbound call via voice engine
    engine = get_voice_engine(voice_engine)

    voice_request = VoiceOutboundRequest(
        phone_number=phone,
        project_id=request.project_id,
        prompt=project["prompt_a"],
        voice_name=project["voice_name"],
        language=project["language"] or "de",
        vapi_assistant_id=project["vapi_assistant_id"],
        twilio_phone_number=project["twilio_phone_number"] or settings.twilio_phone_number,
        metadata={
            "call_id": str(call_id),
            "project_id": str(request.project_id),
            **(request.metadata or {}),
        },
    )

    result = await engine.start_outbound_call(voice_request)

    if not result.success:
        # Mark call as failed
        await db.execute(
            """
            UPDATE calls SET status = 'declined', ended_at = :ended_at
            WHERE id = :id
            """,
            {"id": str(call_id), "ended_at": datetime.utcnow()},
        )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to initiate outbound call: {result.error_message}",
        )

    # 6. Update call with provider IDs
    update_fields = {"id": str(call_id)}
    set_clauses = []

    if result.provider_call_id:
        set_clauses.append("vapi_call_id = :vapi_call_id")
        update_fields["vapi_call_id"] = result.provider_call_id

    if set_clauses:
        await db.execute(
            f"UPDATE calls SET {', '.join(set_clauses)} WHERE id = :id",
            update_fields,
        )

    logger.info(
        f"Outbound call initiated: {call_id} → {phone} via {voice_engine}"
    )

    return OutboundCallResponse(
        success=True,
        call_id=call_id,
        provider_call_id=result.provider_call_id,
        message=f"Outbound call initiated to {phone}",
        voice_engine=voice_engine,
    )


@router.get("/call/{call_id}/status", response_model=OutboundCallStatusResponse)
async def get_outbound_call_status(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
) -> OutboundCallStatusResponse:
    """Get the status of an outbound call."""
    db = get_database()

    call = await db.fetch_one(
        """
        SELECT id, phone_number, status, voice_engine, direction, tenant_id,
               vapi_call_id, started_at, ended_at, duration_seconds
        FROM calls
        WHERE id = :id AND direction = 'outbound'
        """,
        {"id": str(call_id)},
    )

    if not call or not check_tenant_access(current_user, call["tenant_id"]):
        raise HTTPException(status_code=404, detail="Outbound call not found")

    return OutboundCallStatusResponse(
        call_id=call["id"],
        status=call["status"],
        direction="outbound",
        voice_engine=call["voice_engine"],
        vapi_call_id=call["vapi_call_id"],
        phone_number=call["phone_number"],
        started_at=call["started_at"],
        ended_at=call["ended_at"],
        duration_seconds=call["duration_seconds"],
    )


@router.post("/call/{call_id}/hangup")
async def hangup_outbound_call(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> Dict[str, Any]:
    """Terminate an active outbound call."""
    db = get_database()

    call = await db.fetch_one(
        """
        SELECT id, voice_engine, vapi_call_id, status, tenant_id
        FROM calls
        WHERE id = :id AND direction = 'outbound'
        """,
        {"id": str(call_id)},
    )

    if not call or not check_tenant_access(current_user, call["tenant_id"]):
        raise HTTPException(status_code=404, detail="Outbound call not found")

    if call["status"] in (CallStatus.COMPLETED.value, CallStatus.PROCESSED.value, CallStatus.DECLINED.value):
        return {"status": "already_ended", "call_id": str(call_id)}

    voice_engine = call["voice_engine"] or "vapi"
    engine = get_voice_engine(voice_engine)

    success = await engine.end_call(
        call_id=call_id,
        provider_call_id=call["vapi_call_id"],
    )

    if success:
        await db.execute(
            """
            UPDATE calls SET status = :status, ended_at = COALESCE(ended_at, :ended_at)
            WHERE id = :id
            """,
            {
                "id": str(call_id),
                "status": CallStatus.COMPLETED.value,
                "ended_at": datetime.utcnow(),
            },
        )

    return {
        "status": "ended" if success else "error",
        "call_id": str(call_id),
    }
