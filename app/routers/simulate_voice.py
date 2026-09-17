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
import time
from datetime import datetime, timezone
from typing import Any, Optional
from urllib.parse import urlencode
from uuid import UUID, uuid4

import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access
from app.services.agent_versions import resolve_provider_api_key
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)
router = APIRouter()

XAI_REALTIME_URL = "wss://api.x.ai/v1/realtime"

# maintainer, 19/08: "metti un timeout per la simulazione vocale, ad esempio
# 30s" - e' una prova, non una chiamata vera: senza un limite qualcuno
# potrebbe lasciarla aperta e consumare inutilmente il credito xAI del
# tenant. Applicato lato server (non solo in UI) cosi' vale anche se il
# browser si blocca o la tab resta in background.
#
# 19/08 (correzione): "i 30 secondi di timeout devono scattare dopo 30s
# di silenzio" - non un limite sulla durata totale della prova, un
# timeout di INATTIVITA' che si azzera ad ogni evento reale (l'utente
# parla, l'agente risponde, una tool call) - una prova puo' durare
# quanto serve finche' succede qualcosa.
SIMULATION_SILENCE_TIMEOUT_SECONDS = 30

# Stessa definizione di app/integrations/common/tools.py - copiata qui
# invece di importata per non dipendere dal sistema di flag di quel
# modulo (pensato per gli scenari da file statico, non per questa
# simulazione).
SEARCH_KB_TOOL = {
    "type": "function",
    "name": "search_knowledge_base",
    "description": "Search this organization's knowledge base (documents and crawled web pages configured by the admin) for information relevant to the caller's question - e.g. office hours, procedures, local regulations, services offered. Use this before saying you don't know something the organization may have documented.",
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question or topic to search for, in the caller's own words"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
}

TOOL_RESULT_WAIT_INSTRUCTIONS = (
    "Regola inderogabile: se la richiesta richiede il tool search_knowledge_base, "
    "non dire alcun fatto, indirizzo, orario, disponibilita' o conclusione prima "
    "di riceverne il risultato. Chiama il tool, attendi l'output e solo dopo "
    "rispondi usando quel risultato."
)


