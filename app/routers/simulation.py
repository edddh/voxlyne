"""
Ascolta - Prompt simulation (test-chat before publishing).

maintainer, 19/08: "sarebbe bello poter simulare la chiamata sul sito prima
di pubblicare". Not a real voice call (xAI's realtime voice model is a
WebSocket API, not something a text chat panel can drive) - a text-based
conversation against the same provider/tenant credential and a comparable
text model, using the DRAFT prompt_a straight from the editor (not what's
saved/published) as the system message. Close enough to catch prompt
issues (wrong tone, missing info, wrong language) before going live,
without the complexity of a full audio round-trip.
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


class SimMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class SimulateRequest(BaseModel):
    prompt_a: str = Field(..., min_length=1, description="Il testo del prompt corrente nell'editor (anche non salvato)")
    messages: List[SimMessage] = Field(default_factory=list)


class SimulateResponse(BaseModel):
    reply: str


def _provider_for_engine(voice_engine: Optional[str]) -> str:
    if voice_engine and "xai" in voice_engine:
        return "xai"
    return "openai"


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

    provider = _provider_for_engine(project["voice_engine"])
    api_key = await resolve_provider_api_key(tenant_id, provider)
    if not api_key:
        raise HTTPException(
            status_code=400,
            detail=f"Nessuna credenziale voice/{provider} per questo tenant - impossibile simulare la conversazione.",
        )

    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=api_key, base_url="https://api.x.ai/v1" if provider == "xai" else None)

    # Molti prompt (es. il template Comune/URP) istruiscono l'agente a
    # usare il tool "current_datetime" come unica fonte di verita' per
    # data/ora - questa simulazione non ha alcun tool collegato (vedi
    # docstring del modulo), quindi senza questo il modello a volte scrive
    # letteralmente il nome del tool invece di rispondere (maintainer, 19/08:
    # "mi ha risposto con **current_datetime**"). Inietta il fatto
    # direttamente cosi' il modello ha gia' l'informazione e non ha
    # bisogno di "chiamare" nulla.
    now_rome = datetime.now(ZoneInfo("Europe/Rome"))
    datetime_fact = (
        f"[Informazione di sistema per questa simulazione: la data e ora corrente "
        f"a Europe/Rome sono {now_rome.strftime('%A %d %B %Y, %H:%M')}. Usala direttamente "
        f"se ti serve rispondere a domande su data/ora/giorno della settimana - non hai "
        f"nessuno strumento da chiamare in questa conversazione di prova, tutte le "
        f"informazioni che ti servono sono gia' qui o nelle istruzioni sopra.]"
    )
    chat_messages: List[Dict[str, Any]] = [
        {"role": "system", "content": body.prompt_a},
        {"role": "system", "content": datetime_fact},
    ]
    chat_messages += [{"role": m.role, "content": m.content} for m in body.messages]

    try:
        response = await client.chat.completions.create(
            model=SIMULATION_MODELS[provider],
            messages=chat_messages,
            max_tokens=400,
            temperature=0.7,
        )
    except Exception as e:
        logger.error(f"Simulation call failed for project {project_id}: {e}")
        raise HTTPException(status_code=502, detail=f"Errore chiamando il modello: {e}")

    reply = response.choices[0].message.content or ""
    return SimulateResponse(reply=reply)
