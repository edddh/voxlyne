"""
Project-aware ElevenLabs agent provisioning for Ascolta.

Unlike runtime_workers/provision_elevenlabs.py, this module reads prompt /
voice / language from a real Ascolta project (preferably its published
agent_version snapshot) and points tool webhooks back to FastAPI routes that
carry the project_id explicitly.
"""

from __future__ import annotations

import json
import logging
import secrets
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

import httpx

from app.config import get_settings
from app.database.db import get_database
from app.integrations.common.tools import build_tools
from app.services.credentials.manager import CredentialsManager

logger = logging.getLogger(__name__)

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io/v1"
DEFAULT_AGENT_LLM = "qwen35-397b-a17b"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
DEFAULT_TTS_MODEL_ID = "eleven_v3_conversational"

# ElevenLabs abilita il cambio lingua solo per i codici presenti qui. Usiamo
# sempre la voce principale: le lingue non implicano una seconda voce o UI.
ELEVENLABS_SUPPORTED_LANGUAGE_CODES = (
    "ar", "bg", "zh", "hr", "cs", "da", "nl", "en", "fil", "fi", "fr",
    "de", "el", "hi", "hu", "id", "it", "ja", "ko", "ms", "no", "pl",
    "pt", "pt-br", "ro", "ru", "sk", "es", "sv", "ta", "tr", "uk",
)

# Webhook tools must finish before the agent answers with information derived
# from them. Eleven's default "auto" pre-tool speech can otherwise produce an
# answer while the search is still in flight.
TOOL_RESULT_WAIT_INSTRUCTIONS = (
    "Quando usi un tool, il suo risultato e' necessario per la risposta. "
    "Esegui il tool prima di formulare una risposta informativa e attendi sempre il risultato. "
    "Non anticipare conclusioni, disponibilita', indirizzi, orari o dettagli pratici "
    "finche' non hai ricevuto il risultato del tool. "
    "Dopo una ricerca nella knowledge base, usa i risultati nella stessa risposta; "
    "se non contengono la risposta, dillo chiaramente senza inventare informazioni."
)

KNOWLEDGE_BASE_FIRST_INSTRUCTIONS = (
    "Per ogni domanda su orari, aperture, sedi, documenti, procedure, appuntamenti, "
    "scadenze o disponibilita' del Comune, chiama obbligatoriamente search_knowledge_base "
    "prima di rispondere. Non usare conoscenza generale, memoria o supposizioni per questi dati. "
    "Se la ricerca non restituisce un'informazione affidabile, dillo e indica il sito o l'ufficio competente."
)

EXPRESSIVE_VOICE_INSTRUCTIONS = (
    "Usi Eleven v3 Conversational con capacita' espressive. Mantieni una voce "
    "professionale ma umana: calda e rassicurante quando l'utente e' incerto o "
    "preoccupato, chiara e misurata per istruzioni pratiche, naturalmente positiva "
    "per notizie favorevoli. Adatta ritmo, enfasi e tono al contesto senza teatralita' "
    "e senza usare tag sonori in modo gratuito."
)


def elevenlabs_target_sip_uri(phone_number: str) -> str:
    return f"sip:{phone_number}@sip.rtc.elevenlabs.io:5060"


async def _fetch_project_row(project_id: UUID) -> dict[str, Any]:
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        project = await db.fetch_one("SELECT * FROM projects WHERE id = :id", {"id": str(project_id)})
        if not project:
            raise ValueError(f"Project not found: {project_id}")
        published = await db.fetch_one(
            """
            SELECT prompt_a, consent_message, voice_name, language, voice_engine, output_config
            FROM agent_versions
            WHERE project_id = :project_id AND status = 'published'
            ORDER BY version_number DESC
            LIMIT 1
            """,
            {"project_id": str(project_id)},
        )
    data = dict(project)
    if published:
        data["_published_version"] = dict(published)
    return data


def _json_value(value: Any, fallback: Any) -> Any:
    if value is None:
        return deepcopy(fallback)
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return deepcopy(fallback)
    return deepcopy(value)


async def _resolve_credentials(tenant_id: UUID) -> dict[str, str]:
    manager = CredentialsManager()
    creds = await manager.get_credentials_with_fallback(tenant_id, None, "tts", "elevenlabs_agent")
    if not creds.get("api_key"):
        creds = await manager.get_credentials_with_fallback(tenant_id, None, "tts", "elevenlabs")
    if not creds.get("api_key"):
        raise ValueError(
            f"No tts/elevenlabs_agent or tts/elevenlabs credential stored for tenant {tenant_id}"
        )

    tool_secret = (creds.get("tool_secret") or "").strip()
    if not tool_secret:
        tool_secret = secrets.token_urlsafe(24)
        merged = dict(creds)
        merged["tool_secret"] = tool_secret
        await manager.set_credentials(
            entity_type="tenant",
            entity_id=tenant_id,
            service_type="tts",
            provider="elevenlabs_agent",
            data=merged,
            credential_key="default",
        )
        creds = merged
    return creds


