"""
FastAPI endpoints used by ElevenLabs agents provisioned from Ascolta projects.
"""

from __future__ import annotations

import logging
import json
import hashlib
import hmac
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict
from uuid import UUID, uuid4

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request
from pydantic import BaseModel, Field

from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.services.credentials.manager import CredentialsManager
from app.services import elevenlabs_provisioning

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/elevenlabs", tags=["ElevenLabs"])

_controller = None


class ElevenLabsLlmUpdate(BaseModel):
    llm: str = Field(min_length=1, max_length=200)


def _elevenlabs_webhook_signature_is_valid(raw_body: bytes, signature: str | None) -> bool:
    """Validate ElevenLabs' ``t=<unix>,v0=<hmac>`` webhook signature."""
    secret = os.environ.get("ELEVENLABS_POST_CALL_WEBHOOK_SECRET", "").strip()
    if not secret or not signature:
        return False
    parts = {}
    for piece in signature.split(","):
        key, separator, value = piece.strip().partition("=")
        if separator:
            parts[key] = value
    timestamp = parts.get("t")
    received_digest = parts.get("v0")
    if not timestamp or not received_digest:
        return False
    try:
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except ValueError:
        return False
    expected_digest = hmac.new(
        secret.encode("utf-8"),
        timestamp.encode("utf-8") + b"." + raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected_digest, received_digest)


def _elevenlabs_phone_number(metadata: dict[str, Any]) -> str:
    phone_call = metadata.get("phone_call")
    if isinstance(phone_call, dict):
        for key in ("external_number", "caller_number", "from_number", "to_number"):
            value = phone_call.get(key)
            if value:
                return str(value)
    return "simulatore ElevenLabs"


def _elevenlabs_started_at(metadata: dict[str, Any], event_timestamp: Any, duration_seconds: int) -> datetime:
    raw_start = metadata.get("start_time_unix_secs") or event_timestamp
    try:
        started_at = datetime.fromtimestamp(float(raw_start), tz=timezone.utc)
        return started_at if metadata.get("start_time_unix_secs") else started_at - timedelta(seconds=duration_seconds)
    except (TypeError, ValueError, OSError):
        return datetime.now(timezone.utc) - timedelta(seconds=duration_seconds)


