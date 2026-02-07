"""
Ascolta - Vapi Webhook Router
M5: Handles incoming webhooks from Vapi.ai for outbound calls.

Vapi sends webhooks for call lifecycle events:
- status-update: Call status changes (queued, ringing, in-progress, ended)
- end-of-call-report: Full call summary with transcript after completion
- transcript: Real-time transcript updates
- tool-calls: LLM wants to call a tool
- hang: Vapi detected conversation should end
"""

import logging
from datetime import datetime
from typing import Any, Dict
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Request

from app.config import get_settings
from app.database.db import get_database
from app.models.schemas import CallStatus
from app.services.voice.base import WebhookEventType
from app.services.voice.factory import get_voice_engine

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook/vapi")
async def handle_vapi_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, Any]:
    """
    Handle incoming webhooks from Vapi.ai.
    """
    try:
        payload = await request.json()
        message = payload.get("message", payload)
        msg_type = message.get("type", "unknown")

        logger.info(f"Vapi webhook received: {msg_type}")
        logger.debug(f"Vapi payload: {payload}")

        # Parse through the Vapi engine
        engine = get_voice_engine("vapi")
        result = await engine.handle_webhook(payload)

        # Find our internal call by Vapi call ID
        vapi_call_id = result.provider_call_id
        call = None
        if vapi_call_id:
            db = get_database()
            call = await db.fetch_one(
                "SELECT id, status, project_id FROM calls WHERE vapi_call_id = :vapi_call_id",
                {"vapi_call_id": vapi_call_id},
            )

        # Also try metadata fallback
        if not call and result.raw_payload:
            metadata = (
                message.get("call", {}).get("metadata", {})
                or message.get("metadata", {})
            )
            internal_call_id = metadata.get("call_id")
            if internal_call_id:
                db = get_database()
                call = await db.fetch_one(
                    "SELECT id, status, project_id FROM calls WHERE id = :id",
                    {"id": internal_call_id},
                )
                # Update vapi_call_id if we found the call
                if call and vapi_call_id:
                    await db.execute(
                        "UPDATE calls SET vapi_call_id = :vapi_call_id WHERE id = :id",
                        {"id": str(call["id"]), "vapi_call_id": vapi_call_id},
                    )

        # Route based on normalized event type
        if result.event_type == WebhookEventType.CALL_STARTED:
            return await _handle_call_started(call, result)

        elif result.event_type == WebhookEventType.CALL_ENDED:
            return await _handle_call_ended(call, result, background_tasks)

        elif result.event_type == WebhookEventType.TRANSCRIPT_UPDATE:
            return await _handle_transcript(call, result)

        elif result.event_type == WebhookEventType.CALL_FAILED:
            return await _handle_call_failed(call, result)

        else:
            logger.debug(f"Unhandled Vapi event: {msg_type}")
            return {"status": "ignored", "event_type": msg_type}

    except Exception as e:
        logger.error(f"Vapi webhook processing error: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


async def _handle_call_started(call, result) -> Dict[str, Any]:
    """Handle Vapi call started (in-progress status)."""
    if not call:
        logger.warning(f"Call not found for Vapi call: {result.provider_call_id}")
        return {"status": "call_not_found"}

    db = get_database()

    # Update status to in_progress (skip consent for outbound sales calls)
    await db.execute(
        """
        UPDATE calls
        SET status = :status, consent_given = TRUE, consent_timestamp = :now
        WHERE id = :id AND status = :pending_status
        """,
        {
            "id": str(call["id"]),
            "status": CallStatus.IN_PROGRESS.value,
            "now": datetime.utcnow(),
            "pending_status": CallStatus.PENDING_CONSENT.value,
        },
    )

    logger.info(f"Vapi call started: {call['id']}")
    return {"status": "accepted", "call_id": str(call["id"])}


async def _handle_call_ended(call, result, background_tasks) -> Dict[str, Any]:
    """
    Handle Vapi call ended.
    Process end-of-call-report if available (contains full transcript).
    """
    if not call:
        logger.warning(f"Call not found for Vapi call ended: {result.provider_call_id}")
        return {"status": "call_not_found"}

    db = get_database()
    call_id = call["id"]

    # Extract metadata from end-of-call-report
    messages = result.metadata.get("messages", [])
    duration = result.metadata.get("duration_seconds")
    ended_reason = result.metadata.get("ended_reason", "")

    # Save full transcript from end-of-call-report messages
    if messages:
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("message", "") or msg.get("content", "")
            if content and role in ("user", "assistant", "bot"):
                mapped_role = "assistant" if role == "bot" else role
                await db.execute(
                    """
                    INSERT INTO transcripts (call_id, role, content, timestamp)
                    VALUES (:call_id, :role, :content, :timestamp)
                    """,
                    {
                        "call_id": str(call_id),
                        "role": mapped_role,
                        "content": content,
                        "timestamp": datetime.utcnow(),
                    },
                )

    # Determine final status
    current_status = call["status"]
    if current_status in (CallStatus.PROCESSING.value, CallStatus.PROCESSED.value):
        new_status = current_status
    elif ended_reason in ("customer-did-not-answer", "customer-busy"):
        new_status = CallStatus.DECLINED.value
    else:
        new_status = CallStatus.COMPLETED.value

    # Update call record
    await db.execute(
        """
        UPDATE calls
        SET status = :status,
            ended_at = COALESCE(ended_at, :ended_at)
        WHERE id = :id
        """,
        {
            "id": str(call_id),
            "status": new_status,
            "ended_at": datetime.utcnow(),
        },
    )

    logger.info(f"Vapi call ended: {call_id}, status={new_status}, reason={ended_reason}")

    # Trigger post-processing if call completed successfully
    if new_status == CallStatus.COMPLETED.value:
        background_tasks.add_task(_post_process_call, call_id)

    return {
        "status": "updated",
        "call_id": str(call_id),
        "final_status": new_status,
    }


async def _handle_transcript(call, result) -> Dict[str, Any]:
    """Handle real-time transcript updates from Vapi."""
    if not call:
        return {"status": "call_not_found"}

    # Only save final transcripts, not partial
    transcript_type = result.metadata.get("transcript_type", "")
    if transcript_type == "partial":
        return {"status": "partial_ignored"}

    if result.transcript_text and result.transcript_role:
        db = get_database()
        await db.execute(
            """
            INSERT INTO transcripts (call_id, role, content, timestamp)
            VALUES (:call_id, :role, :content, :timestamp)
            """,
            {
                "call_id": str(call["id"]),
                "role": result.transcript_role,
                "content": result.transcript_text,
                "timestamp": datetime.utcnow(),
            },
        )

    return {"status": "transcript_saved"}


async def _handle_call_failed(call, result) -> Dict[str, Any]:
    """Handle call failure."""
    if not call:
        return {"status": "call_not_found"}

    db = get_database()
    await db.execute(
        """
        UPDATE calls
        SET status = 'declined', ended_at = COALESCE(ended_at, :ended_at)
        WHERE id = :id
        """,
        {"id": str(call["id"]), "ended_at": datetime.utcnow()},
    )

    logger.error(f"Vapi call failed: {call['id']}, error: {result.error_message}")
    return {"status": "failed", "call_id": str(call["id"])}


async def _post_process_call(call_id: UUID) -> None:
    """
    Trigger post-processing for a completed outbound call.
    Reuses the existing post-processing pipeline (GPT-4 extraction, PDF, email, CRM).
    """
    try:
        logger.info(f"Starting post-processing for outbound call {call_id}")

        db = get_database()

        # Update status to processing
        await db.execute(
            "UPDATE calls SET status = :status WHERE id = :id",
            {"id": str(call_id), "status": CallStatus.PROCESSING.value},
        )

        # 1. Extract JSON from transcript
        from app.services.post_processor import PostProcessor
        post_processor = PostProcessor()
        json_data = await post_processor.process_call(call_id)
        logger.info(f"JSON extraction completed for outbound call {call_id}")

        # 2. Generate PDF
        from app.services.pdf_generator import PDFGenerator
        pdf_generator = PDFGenerator()
        await pdf_generator.generate_and_upload_pdf(call_id, json_data)
        logger.info(f"PDF generated for outbound call {call_id}")

        # 3. Send email (if enabled)
        from app.services.email_service import EmailService
        email_service = EmailService()

        call_metadata = await db.fetch_one(
            "SELECT id, started_at, duration_seconds, phone_number FROM calls WHERE id = :id",
            {"id": str(call_id)},
        )

        if email_service.is_enabled():
            try:
                pdf_bytes = await pdf_generator.download_pdf(call_id)
                await email_service.send_candidate_report(
                    pdf_bytes=pdf_bytes,
                    json_data=json_data,
                    call_metadata=dict(call_metadata) if call_metadata else None,
                )
                logger.info(f"Email sent for outbound call {call_id}")
            except Exception as e:
                logger.error(f"Failed to send email for outbound call {call_id}: {e}")

        # 4. CRM sync (if enabled)
        try:
            from app.services.crm.dispatcher import CRMDispatcher
            crm_dispatcher = CRMDispatcher()
            await crm_dispatcher.dispatch(
                call_id=call_id,
                json_data=json_data,
                call_metadata=dict(call_metadata) if call_metadata else {},
            )
        except Exception as e:
            logger.error(f"CRM sync error for outbound call {call_id}: {e}")

        logger.info(f"Post-processing completed for outbound call {call_id}")

    except Exception as e:
        logger.error(f"Post-processing failed for outbound call {call_id}: {e}", exc_info=True)