async def _handle_function_call(
    xai_ws: Any, websocket: WebSocket, event: dict, project_id: UUID, tenant_id: UUID,
) -> None:
    """Esegue la function call lato server e restituisce il risultato a xAI - stesso schema di conversation.item.create + function_call_output gia' usato in runtime_workers/realtime_service.py::handle_function_call. Notifica anche il browser (maintainer, 19/08: "potresti riportare la chiamata al tool e la risposta") - visibile in trascrizione, non solo eseguita in silenzio."""
    call_id = event.get("call_id")
    name = event.get("name")
    try:
        arguments = json.loads(event.get("arguments") or "{}")
    except json.JSONDecodeError:
        arguments = {}

    if name == "search_knowledge_base":
        from app.services.rag.search import search_knowledge_base

        try:
            results = await search_knowledge_base(project_id, tenant_id, arguments.get("query", ""), top_k=5)
            result = {"status": "ok", "results": results} if results else {"status": "no_results"}
        except ValueError as e:
            result = {"status": "unavailable", "message": str(e)}
    else:
        result = {"status": "error", "message": f"Unknown tool: {name}"}

    try:
        await websocket.send_text(json.dumps({
            "type": "ascolta.tool_call",
            "name": name,
            "arguments": arguments,
            "result": result,
        }))
    except Exception:
        pass  # non bloccare la chiamata vera se il browser ha gia' chiuso

    await xai_ws.send(json.dumps({
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": json.dumps(result, ensure_ascii=True),
        },
    }))
    await xai_ws.send(json.dumps({"type": "response.create"}))


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
            "SELECT tenant_id, voice_name, language, consent_message FROM projects WHERE id = :id",
            {"id": str(project_id)},
        )
        has_knowledge_base = bool(await db.fetch_val(
            """SELECT EXISTS(
                 SELECT 1 FROM kb_sources
                 WHERE project_id = :project_id
                   AND status IN ('completed', 'indexed', 'ready')
             )""",
            {"project_id": str(project_id)},
        )) if project else False
    if not project:
        await websocket.close(code=4404, reason="Project not found")
        return

    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not tenant_id or not check_tenant_access(user, tenant_id):
        await websocket.close(code=4403, reason="Access denied")
        return

    api_key = await resolve_provider_api_key(tenant_id, "xai", project_id=project_id)
    if not api_key:
        await websocket.close(
            code=4400,
            reason="Nessuna credenziale voice/xai o voice/openai per questo tenant o progetto",
        )
        return

    simulation_call_id = uuid4()
    simulation_started_at = datetime.now(timezone.utc)
    simulation_transcript: list[dict[str, str]] = []
    await db.execute(
        """
        INSERT INTO calls (
            id, phone_number, status, consent_given, started_at,
            project_id, tenant_id, voice_engine, direction, session_model,
            origin, channel
        ) VALUES (
            :id, 'browser-simulation', 'in_progress', true, :started_at,
            :project_id, :tenant_id, 'xai_sip_direct', 'inbound',
            'grok-voice-latest', 'voice_simulation', 'browser'
        )
        """,
        {
            "id": str(simulation_call_id),
            "started_at": simulation_started_at,
            "project_id": str(project_id),
            "tenant_id": str(tenant_id),
        },
    )

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
    instructions = f"{first['instructions']}\n\n{TOOL_RESULT_WAIT_INSTRUCTIONS}"

    query = urlencode({"model": "grok-voice-latest"})
    xai_ws_url = f"{XAI_REALTIME_URL}?{query}"
    headers = {"Authorization": f"Bearer {api_key}"}

    # La frase di apertura arriva dal browser (bozza corrente nell'editor,
    # non ancora salvata) - stesso trattamento di `instructions` sopra.
    # Fallback sul valore salvato solo se il browser non ne manda uno
    # (retrocompatibilita').
    consent_message = first.get("consent_message") or project["consent_message"] or "Salve, come posso aiutarla?"

    try:
        async with websockets.connect(xai_ws_url, additional_headers=headers) as xai_ws:
            # Schema verificato localmente contro l'API reale prima di scriverlo
            # (19/08) - il tipo del messaggio ESTERNO e' "session.update",
            # "realtime" e' un campo DENTRO session (stesso errore preso e
            # corretto durante la verifica: con type:"realtime" a livello
            # esterno il server ignora silenziosamente il messaggio e
            # risponde solo con la sessione di default).
            #
            # tools: solo search_knowledge_base (stessa definizione di
            # app/integrations/common/tools.py) - maintainer, 19/08: "pare
            # non funzionare la chiamata a RAG". Prima non c'era NESSUN
            # tool collegato qui (dichiarato in UI ma probabilmente non
            # notato) - il modello non aveva letteralmente nulla da
            # chiamare. Cal.com/Nextcloud restano fuori (richiedono
            # credenziali/sistemi esterni non pertinenti a questa prova).
            await xai_ws.send(json.dumps({
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "instructions": instructions,
                    "output_modalities": ["audio"],
                    "voice": project["voice_name"] or "Eve",
                    "tool_choice": "auto",
                    "tools": [SEARCH_KB_TOOL] if has_knowledge_base else [],
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

            # Frase di apertura - senza questo il modello resta in
            # silenzio finche' l'utente non parla per primo, diverso da
            # una chiamata vera (maintainer, 19/08: "non da' la frase in
            # apertura"). Stesso pattern di runtime_workers/
            # realtime_service.py::run_call().
            await xai_ws.send(json.dumps({
                "type": "response.create",
                "response": {
                    "instructions": (
                        "Pronuncia subito e integralmente il seguente messaggio iniziale, "
                        "senza riassumerlo, senza cambiare lingua o ordine, e senza aggiungere altro prima: "
                        f"{consent_message}"
                    ),
                },
            }))

            await websocket.send_text(json.dumps({"type": "ascolta.ready"}))

            # Aggiornato ad ogni evento REALE ricevuto da xAI (l'utente ha
            # parlato, l'agente ha risposto, una tool call e' avvenuta) -
            # non dai pacchetti audio grezzi che il browser manda in
            # continuazione anche durante il silenzio (input_audio_buffer.
            # append), quelli non indicano attivita' vera. Con server_vad
            # xAI non manda letteralmente nulla mentre non succede niente,
            # quindi "nessun evento da N secondi" e' gia' un buon segnale
            # di silenzio senza dover distinguere i singoli tipi di evento.
            last_activity = time.monotonic()

            async def browser_to_xai() -> None:
                while True:
                    raw = await websocket.receive_text()
                    await xai_ws.send(raw)

            async def xai_to_browser() -> None:
                nonlocal last_activity
                async for raw in xai_ws:
                    last_activity = time.monotonic()
                    event = json.loads(raw)
                    event_type = event.get("type")
                    if event_type == "conversation.item.input_audio_transcription.completed":
                        transcript = (event.get("transcript") or "").strip()
                        if transcript:
                            simulation_transcript.append({"role": "user", "content": transcript})
                    elif event_type == "response.output_audio_transcript.done":
                        transcript = (event.get("transcript") or "").strip()
                        if transcript:
                            simulation_transcript.append({"role": "assistant", "content": transcript})
                    if event.get("type") == "response.function_call_arguments.done":
                        await _handle_function_call(xai_ws, websocket, event, project_id, tenant_id)
                        continue  # meccanica interna, non serve al browser
                    await websocket.send_text(raw)

            async def silence_watchdog() -> None:
                while True:
                    await asyncio.sleep(1)
                    if time.monotonic() - last_activity >= SIMULATION_SILENCE_TIMEOUT_SECONDS:
                        return

            timeout_task = asyncio.create_task(silence_watchdog())
            browser_task = asyncio.create_task(browser_to_xai())
            xai_task = asyncio.create_task(xai_to_browser())

            done, pending = await asyncio.wait(
                [browser_task, xai_task, timeout_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

            if timeout_task in done:
                try:
                    await websocket.send_text(json.dumps({
                        "type": "ascolta.timeout",
                        "seconds": SIMULATION_SILENCE_TIMEOUT_SECONDS,
                    }))
                except Exception:
                    pass  # il browser potrebbe aver gia' chiuso

            for task in done:
                if task is timeout_task:
                    continue
                exc = task.exception()
                if exc and not isinstance(exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed)):
                    logger.exception("simulate_voice relay task failed", exc_info=exc)

    except WebSocketDisconnect:
        logger.info(f"simulate_voice: browser disconnected (project={project_id})")
    except Exception as e:
        logger.exception(f"simulate_voice failed for project {project_id}: {e}")
    finally:
        simulation_ended_at = datetime.now(timezone.utc)
        try:
            await db.execute(
                """
                UPDATE calls
                SET ended_at = :ended_at,
                    status = 'completed'
                WHERE id = :id
                """,
                {"id": str(simulation_call_id), "ended_at": simulation_ended_at},
            )
            for item in simulation_transcript:
                await db.execute(
                    """
                    INSERT INTO transcripts (call_id, role, content, timestamp)
                    VALUES (:call_id, :role, :content, :timestamp)
                    """,
                    {
                        "call_id": str(simulation_call_id),
                        "role": item["role"],
                        "content": item["content"],
                        "timestamp": simulation_ended_at,
                    },
                )
            logger.info("simulate_voice stored call=%s transcript_items=%s", simulation_call_id, len(simulation_transcript))
        except Exception:
            logger.exception("simulate_voice could not persist call=%s", simulation_call_id)
        try:
            await websocket.close()
        except Exception:
            pass
