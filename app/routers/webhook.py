"""
Ascolta - Webhook Router
Handles incoming webhooks from OpenAI SIP gateway
"""

import logging
import httpx
import re
from datetime import datetime
from typing import Any, Dict
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.config import get_settings
from app.database.db import get_database
from app.models.schemas import CallStatus
from app.services.call_manager import CallManager
from app.services.realtime_session import DEFAULT_PROMPT_A

logger = logging.getLogger(__name__)
router = APIRouter()

# Global call manager instance
call_manager = CallManager()


@router.post("/webhook/call")
async def handle_call_webhook(
    request: Request,
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    Handle incoming call events from OpenAI SIP gateway.

    OpenAI sends webhooks for various call events:
    - call.started: New incoming call
    - call.ended: Call terminated
    - session.created: Realtime session established
    - input_audio_buffer.speech_started: User started speaking
    - response.done: AI finished responding
    - input.dtmf: DTMF tone received

    See: https://platform.openai.com/docs/guides/realtime-sip
    """
    settings = get_settings()

    try:
        # Parse the webhook payload
        payload = await request.json()
        logger.info(f"Received webhook: {payload.get('type', 'unknown')}")
        logger.debug(f"Webhook payload: {payload}")

        event_type = payload.get("type", "")

        # Log all events for debugging
        logger.info(f"[WEBHOOK DEBUG] event_type={event_type}")

        # Route based on event type
        if event_type in ("call.started", "session.created", "realtime.call.incoming"):
            return await handle_call_started(payload, background_tasks, event_type)

        elif event_type in ("call.ended", "realtime.call.ended"):
            return await handle_call_ended(payload, event_type)

        elif event_type in ("input.dtmf", "realtime.dtmf", "dtmf", "input_audio_buffer.dtmf"):
            return await handle_dtmf(payload, background_tasks)

        elif event_type == "conversation.item.created":
            return await handle_transcript_item(payload)

        elif event_type == "response.done":
            return await handle_response_done(payload)

        elif event_type == "error":
            return await handle_error(payload)

        else:
            # Log unknown event types for debugging
            # Elevate to INFO if it might be DTMF-related
            if "dtmf" in event_type.lower():
                logger.info(f"[UNHANDLED DTMF] Unknown DTMF event type: {event_type}, payload: {payload}")
            else:
                logger.debug(f"Unhandled event type: {event_type}")
            return {"status": "ignored", "event_type": event_type}

    except Exception as e:
        logger.error(f"Webhook processing error: {e}", exc_info=True)
        # Return 200 to prevent retries for processing errors
        return {"status": "error", "message": str(e)}




async def _accept_realtime_call(call_id: str, settings) -> None:
    """
    Accept an incoming SIP call via OpenAI Realtime API.
    """
    url = f"https://api.openai.com/v1/realtime/calls/{call_id}/accept"
    headers = {
        "Authorization": f"Bearer {settings.openai_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "type": "realtime",
        "model": settings.openai_realtime_model,
        "instructions": DEFAULT_PROMPT_A,
        "audio": {
            "input": {
                "format": {"type": "audio/pcma"},
                "transcription": {
                    "model": "whisper-1",
                    "language": "it",
                },
            },
            "output": {
                "format": {"type": "audio/pcma"},
                "voice": settings.openai_realtime_voice,
            },
        },
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, headers=headers, json=payload)
        if resp.status_code >= 300:
            raise RuntimeError(f"OpenAI call accept failed: {resp.status_code} {resp.text}")

async def handle_call_started(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks,
    event_type: str
) -> Dict[str, Any]:
    """
    Handle new incoming call.
    Creates a call record and initiates the conversation.
    """
    settings = get_settings()
    db = get_database()

    # Extract call information
    if event_type == "realtime.call.incoming":
        session_id = payload.get("data", {}).get("call_id")
    else:
        session_id = payload.get("session", {}).get("id") or payload.get("session_id")

    caller_number = (
        payload.get("call", {}).get("caller_number") or
        payload.get("caller_number") or
        payload.get("data", {}).get("from") or
        payload.get("data", {}).get("from_number") or
        payload.get("data", {}).get("caller_number") or
        payload.get("data", {}).get("caller") or
        "unknown"
    )
    if caller_number == "unknown" and event_type == "realtime.call.incoming":
        # Try to parse SIP From header for caller ID
        sip_headers = payload.get("data", {}).get("sip_headers") or []
        from_header = next((h for h in sip_headers if h.get("name") == "From"), None)
        if from_header and from_header.get("value"):
            match = re.search(r'sip:([^@;>]+)', from_header["value"])
            if match:
                caller_number = match.group(1)

    # Accept incoming SIP calls
    if event_type == "realtime.call.incoming":
        if not session_id:
            raise ValueError("Missing call_id in realtime.call.incoming payload")
        await _accept_realtime_call(session_id, settings)

    # Create call record
    call_id = uuid4()
    await db.execute(
        """
        INSERT INTO calls (id, phone_number, status, openai_session_id, started_at)
        VALUES (:id, :phone_number, :status, :session_id, :started_at)
        """,
        {
            "id": str(call_id),
            "phone_number": caller_number,
            "status": CallStatus.PENDING_CONSENT.value,
            "session_id": session_id,
            "started_at": datetime.utcnow(),
        }
    )

    logger.info(f"Call started: {call_id} from {caller_number}")

    # Start the call session in background
    background_tasks.add_task(
        call_manager.start_session,
        call_id=call_id,
        session_id=session_id,
    )

    return {
        "status": "accepted",
        "call_id": str(call_id),
        "session_id": session_id,
    }


async def handle_call_ended(payload: Dict[str, Any], event_type: str) -> Dict[str, Any]:
    """
    Handle call termination from OpenAI webhook.
    Updates the call record with end time. Duration is auto-calculated by database.
    Idempotent - safe to call multiple times.
    """
    db = get_database()

    if event_type == "realtime.call.ended":
        session_id = payload.get("data", {}).get("call_id")
    else:
        session_id = payload.get("session", {}).get("id") or payload.get("session_id")

    if not session_id:
        logger.warning("No session_id in call.ended webhook")
        return {"status": "error", "message": "Missing session_id"}

    try:
        # Find the call by session ID
        call = await db.fetch_one(
            """
            SELECT id, ended_at, status
            FROM calls
            WHERE openai_session_id = :session_id
            """,
            {"session_id": session_id}
        )

        if not call:
            logger.warning(f"Call not found for session: {session_id}")
            return {"status": "not_found"}

        # Calculate end time (use existing if already set)
        ended_at = call["ended_at"] or datetime.utcnow()

        # Determine final status (only if not already terminal)
        current_status = call["status"]
        if current_status in [CallStatus.IN_PROGRESS.value, CallStatus.CONSENTED.value]:
            new_status = CallStatus.COMPLETED.value
        elif current_status == CallStatus.PENDING_CONSENT.value:
            new_status = CallStatus.DECLINED.value
        else:
            new_status = current_status  # Preserve cancelled/declined/failed

        # Idempotent update - don't overwrite existing ended_at
        # Note: duration_seconds is automatically calculated by database
        await db.execute(
            """
            UPDATE calls
            SET ended_at = COALESCE(ended_at, :ended_at),
                status = :status
            WHERE id = :id
            """,
            {
                "id": str(call["id"]),
                "ended_at": ended_at,
                "status": new_status,
            }
        )

        logger.info(
            f"Webhook: Call {call['id']} ended, status: {new_status}"
        )

        # Clean up call manager session
        await call_manager.end_session(call["id"])

        return {
            "status": "updated",
            "call_id": str(call["id"]),
            "final_status": new_status,
        }

    except Exception as e:
        logger.error(f"Error handling call.ended webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def handle_dtmf(
    payload: Dict[str, Any],
    background_tasks: BackgroundTasks
) -> Dict[str, Any]:
    """
    Handle DTMF tone input.
    Key "9" triggers immediate cancellation and transcript deletion.
    """
    settings = get_settings()
    db = get_database()

    # Enhanced logging to diagnose DTMF issues
    logger.info(f"[DTMF DEBUG] Full payload: {payload}")

    # Try multiple extraction paths for digit
    digit = payload.get("digit")
    if digit is None:
        digit = payload.get("input", {}).get("digit")
    if digit is None:
        digit = payload.get("dtmf", {}).get("digit")
    if digit is None:
        digit = payload.get("data", {}).get("digit")
    if digit is None:
        digit = payload.get("event", {}).get("digit")

    # Try multiple extraction paths for session_id
    session_id = payload.get("session", {}).get("id")
    if not session_id:
        session_id = payload.get("session_id")
    if not session_id:
        session_id = payload.get("call_id")
    if not session_id:
        session_id = payload.get("data", {}).get("call_id")

    logger.info(f"[DTMF DEBUG] Extracted digit={digit}, session_id={session_id}")

    # Check if this is the cancel key
    if digit == settings.dtmf_cancel_key:
        # Find the call
        call = await db.fetch_one(
            "SELECT id FROM calls WHERE openai_session_id = :session_id",
            {"session_id": session_id}
        )

        if call:
            # Trigger immediate cancellation in background
            background_tasks.add_task(
                call_manager.handle_cancellation,
                call_id=call["id"],
                session_id=session_id,
            )

            return {
                "status": "cancellation_triggered",
                "call_id": str(call["id"]),
            }

    return {"status": "dtmf_received", "digit": digit}


async def handle_transcript_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle transcript items (conversation messages).
    Stores messages in the transcripts table.
    """
    db = get_database()

    session_id = payload.get("session", {}).get("id") or payload.get("session_id")
    item = payload.get("item", {})

    # Get role and content
    role = item.get("role", "user")
    content_parts = item.get("content", [])

    # Extract text content
    text_content = ""
    for part in content_parts:
        if part.get("type") == "text":
            text_content += part.get("text", "")
        elif part.get("type") == "input_text":
            text_content += part.get("text", "")
        elif part.get("type") == "input_audio":
            # Audio content - transcript might be in a different field
            text_content += part.get("transcript", "")

    if not text_content:
        return {"status": "no_content"}

    # Find the call
    call = await db.fetch_one(
        "SELECT id, consent_given FROM calls WHERE openai_session_id = :session_id",
        {"session_id": session_id}
    )

    if not call:
        logger.warning(f"Call not found for transcript: {session_id}")
        return {"status": "call_not_found"}

    # Only save transcripts if consent was given
    if not call["consent_given"]:
        logger.debug("Skipping transcript - no consent yet")
        return {"status": "consent_pending"}

    # Save transcript
    await db.execute(
        """
        INSERT INTO transcripts (call_id, role, content, timestamp)
        VALUES (:call_id, :role, :content, :timestamp)
        """,
        {
            "call_id": str(call["id"]),
            "role": role,
            "content": text_content,
            "timestamp": datetime.utcnow(),
        }
    )

    logger.debug(f"Transcript saved: {role}: {text_content[:50]}...")

    return {"status": "saved", "role": role}


async def handle_response_done(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle AI response completion.
    Used for tracking conversation progress.
    """
    session_id = payload.get("session", {}).get("id") or payload.get("session_id")
    response = payload.get("response", {})

    # Extract the response content for logging
    output = response.get("output", [])
    for item in output:
        content = item.get("content", [])
        for part in content:
            if part.get("type") == "audio":
                transcript = part.get("transcript", "")
                if transcript:
                    logger.debug(f"AI response: {transcript[:100]}...")

    return {"status": "response_processed"}


async def handle_error(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Handle error events from OpenAI.
    """
    error = payload.get("error", {})
    error_type = error.get("type", "unknown")
    error_message = error.get("message", "Unknown error")

    logger.error(f"OpenAI error: {error_type} - {error_message}")

    return {"status": "error_logged", "error_type": error_type}


@router.post("/webhook/test")
async def test_webhook(request: Request) -> Dict[str, Any]:
    """
    Test endpoint for webhook verification.
    Use this to verify webhook URL is accessible.
    """
    payload = await request.json() if request.headers.get("content-type") == "application/json" else {}
    return {
        "status": "ok",
        "message": "Webhook endpoint is working",
        "received": payload,
        "timestamp": datetime.utcnow().isoformat(),
    }
