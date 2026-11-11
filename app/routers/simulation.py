"""
Voxlyne - Prompt simulation (test-chat before publishing).

maintainer, 19/08: "sarebbe bello poter simulare la chiamata sul sito prima
di pubblicare". Not a real voice call (xAI's realtime voice model is a
WebSocket API, not something a text chat panel can drive) - a text-based
conversation against the same provider/tenant credential and a comparable
text model, using the DRAFT prompt_a straight from the editor (not what's
saved/published) as the system message. Close enough to catch prompt
issues (wrong tone, missing info, wrong language) before going live,
without the complexity of a full audio round-trip.

Has the search_knowledge_base tool wired in (maintainer, 19/08: "anche nella
chat testuale" - same request already done for the voice simulation,
app/routers/simulate_voice.py) - OpenAI-compatible chat completions tool
calling, one round-trip if the model calls the tool.
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.services.agent_versions import resolve_provider_api_key

logger = logging.getLogger(__name__)
router = APIRouter()

# Text models used for simulation only - NOT the realtime voice models
# actually used in a live call (grok-voice-fast-1.0, gpt-4o-realtime-*),
# those are WebSocket APIs unusable from a simple request/response chat.
# xai: "grok-4.6" (reasoning) took ~10s per reply in testing - switched to
# the non-reasoning variant after maintainer reported the simulation "ci
# mette tanto a rispondere" (19/08) - verified live: 0.65s vs 10.6s for
# the same prompt, same quality of answer for this kind of short reply.
SIMULATION_MODELS = {
    "xai": "grok-4.20-0309-non-reasoning",
    "openai": "gpt-4o",
}

# Formato OpenAI-compatible per chat.completions (diverso da quello usato
# nell'API realtime, vedi app/routers/simulate_voice.py::SEARCH_KB_TOOL -
# qui i campi vanno annidati sotto "function").
SEARCH_KB_TOOL_CHAT = {
    "type": "function",
    "function": {
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
    },
}

# Keep the text simulator aligned with the production tool contract. Without
# this, a chat model may emit a generic answer and a tool call in the same
# turn, which makes the preview look as though it ignored the search result.
TOOL_RESULT_WAIT_INSTRUCTIONS = (
    "Regola inderogabile per i tool: quando una risposta richiede dati dalla "
    "knowledge base o da un altro tool, non fornire alcuna risposta sostanziale "
    "prima del risultato. Esegui il tool, attendi il suo output, poi rispondi "
    "nello stesso turno usando esclusivamente quel risultato per i fatti verificabili. "
    "Non anticipare indirizzi, orari, disponibilita' o conclusioni."
)


class SimMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class SimulateToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any]
    result: Dict[str, Any]


class SimulateRequest(BaseModel):
    prompt_a: str = Field(..., min_length=1, description="Il testo del prompt corrente nell'editor (anche non salvato)")
    messages: List[SimMessage] = Field(default_factory=list)


class SimulateResponse(BaseModel):
    reply: str
    tool_calls: List[SimulateToolCall] = Field(default_factory=list)


def _provider_candidates_for_engine(voice_engine: Optional[str]) -> List[str]:
    engine = (voice_engine or "").strip().lower()
    if "xai" in engine:
        return ["xai"]
    if "openai" in engine:
        return ["openai"]
    if "eleven" in engine:
        return ["xai", "openai"]
    return ["xai", "openai"]


async def _run_search_knowledge_base(project_id: UUID, tenant_id: UUID, query: str) -> Dict[str, Any]:
    from app.services.rag.search import search_knowledge_base

    try:
        results = await search_knowledge_base(project_id, tenant_id, query, top_k=5)
        return {"status": "ok", "results": results} if results else {"status": "no_results"}
    except ValueError as e:
        return {"status": "unavailable", "message": str(e)}


@router.post("/projects/{project_id}/simulate", response_model=SimulateResponse)
async def simulate_conversation(
    project_id: UUID,
    body: SimulateRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> SimulateResponse:
    db = get_database()
    project = await db.fetch_one(
        "SELECT tenant_id, voice_engine FROM projects WHERE id = :id", {"id": str(project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Project has no owning tenant")
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=403, detail="Access denied to this project")

    provider = None
    api_key = None
    for candidate in _provider_candidates_for_engine(project["voice_engine"]):
        candidate_key = await resolve_provider_api_key(tenant_id, candidate, project_id=project_id)
        if candidate_key:
            provider = candidate
            api_key = candidate_key
            break
    if not api_key or not provider:
        raise HTTPException(
            status_code=400,
            detail=(
                "Nessuna credenziale voice/xai o voice/openai per questo tenant "
                "- impossibile simulare la conversazione."
            ),
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1" if provider == "xai" else None)

    # Molti prompt (es. il template Comune/URP) istruiscono l'agente a
    # usare il tool "current_datetime" - non collegato qui (solo
    # search_knowledge_base lo e', vedi sotto), quindi senza questo il
    # modello a volte scrive letteralmente il nome del tool invece di
    # rispondere (maintainer, 19/08: "mi ha risposto con **current_datetime**").
    # Inietta il fatto direttamente cosi' il modello ha gia' l'informazione.
    now_rome = datetime.now(ZoneInfo("Europe/Rome"))
    datetime_fact = (
        f"[Informazione di sistema per questa simulazione: la data e ora corrente "
        f"a Europe/Rome sono {now_rome.strftime('%A %d %B %Y, %H:%M')}. Usala direttamente "
        f"se ti serve rispondere a domande su data/ora/giorno della settimana - non hai "
        f"un tool current_datetime da chiamare in questa conversazione di prova, solo "
        f"search_knowledge_base per la knowledge base del progetto.]"
    )
    chat_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": body.prompt_a},
        {"role": "system", "content": TOOL_RESULT_WAIT_INSTRUCTIONS},
        {"role": "system", "content": datetime_fact},
    ]
    chat_messages += [{"role": m.role, "content": m.content} for m in body.messages]

    async def _call_model(messages: List[Dict[str, Any]]):
        return await client.chat.completions.create(
            model=SIMULATION_MODELS[provider],
            messages=messages,
            tools=[SEARCH_KB_TOOL_CHAT],
            tool_choice="auto",
            max_tokens=400,
            temperature=0.7,
        )

    tool_calls_log: List[SimulateToolCall] = []
    try:
        response = await _call_model(chat_messages)
        message = response.choices[0].message

        # A tool can lead to a follow-up tool call. Continue until the model
        # produces a final answer, with a bounded loop for a predictable UI
        # request time.
        for _ in range(4):
            if not message.tool_calls:
                break
            chat_messages.append({
                "role": "assistant",
                "content": message.content,
                "tool_calls": [tc.model_dump() for tc in message.tool_calls],
            })
            for tool_call in message.tool_calls:
                import json as _json

                try:
                    args = _json.loads(tool_call.function.arguments or "{}")
                except _json.JSONDecodeError:
                    args = {}
                if tool_call.function.name == "search_knowledge_base":
                    result = await _run_search_knowledge_base(project_id, tenant_id, args.get("query", ""))
                    tool_calls_log.append(SimulateToolCall(name="search_knowledge_base", arguments=args, result=result))
                else:
                    result = {"status": "error", "message": f"Unsupported simulation tool: {tool_call.function.name}"}
                chat_messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": _json.dumps(result, ensure_ascii=True),
                })
            response = await _call_model(chat_messages)
            message = response.choices[0].message
    except Exception as e:
        logger.error(f"Simulation call failed for project {project_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Errore chiamando il modello: {e}")

    return SimulateResponse(reply=message.content or "", tool_calls=tool_calls_log)