async def _store_elevenlabs_call(payload: dict[str, Any], project_id: UUID | None = None) -> dict[str, Any]:
    """Persist one completed ElevenLabs conversation in the normal call history."""
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    conversation_id = str(data.get("conversation_id") or "").strip()
    agent_id = str(data.get("agent_id") or "").strip()
    if not conversation_id or not agent_id:
        raise HTTPException(status_code=400, detail="Missing ElevenLabs conversation_id or agent_id")

    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        project_filter = "AND p.id = :project_id" if project_id else ""
        params: dict[str, Any] = {"agent_id": agent_id}
        if project_id:
            params["project_id"] = str(project_id)
        project = await db.fetch_one(
            f"""
            SELECT p.id, p.tenant_id, av.id AS agent_version_id
            FROM projects p
            LEFT JOIN agent_versions av
              ON av.project_id = p.id AND av.status = 'published'
            WHERE p.elevenlabs_agent_id = :agent_id
              AND p.is_active = TRUE {project_filter}
            """,
            params,
        )
        if not project or not project["tenant_id"]:
            raise HTTPException(status_code=404, detail="No Ascolta project matches this ElevenLabs agent")

        existing = await db.fetch_one(
            "SELECT id, origin FROM calls WHERE openai_session_id = :conversation_id",
            {"conversation_id": conversation_id},
        )
        if existing and (existing["origin"] or "production") != "voice_simulation":
            return {"status": "already_recorded", "call_id": str(existing["id"]), "conversation_id": conversation_id}

        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        try:
            duration_seconds = max(0, round(float(metadata.get("call_duration_secs") or 0)))
        except (TypeError, ValueError):
            duration_seconds = 0
        started_at = _elevenlabs_started_at(metadata, payload.get("event_timestamp"), duration_seconds)
        ended_at = started_at + timedelta(seconds=duration_seconds)
        call_id = existing["id"] if existing else uuid4()
        call_values = {
            "id": str(call_id),
            "phone_number": _elevenlabs_phone_number(metadata),
            "conversation_id": conversation_id,
            "started_at": started_at,
            "ended_at": ended_at,
            "duration_seconds": duration_seconds,
            "project_id": str(project["id"]),
            "tenant_id": str(project["tenant_id"]),
            "agent_version_id": str(project["agent_version_id"]) if project["agent_version_id"] else None,
            "session_model": str(metadata.get("model") or "eleven_v3_conversational"),
        }
        if existing:
            await db.execute(
                """
                UPDATE calls
                SET phone_number = :phone_number, status = 'completed', consent_given = true,
                    started_at = :started_at, ended_at = :ended_at,
                    project_id = :project_id, tenant_id = :tenant_id,
                    agent_version_id = :agent_version_id, session_model = :session_model
                WHERE id = :id
                """,
                call_values,
            )
        else:
            await db.execute(
                """
                INSERT INTO calls (
                    id, phone_number, status, consent_given, openai_session_id,
                    started_at, ended_at, duration_seconds, project_id, tenant_id,
                    agent_version_id, voice_engine, direction, session_model, origin
                ) VALUES (
                    :id, :phone_number, 'completed', true, :conversation_id,
                    :started_at, :ended_at, :duration_seconds, :project_id, :tenant_id,
                    :agent_version_id, 'elevenlabs_agent', 'inbound', :session_model, 'production'
                )
                """,
                call_values,
            )
        transcript = data.get("transcript") if isinstance(data.get("transcript"), list) else []
        for turn in transcript:
            if not isinstance(turn, dict):
                continue
            raw_role = str(turn.get("role") or turn.get("speaker") or "").lower()
            role = "assistant" if raw_role in {"agent", "assistant", "ai"} else "user"
            content = str(turn.get("message") or turn.get("text") or turn.get("content") or "").strip()
            if not content:
                continue
            try:
                offset = float(turn.get("time_in_call_secs") or 0)
            except (TypeError, ValueError):
                offset = 0
            await db.execute(
                """
                INSERT INTO transcripts (call_id, role, content, timestamp)
                VALUES (:call_id, :role, :content, :timestamp)
                """,
                {"call_id": str(call_id), "role": role, "content": content, "timestamp": started_at + timedelta(seconds=max(0, offset))},
            )
    logger.info("ElevenLabs call stored conversation_id=%s call_id=%s", conversation_id, call_id)
    return {"status": "stored", "call_id": str(call_id), "conversation_id": conversation_id}


def _get_controller():
    global _controller
    if _controller is None:
        from runtime_workers.realtime_service import LegacyController

        _controller = LegacyController()
    return _controller


async def _resolve_project_context(project_id: UUID) -> dict[str, str]:
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        row = await db.fetch_one(
            "SELECT id, tenant_id FROM projects WHERE id = :id",
            {"id": str(project_id)},
        )
    if not row or not row["tenant_id"]:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"project_id": str(row["id"]), "tenant_id": str(row["tenant_id"])}


async def _check_project_access(project_id: UUID, current_user: CurrentUser) -> dict[str, str]:
    ctx = await _resolve_project_context(project_id)
    tenant_id = UUID(ctx["tenant_id"])
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=403, detail="Access denied to this project")
    return ctx


async def _assert_tool_secret(project_id: UUID, provided: str | None) -> dict[str, str]:
    ctx = await _resolve_project_context(project_id)
    creds = await CredentialsManager().get_credentials_with_fallback(
        UUID(ctx["tenant_id"]),
        None,
        "tts",
        "elevenlabs_agent",
    )
    expected = (creds.get("tool_secret") or "").strip()
    if not expected or not provided or provided.strip() != expected:
        raise HTTPException(status_code=403, detail="Invalid ElevenLabs tool secret")
    return ctx