async def _request(api_key: str, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.request(
            method,
            f"{ELEVENLABS_BASE_URL}{path}",
            headers={"xi-api-key": api_key, "Content-Type": "application/json"},
            json=payload,
        )
    if response.status_code >= 300:
        raise RuntimeError(f"ElevenLabs {method} {path} failed: {response.status_code} {response.text}")
    return response.json() if response.content else {}


def _tool_schema_parameters(parameters: dict[str, Any]) -> dict[str, Any]:
    required = set(parameters.get("required") or [])
    properties = parameters.get("properties") or {}
    converted_properties: dict[str, Any] = {}

    for name, spec in properties.items():
        prop_type = spec.get("type", "string")
        if name == "caller_phone":
            converted_properties[name] = {
                "type": prop_type,
                "dynamic_variable": "system__caller_id",
                "required": name in required,
                "value_type": "dynamic_variable",
            }
            continue
        converted_properties[name] = {
            "type": prop_type,
            "description": spec.get("description", name),
            "dynamic_variable": "",
            "constant_value": "",
            "required": name in required,
            "value_type": "llm_prompt",
        }

    return {
        "type": "object",
        "description": parameters.get("description", "Arguments"),
        "required": list(required),
        "properties": converted_properties,
    }


async def _create_tools(
    api_key: str,
    tool_secret: str,
    public_base_url: str,
    project_id: UUID,
    existing_tool_ids: list[str] | None = None,
) -> list[str]:
    existing_by_name: dict[str, str] = {}
    for tool_id in existing_tool_ids or []:
        try:
            existing = await _request(api_key, "GET", f"/convai/tools/{tool_id}")
            name = ((existing.get("tool_config") or {}).get("name") or "").strip()
            if name:
                existing_by_name[name] = tool_id
        except Exception:
            # A deleted or inaccessible old tool must not prevent restoring
            # the project's usable tool set.
            logger.warning("Could not retrieve existing ElevenLabs tool %s", tool_id, exc_info=True)

    tool_ids: list[str] = []
    for tool in build_tools(None):
        payload = {
            "tool_config": {
                "name": tool["name"],
                "description": tool["description"],
                "type": "webhook",
                "response_timeout_secs": 20,
                # The default "auto" may let the agent speak before a tool
                # result is available. For factual searches that makes the
                # first answer stale or generic, so keep every tool blocking.
                "pre_tool_speech": "off",
                "execution_mode": "immediate",
                "interruption_mode": "disable_during_tool",
                "api_schema": {
                    "url": f"{public_base_url}/api/elevenlabs/projects/{project_id}/tools/{tool['name']}",
                    "method": "POST",
                    "request_body_schema": _tool_schema_parameters(tool["parameters"]),
                    "request_headers": {
                        "Content-Type": "application/json",
                        "X-Tool-Secret": tool_secret,
                    },
                },
                "dynamic_variables": {"dynamic_variable_placeholders": {}},
            }
        }
        existing_tool_id = existing_by_name.get(tool["name"])
        if existing_tool_id:
            updated = await _request(api_key, "PATCH", f"/convai/tools/{existing_tool_id}", payload)
            tool_id = updated.get("tool_id") or updated.get("id") or existing_tool_id
        else:
            created = await _request(api_key, "POST", "/convai/tools", payload)
            tool_id = created.get("tool_id") or created.get("id")
        if tool_id:
            tool_ids.append(str(tool_id))
    return tool_ids


def _build_conversation_config(
    project: dict[str, Any], tool_ids: list[str], voice_id: str, llm: str
) -> dict[str, Any]:
    published = project.get("_published_version") or {}
    prompt = (published.get("prompt_a") or project.get("prompt_a") or "").strip()
    prompt = (
        f"{prompt}\n\n{KNOWLEDGE_BASE_FIRST_INSTRUCTIONS}\n\n"
        f"{TOOL_RESULT_WAIT_INSTRUCTIONS}\n\n{EXPRESSIVE_VOICE_INSTRUCTIONS}"
    ).strip()
    first_message = (
        published.get("consent_message")
        or project.get("consent_message")
        or "Buongiorno, come posso aiutarla?"
    ).strip()
    language = str(published.get("language") or project.get("language") or "en").strip().lower()

    language_presets = {
        language_code: {
            "overrides": {
                "agent": {"language": None},
                "tts": {"voice_id": voice_id},
            },
            "first_message_translation": None,
        }
        for language_code in ELEVENLABS_SUPPORTED_LANGUAGE_CODES
        if language_code != language
    }

    return {
        # Tutte le lingue ElevenLabs, con una sola voce. language_detection
        # seleziona il preset corretto senza esporre voci nazionali nella UI.
        "language_presets": language_presets,
        "agent": {
            "first_message": first_message,
            "language": language,
            "prompt": {
                "prompt": prompt,
                "llm": llm,
                "temperature": 0.4,
                "max_tokens": 220,
                "tool_ids": tool_ids,
                "knowledge_base": [],
                "built_in_tools": {
                    "language_detection": {"name": "language_detection", "params": {}},
                },
            },
        },
        "tts": {
            "model_id": DEFAULT_TTS_MODEL_ID,
            "voice_id": voice_id,
            "expressive_mode": True,
        },
        # ElevenLabs abilita il barge-in dell'agente soltanto quando il
        # client event `interruption` e' incluso nella configurazione della
        # conversazione. Vale anche per il canale SIP, non solo per la demo
        # browser. Le correzioni mantengono coerente il transcript dopo un
        # taglio della risposta dell'agente.
        "conversation": {
            "client_events": [
                "audio",
                "interruption",
                "agent_response",
                "agent_response_correction",
                "agent_tool_response",
                "agent_tool_response_full_payload",
                "user_transcript",
            ],
        },
        # Turn V3 usa il rilevamento contestuale di ElevenLabs. Per un URP
        # telefonico manteniamo una presa di turno rapida, senza aspettare
        # inutilmente dopo che il cittadino ha concluso la richiesta.
        "turn": {
            "turn_model": "turn_v3",
            "turn_eagerness": "eager",
        },
    }


async def provision_agent_for_project(project_id: UUID) -> dict[str, Any]:
    project = await _fetch_project_row(project_id)
    tenant_id = project.get("tenant_id")
    if not tenant_id:
        raise ValueError(f"Project {project_id} has no tenant_id")

    creds = await _resolve_credentials(UUID(str(tenant_id)))
    settings = get_settings()
    public_base_url = settings.webhook_base_url.rstrip("/")
    if not public_base_url:
        raise ValueError("WEBHOOK_BASE_URL is missing")

    provider_cfg = _json_value(project.get("voice_provider_config"), {})
    eleven_cfg = provider_cfg.get("elevenlabs") if isinstance(provider_cfg.get("elevenlabs"), dict) else {}
    llm = str(eleven_cfg.get("llm") or DEFAULT_AGENT_LLM).strip()
    existing_agent_id = (project.get("elevenlabs_agent_id") or "").strip()
    voice_id = str(project.get("elevenlabs_voice_id") or DEFAULT_VOICE_ID).strip()

    # Durante una migrazione di workspace viene usata una voce temporanea
    # per creare l'agente. Se l'amministratore sceglie poi una voce dal
    # dashboard ElevenLabs, il primo publish la acquisisce e non la perde.
    if existing_agent_id and eleven_cfg.get("migration_voice_temporary"):
        try:
            remote_agent = await _request(creds["api_key"], "GET", f"/convai/agents/{existing_agent_id}")
            remote_voice_id = str(
                ((remote_agent.get("conversation_config") or {}).get("tts") or {}).get("voice_id") or ""
            ).strip()
            if remote_voice_id and remote_voice_id != voice_id:
                voice_id = remote_voice_id
                eleven_cfg.pop("migration_voice_temporary", None)
                logger.info("Adopted manually selected ElevenLabs voice for project=%s", project_id)
        except Exception:
            logger.warning("Could not read manually selected ElevenLabs voice project=%s", project_id, exc_info=True)

    previous_tool_ids = [str(tool_id) for tool_id in (eleven_cfg.get("tool_ids") or []) if tool_id]
    tool_ids = await _create_tools(
        creds["api_key"],
        creds["tool_secret"],
        public_base_url,
        project_id,
        previous_tool_ids,
    )
    conversation_config = _build_conversation_config(project, tool_ids, voice_id, llm)

    payload = {
        "name": f"{project['name']} - Eleven v3",
        "conversation_config": conversation_config,
    }
    if existing_agent_id:
        agent = await _request(creds["api_key"], "PATCH", f"/convai/agents/{existing_agent_id}", payload)
        agent_id = existing_agent_id
    else:
        agent = await _request(creds["api_key"], "POST", "/convai/agents/create", payload)
        agent_id = str(agent.get("agent_id") or agent.get("id") or "").strip()
        if not agent_id:
            raise RuntimeError("ElevenLabs create agent succeeded but returned no agent_id")

    db = get_database()
    eleven_cfg.update(
        {
            "agent_id": agent_id,
            "tool_ids": tool_ids,
            "tts_model_id": DEFAULT_TTS_MODEL_ID,
            "llm": llm,
            "last_provisioned_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    provider_cfg["elevenlabs"] = eleven_cfg
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        await db.execute(
            """
            UPDATE projects
            SET elevenlabs_agent_id = :agent_id,
                elevenlabs_voice_id = :voice_id,
                voice_provider_config = :voice_provider_config,
                updated_at = NOW()
            WHERE id = :id
            """,
            {
                "id": str(project_id),
                "agent_id": agent_id,
                "voice_id": voice_id,
                "voice_provider_config": json.dumps(provider_cfg),
            },
        )

    logger.info("Provisioned ElevenLabs agent project=%s agent_id=%s", project_id, agent_id)
    return {
        "status": "agent_provisioned",
        "agent_id": agent_id,
        "tool_ids": tool_ids,
        "tts_model_id": DEFAULT_TTS_MODEL_ID,
        "llm": llm,
        "voice_id": voice_id,
    }
