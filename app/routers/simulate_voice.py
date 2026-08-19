"""
Ascolta - Live voice simulation (WebSocket relay to xAI's realtime API).

maintainer, 19/08: "ma deve corrispondere al modello usato nella chiamata"
+ "io non dicevo una chat ma simulare la chiamata voce con un tastino
sul pannello" - the text-chat simulation (app/routers/simulation.py)
can't use the real voice model at all (verified live: both
"grok-voice-fast-1.0" and the actually-configured "grok-voice-latest"
return "Model not found" against the plain chat completions endpoint -
that model only exists behind the realtime WebSocket API). This module
uses that same realtime API directly, browser microphone in, browser
speaker out - the real model, not a substitute.

Confirmed via xAI's own docs before building this (WebFetch, not
guessed): wss://api.x.ai/v1/realtime?model=grok-voice-latest supports
direct client audio streaming (not just SIP/byo_trunk) -
input_audio_buffer.append (base64 PCM) in, response.output_audio.delta
(base64 PCM) out, server_vad for turn detection.

Architecture: browser <-> this WebSocket endpoint <-> xAI's realtime
WebSocket. The backend holds the tenant's xai API key (resolved the same
way as every other provider credential in this codebase - no env
fallback) and relays JSON events verbatim in both directions; the
browser never sees the API key. Uses the DRAFT prompt_a sent by the
browser on connect (same "test what's in the editor right now, not what
was last published" behavior as the text-chat simulation), not a saved/
published version.
"""

import asyncio
import json
import logging
from typing import Any, Optional
from urllib.parse import urlencode
from uuid import UUID

import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access
from app.services.agent_versions import resolve_provider_api_key
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)
router = APIRouter()

XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"


async def _authenticate(token: str) -> Optional[CurrentUser]:
    payload = AuthService().decode_token(token)
    if not payload or payload.get("type") != "access":
        return None
    return CurrentUser(
        id=UUID(payload["sub"]),
        email=payload["email"],
        role=payload["role"],
        tenant_id=UUID(payload["tenant_id"]) if payload.get("tenant_id") else None,
    )


@router.websocket("/ws/projects/{project_id}/simulate-voice")
async def simulate_voice(websocket: WebSocket, project_id: UUID, token: str = Query(...)) -> None:
    await websocket.accept()

    user = await _authenticate(token)
    if not user:
        await websocket.close(code=4401, reason="Invalid or expired token")
        return

    db = get_database()
    # WebSocket routes don't go through the FastAPI Depends() chain that
    # sets app.tenant_id/app.is_super_admin for HTTP requests
    # (get_current_user_rls_scoped) - without this, FORCE RLS on
    # `projects` denies every row and this always 404s. Same pattern as
    # every other pre-authenticated/system query in this codebase.
    async with db.transaction():
        if user.is_super_admin:
            await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        else:
            await db.execute("SELECT set_config('app.tenant_id', :t, true)", {"t": str(user.tenant_id)})
        project = await db.fetch_one(
            "SELECT tenant_id, voice_name, language FROM projects WHERE id = :id", {"id": str(project_id)},
        )
    if not project:
        await websocket.close(code=4404, reason="Project not found")
        return

    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not tenant_id or not check_tenant_access(user, tenant_id):
        await websocket.close(code=4403, reason="Access denied")
        return

    api_key = await resolve_provider_api_key(tenant_id, "xai")
    if not api_key:
        await websocket.close(code=4400, reason="No voice/xai credential configured for this tenant")
        return

    # Il primo messaggio del browser deve essere {"type": "start",
    # "instructions": "<prompt_a corrente nell'editor>"} - non un evento
    # dell'API realtime, solo il modo per passare il prompt da testare
    # prima di aprire la sessione vera.
    try:
        first_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        first = json.loads(first_raw)
    except (asyncio.TimeoutError, json.JSONDecodeError):
        await websocket.close(code=4400, reason="Expected a 'start' message with instructions")
        return
    if first.get("type") != "start" or not first.get("instructions"):
        await websocket.close(code=4400, reason="Expected a 'start' message with instructions")
        return
    instructions = first["instructions"]

    query = urlencode({"model": "grok-voice-latest"})
    xai_ws_url = f"{XAI_REALTIME_URL}?{query}"
    headers = {"Authorization": f"Bearer {api_key}"}

    try:
        async with websockets.connect(xai_ws_url, additional_headers=headers) as xai_ws:
            # Schema verificato localmente contro l'API reale prima di scriverlo
            # (19/08) - il tipo del messaggio ESTERNO e' "session.update",
            # "realtime" e' un campo DENTRO session (stesso errore preso e
            # corretto durante la verifica: con type:"realtime" a livello
            # esterno il server ignora silenziosamente il messaggio e
            # risponde solo con la sessione di default).
            await xai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": instructions,
                    "output_modalities": ["audio"],
                    "voice": project["voice_name"] or "Eve",
                    "turn_detection": {
                        "type": "server_vad",
                        "create_response": True,
                        "interrupt_response": True,
                    },
                    "audio": {
                        "input": {"format": {"type": "audio/pcm", "rate": 24000}},
                        "output": {"format": {"type": "audio/pcm", "rate": 24000}},
                    },
                },
            }))
            await websocket.send_text(json.dumps({"type": "ascolta.ready"}))

            async def browser_to_xai() -> None:
                while True:
                    raw = await websocket.receive_text()
                    await xai_ws.send(raw)

            async def xai_to_browser() -> None:
                async for raw in xai_ws:
                    await websocket.send_text(raw)

            done, pending = await asyncio.wait(
                [asyncio.create_task(browser_to_xai()), asyncio.create_task(xai_to_browser())],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed)):
                    logger.exception("simulate_voice relay task failed", exc_info=exc)

    except WebSocketDisconnect:
        logger.info(f"simulate_voice: browser disconnected (project={project_id})")
    except Exception as e:
        logger.exception(f"simulate_voice failed for project {project_id}: {e}")
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