async def _elevenlabs_api_key(tenant_id: str) -> str:
    manager = CredentialsManager()
    creds = await manager.get_credentials_with_fallback(
        UUID(tenant_id), None, "tts", "elevenlabs_agent"
    )
    if not creds.get("api_key"):
        creds = await manager.get_credentials_with_fallback(
            UUID(tenant_id), None, "tts", "elevenlabs"
        )
    api_key = (creds.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="No ElevenLabs credential configured for this tenant")
    return api_key


@router.get("/manifest")
async def get_manifest() -> Dict[str, Any]:
    return {
        "status": "ok",
        "toolsBaseUrl": "/api/elevenlabs/projects/{project_id}/tools/{tool_name}",
        "authHeader": "X-Tool-Secret",
    }


@router.post("/projects/{project_id}/signed-url")
async def get_signed_url(
    project_id: UUID = Path(...),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
) -> Dict[str, Any]:
    ctx = await _check_project_access(project_id, current_user)
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        project = await db.fetch_one(
            """
            SELECT id, name, voice_engine, elevenlabs_agent_id
            FROM projects
            WHERE id = :id
            """,
            {"id": str(project_id)},
        )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if (project["voice_engine"] or "").strip() != "elevenlabs_agent":
        raise HTTPException(status_code=400, detail="Project is not configured for ElevenLabs Agent")

    agent_id = (project["elevenlabs_agent_id"] or "").strip()
    if not agent_id:
        raise HTTPException(status_code=400, detail="ElevenLabs agent not provisioned for this project")

    creds = await CredentialsManager().get_credentials_with_fallback(
        UUID(ctx["tenant_id"]),
        None,
        "tts",
        "elevenlabs_agent",
    )
    if not creds.get("api_key"):
        creds = await CredentialsManager().get_credentials_with_fallback(
            UUID(ctx["tenant_id"]),
            None,
            "tts",
            "elevenlabs",
        )
    api_key = (creds.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="No ElevenLabs credential configured for this tenant")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            # Eleven returns a stable conversation id when requested. It
            # lets the browser display the same tool trace that Eleven used
            # internally for this exact simulator session.
            params={"agent_id": agent_id, "include_conversation_id": "true"},
            headers={"xi-api-key": api_key},
        )
    if response.status_code >= 300:
        logger.error("ElevenLabs signed URL failed project=%s status=%s body=%s", project_id, response.status_code, response.text)
        raise HTTPException(status_code=502, detail="Failed to create ElevenLabs signed URL")

    body = response.json() if response.content else {}
    signed_url = body.get("signed_url")
    if not signed_url:
        raise HTTPException(status_code=502, detail="ElevenLabs returned no signed URL")
    conversation_id = body.get("conversation_id")
    if conversation_id:
        await db.execute(
            """
            INSERT INTO calls (
                id, phone_number, status, consent_given, openai_session_id,
                started_at, project_id, tenant_id, voice_engine, direction,
                session_model, origin, channel
            )
            SELECT :id, 'browser-simulation', 'in_progress', true, :conversation_id,
                   :started_at, :project_id, :tenant_id, 'elevenlabs_agent',
                   'inbound', 'eleven_v3_conversational', 'voice_simulation', 'browser'
            WHERE NOT EXISTS (
                SELECT 1 FROM calls WHERE openai_session_id = :conversation_id
            )
            """,
            {
                "id": str(uuid4()),
                "conversation_id": str(conversation_id),
                "started_at": datetime.now(timezone.utc),
                "project_id": str(project_id),
                "tenant_id": str(ctx["tenant_id"]),
            },
        )
    return {
        "status": "ok",
        "signed_url": signed_url,
        "agent_id": agent_id,
        "conversation_id": conversation_id,
    }


