"""
Ascolta - Calendar API Routes

Endpoints for calendar scheduling and appointment management.
"""

import logging
from typing import List
from uuid import UUID

from fastapi import APIRouter, HTTPException

from app.database.db import get_database
from app.models.schemas import (
    CalendarEventResponse,
    CalendarProvider,
    CalendarSlotResponse,
    CalendarSlotsResponse,
    CalendarTestConnectionRequest,
    CalendarTestConnectionResponse,
    ScheduleAppointmentRequest,
    ScheduleAppointmentResponse,
)
from app.services.calendar.base import CalendarSlot
from app.services.calendar.scheduler import CalendarScheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["Calendar"])


@router.get("/calls/{call_id}/slots", response_model=CalendarSlotsResponse)
async def get_available_slots(
    call_id: UUID,
    num_slots: int = 3,
):
    """
    Get available appointment slots for a call.

    Returns up to `num_slots` available time slots based on
    the project's calendar configuration.
    """
    scheduler = CalendarScheduler()

    try:
        slots = await scheduler.get_available_slots(call_id, num_slots)

        return CalendarSlotsResponse(
            call_id=call_id,
            slots=[
                CalendarSlotResponse(
                    start=slot.start,
                    end=slot.end,
                    duration_minutes=slot.duration_minutes,
                    display_text=slot.to_display_string("it"),
                )
                for slot in slots
            ],
            provider="google",  # TODO: Get from config
            calendar_enabled=len(slots) > 0,
        )

    except Exception as e:
        logger.error(f"Error getting slots for call {call_id}: {e}")
        return CalendarSlotsResponse(
            call_id=call_id,
            slots=[],
            calendar_enabled=False,
        )


@router.post("/schedule", response_model=ScheduleAppointmentResponse)
async def schedule_appointment(request: ScheduleAppointmentRequest):
    """
    Schedule an appointment for a call.

    Creates a calendar event at the specified time slot
    and sends invites to attendees.
    """
    db = get_database()
    scheduler = CalendarScheduler()

    # Get candidate data from record
    record = await db.fetch_one(
        """
        SELECT r.json_data, c.phone_number
        FROM records r
        JOIN calls c ON r.call_id = c.id
        WHERE r.call_id = :call_id
        """,
        {"call_id": str(request.call_id)},
    )

    if not record:
        raise HTTPException(
            status_code=404,
            detail="Record not found for this call"
        )

    import json
    json_data = record["json_data"]
    if isinstance(json_data, str):
        json_data = json.loads(json_data)

    candidate_data = {
        "candidate_name": json_data.get("candidate_name", "Candidato"),
        "email": json_data.get("email"),
        "phone_number": record["phone_number"],
        "role_targets": json_data.get("role_targets", []),
    }

    # Create slot
    slot = CalendarSlot(
        start=request.slot_start,
        end=request.slot_end,
        duration_minutes=int((request.slot_end - request.slot_start).seconds / 60),
    )

    # Schedule
    result = await scheduler.schedule_appointment(
        call_id=request.call_id,
        slot=slot,
        candidate_data=candidate_data,
        hr_email=request.hr_email,
    )

    return ScheduleAppointmentResponse(
        success=result.success,
        message="Appuntamento fissato" if result.success else (result.error_message or "Errore"),
        event_id=result.external_id,
        event_link=result.event_link,
        scheduled_at=slot.start if result.success else None,
    )


@router.delete("/calls/{call_id}/appointment")
async def cancel_appointment(
    call_id: UUID,
    notify_attendees: bool = True,
):
    """
    Cancel a scheduled appointment.

    Optionally notifies attendees of the cancellation.
    """
    scheduler = CalendarScheduler()

    result = await scheduler.cancel_appointment(
        call_id=call_id,
        notify_attendees=notify_attendees,
    )

    if not result.success:
        raise HTTPException(
            status_code=400,
            detail=result.error_message or "Failed to cancel appointment"
        )

    return {
        "success": True,
        "message": "Appuntamento annullato",
        "call_id": str(call_id),
    }


@router.get("/calls/{call_id}/event", response_model=CalendarEventResponse)
async def get_calendar_event(call_id: UUID):
    """
    Get calendar event details for a call.
    """
    db = get_database()

    event = await db.fetch_one(
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

    if not event:
        raise HTTPException(
            status_code=404,
            detail="No calendar event found for this call"
        )

    return CalendarEventResponse(**dict(event))


@router.get("/events", response_model=List[CalendarEventResponse])
async def list_calendar_events(
    status: str = None,
    limit: int = 50,
    offset: int = 0,
):
    """
    List calendar events with optional status filter.
    """
    db = get_database()

    params = {"limit": limit, "offset": offset}

    if status:
        query = """
            SELECT * FROM calendar_events
            WHERE status = :status
            ORDER BY scheduled_at DESC
            LIMIT :limit OFFSET :offset
        """
        params["status"] = status
    else:
        query = """
            SELECT * FROM calendar_events
            ORDER BY scheduled_at DESC
            LIMIT :limit OFFSET :offset
        """

    events = await db.fetch_all(query, params)
    return [CalendarEventResponse(**dict(e)) for e in events]


@router.post("/test-connection", response_model=CalendarTestConnectionResponse)
async def test_calendar_connection(request: CalendarTestConnectionRequest):
    """
    Test calendar connection with provided token.

    Validates that OAuth tokens are correct and the calendar is accessible.
    """
    scheduler = CalendarScheduler()

    try:
        success = await scheduler.test_connection(
            provider=request.provider.value,
            access_token=request.access_token,
            refresh_token=request.refresh_token,
        )

        return CalendarTestConnectionResponse(
            success=success,
            message="Connessione riuscita" if success else "Connessione fallita",
            provider=request.provider.value,
        )

    except Exception as e:
        logger.error(f"Calendar connection test error: {e}")
        return CalendarTestConnectionResponse(
            success=False,
            message=f"Errore: {str(e)}",
            provider=request.provider.value,
        )


@router.get("/providers")
async def list_calendar_providers():
    """
    List available calendar providers with their OAuth requirements.
    """
    return [
        {
            "name": "google",
            "display_name": "Google Calendar",
            "description": "Google Calendar via OAuth2",
            "oauth_url": "https://accounts.google.com/o/oauth2/v2/auth",
            "scopes": [
                "https://www.googleapis.com/auth/calendar",
                "https://www.googleapis.com/auth/calendar.events",
            ],
        },
        {
            "name": "microsoft",
            "display_name": "Microsoft 365 / Outlook",
            "description": "Outlook Calendar via Microsoft Graph API",
            "oauth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
            "scopes": [
                "https://graph.microsoft.com/Calendars.ReadWrite",
                "https://graph.microsoft.com/User.Read",
            ],
        },
    ]