@router.get("/projects/{project_id}/llms")
async def list_project_llms(
    project_id: UUID = Path(...),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
) -> Dict[str, Any]:
    """Expose exactly the models available to this tenant's Eleven workspace."""
    ctx = await _check_project_access(project_id, current_user)
    api_key = await _elevenlabs_api_key(ctx["tenant_id"])
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.elevenlabs.io/v1/convai/llm/list",
            headers={"xi-api-key": api_key},
        )
    if response.status_code >= 300:
        logger.error("ElevenLabs LLM list failed project=%s status=%s", project_id, response.status_code)
        raise HTTPException(status_code=502, detail="Failed to retrieve ElevenLabs LLMs")
    return response.json() if response.content else {"llms": []}


@router.put("/projects/{project_id}/llm")
async def set_project_llm(
    body: ElevenLabsLlmUpdate,
    project_id: UUID = Path(...),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
) -> Dict[str, Any]:
    """Persist a selected Eleven model and provision it on the live agent."""
    ctx = await _check_project_access(project_id, current_user)
    api_key = await _elevenlabs_api_key(ctx["tenant_id"])
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            "https://api.elevenlabs.io/v1/convai/llm/list",
            headers={"xi-api-key": api_key},
        )
    available = {
        str(item.get("llm"))
        for item in (response.json().get("llms") if response.status_code < 300 else [])
        if item.get("llm")
    }
    llm = body.llm.strip()
    if llm not in available:
        raise HTTPException(status_code=400, detail="LLM is not available in this ElevenLabs workspace")

    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        project = await db.fetch_one(
            "SELECT voice_engine, voice_provider_config FROM projects WHERE id = :id",
            {"id": str(project_id)},
        )
        if not project or project["voice_engine"] != "elevenlabs_agent":
            raise HTTPException(status_code=400, detail="Project is not configured for ElevenLabs Agent")
        provider_config = project["voice_provider_config"]
        if isinstance(provider_config, str):
            provider_config = json.loads(provider_config or "{}")
        provider_config = provider_config if isinstance(provider_config, dict) else {}
        eleven_config = provider_config.get("elevenlabs") if isinstance(provider_config.get("elevenlabs"), dict) else {}
        eleven_config["llm"] = llm
        provider_config["elevenlabs"] = eleven_config
        await db.execute(
            "UPDATE projects SET voice_provider_config = :config, updated_at = NOW() WHERE id = :id",
            {"id": str(project_id), "config": json.dumps(provider_config)},
        )

    try:
        result = await elevenlabs_provisioning.provision_agent_for_project(project_id)
    except Exception as exc:
        logger.exception("ElevenLabs LLM provisioning failed project=%s", project_id)
        raise HTTPException(status_code=502, detail=f"Failed to update ElevenLabs agent: {exc}") from exc
    return {"status": "updated", "llm": result["llm"], "agent_id": result["agent_id"]}


@router.get("/projects/{project_id}/conversations/{conversation_id}/tool-trace")
async def get_tool_trace(
    project_id: UUID = Path(...),
    conversation_id: str = Path(..., min_length=1, max_length=200),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
) -> Dict[str, Any]:
    """Return the tool calls that Eleven recorded for one simulator session."""
    ctx = await _check_project_access(project_id, current_user)
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        project = await db.fetch_one(
            "SELECT elevenlabs_agent_id FROM projects WHERE id = :id",
            {"id": str(project_id)},
        )
    if not project or not project["elevenlabs_agent_id"]:
        raise HTTPException(status_code=404, detail="ElevenLabs agent not provisioned for this project")

    creds = await CredentialsManager().get_credentials_with_fallback(
        UUID(ctx["tenant_id"]), None, "tts", "elevenlabs_agent"
    )
    if not creds.get("api_key"):
        creds = await CredentialsManager().get_credentials_with_fallback(
            UUID(ctx["tenant_id"]), None, "tts", "elevenlabs"
        )
    api_key = (creds.get("api_key") or "").strip()
    if not api_key:
        raise HTTPException(status_code=400, detail="No ElevenLabs credential configured for this tenant")

    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"https://api.elevenlabs.io/v1/convai/conversations/{conversation_id}",
            headers={"xi-api-key": api_key},
        )
    if response.status_code == 404:
        return {"status": "pending", "tool_calls": []}
    if response.status_code >= 300:
        logger.error("ElevenLabs tool trace failed conversation=%s status=%s", conversation_id, response.status_code)
        raise HTTPException(status_code=502, detail="Failed to read ElevenLabs conversation trace")

    conversation = response.json() if response.content else {}
    if conversation.get("agent_id") != project["elevenlabs_agent_id"]:
        raise HTTPException(status_code=403, detail="Conversation does not belong to this project")

    tool_calls: list[dict[str, Any]] = []
    for turn in conversation.get("transcript") or []:
        for item in turn.get("tool_results") or []:
            raw_result = item.get("result_value") or "{}"
            try:
                result = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
            except json.JSONDecodeError:
                result = {"status": "unreadable"}
            nested_result = result.get("result") if isinstance(result, dict) else {}
            tool_calls.append(
                {
                    "request_id": item.get("request_id"),
                    "name": (
                        item.get("tool_name") or result.get("tool")
                        if isinstance(result, dict)
                        else "tool"
                    ),
                    "status": nested_result.get("status") if isinstance(nested_result, dict) else item.get("is_error") and "error" or "ok",
                    "arguments": {},
                    "result": result,
                }
            )
    return {"status": "ok", "tool_calls": tool_calls}


@router.post("/projects/{project_id}/tools/{tool_name}")
async def execute_tool(
    request: Request,
    project_id: UUID = Path(...),
    tool_name: str = Path(...),
    x_tool_secret: str | None = Header(None, alias="X-Tool-Secret"),
) -> Dict[str, Any]:
    ctx = await _assert_tool_secret(project_id, x_tool_secret)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    arguments = body.get("arguments")
    if arguments is None:
        arguments = body
    if not isinstance(arguments, dict):
        arguments = {}

    for key in ("caller_phone", "caller_id", "system__caller_id", "phone"):
        if key in body and key not in arguments:
            arguments[key] = body.get(key)
    metadata = body.get("metadata")
    if isinstance(metadata, dict):
        for key in ("caller_phone", "caller_id", "system__caller_id", "phone"):
            if key in metadata and key not in arguments:
                arguments[key] = metadata.get(key)

    call_id = body.get("call_id")
    controller = _get_controller()
    try:
        result = await controller.call_tool(
            tool_name,
            arguments,
            call_id=call_id,
            project_id=ctx["project_id"],
            tenant_id=ctx["tenant_id"],
        )
    except Exception as exc:
        logger.exception("ElevenLabs tool failed: project=%s tool=%s", project_id, tool_name)
        raise HTTPException(status_code=500, detail=str(exc))
    return {"status": "ok", "tool": tool_name, "result": result}


@router.post("/projects/{project_id}/post-call")
async def store_post_call(
    request: Request,
    project_id: UUID = Path(...),
    x_tool_secret: str | None = Header(None, alias="X-Tool-Secret"),
) -> Dict[str, Any]:
    ctx = await _assert_tool_secret(project_id, x_tool_secret)
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}
    body.setdefault("metadata", {})
    if isinstance(body["metadata"], dict):
        body["metadata"].setdefault("project_id", ctx["project_id"])
        body["metadata"].setdefault("tenant_id", ctx["tenant_id"])
    return await _store_elevenlabs_call(body, project_id)


@router.post("/post-call")
async def receive_workspace_post_call(
    request: Request,
    elevenlabs_signature: str | None = Header(None, alias="ElevenLabs-Signature"),
) -> Dict[str, Any]:
    """Receive the workspace-wide, HMAC-signed ElevenLabs post-call event."""
    raw_body = await request.body()
    if not _elevenlabs_webhook_signature_is_valid(raw_body, elevenlabs_signature):
        raise HTTPException(status_code=401, detail="Invalid ElevenLabs webhook signature")
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Invalid webhook payload")
    if body.get("type") != "post_call_transcription":
        return {"status": "ignored", "event_type": body.get("type")}
    return await _store_elevenlabs_call(body)
