#!/usr/bin/env python3
"""
Self-contained ElevenLabs provisioning helper for Ascolta.
Status: starting point for Milestone 5 (see README) - not yet wired into
app.services.voice.factory / CallManager. Config/env resolution here is still
file-based (ascolta-stack-config.json); the DB-driven credential/config
resolution (CredentialsManager.get_credentials_with_fallback) will replace it
when the concrete voice engine classes are implemented.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ASCOLTA_ROOT = SCRIPT_DIR.parent
if str(ASCOLTA_ROOT) not in sys.path:
    sys.path.insert(0, str(ASCOLTA_ROOT))

from app.integrations.common.config import load_config, load_scenario_config, resolve_scenario
from app.integrations.common.tools import build_tools


BASE_URL = "https://api.elevenlabs.io/v1"
API_KEY = os.environ.get("ELEVENLABS_API_KEY", "").strip()
PUBLIC_BASE_URL = os.environ.get("ASCOLTA_PUBLIC_BASE_URL", "").strip()
TOOL_SECRET = os.environ.get("ELEVENLABS_TOOL_SECRET", "").strip()
DEFAULT_AGENT_NAME = "Ascolta Eleven"
DEFAULT_AGENT_LLM = "qwen3-30b-a3b"
DEFAULT_VOICE_ID = "JBFqnCBsd6RMkjVDRZzb"
AGENT_ID_FILE = SCRIPT_DIR / "agent_id.txt"


def deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dicts(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def load_tool_definitions(scenario_config: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    return build_tools(scenario_config)


def read_text_file(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return content or None


def read_json_file(path: Path) -> dict[str, Any] | list[Any] | None:
    try:
        data = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


def load_effective_settings(scenario_config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = load_config()
    response_cfg = cfg.get("response") if isinstance(cfg.get("response"), dict) else {}
    eleven_cfg = cfg.get("elevenlabs") if isinstance(cfg.get("elevenlabs"), dict) else {}
    scenario_cfg = scenario_config if isinstance(scenario_config, dict) else {}
    scenario_eleven = (
        scenario_cfg.get("elevenlabs") if isinstance(scenario_cfg.get("elevenlabs"), dict) else {}
    )
    language = str(response_cfg.get("language") or eleven_cfg.get("language") or "it").strip().lower()
    verbosity = str(
        scenario_eleven.get("verbosity")
        or eleven_cfg.get("verbosity")
        or response_cfg.get("verbosity")
        or scenario_cfg.get("verbosity")
        or "medium"
    ).strip().lower()
    max_tokens_by_verbosity = {"low": 120, "medium": 180, "high": 260}
    voice_id = (
        scenario_eleven.get("voice_id")
        or eleven_cfg.get("voice_id")
        or response_cfg.get("voice_id")
        or DEFAULT_VOICE_ID
    )
    public_base_url = str(
        scenario_eleven.get("public_base_url")
        or eleven_cfg.get("public_base_url")
        or PUBLIC_BASE_URL
    ).rstrip("/")
    return {
        "agent_name": scenario_eleven.get("agent_name") or eleven_cfg.get("agent_name") or DEFAULT_AGENT_NAME,
        "agent_llm": scenario_eleven.get("agent_llm") or eleven_cfg.get("agent_llm") or DEFAULT_AGENT_LLM,
        "language": str(scenario_eleven.get("language") or language).strip().lower() or language,
        "voice_id": voice_id,
        "voice_id_ru": scenario_eleven.get("voice_id_ru") or eleven_cfg.get("voice_id_ru") or voice_id,
        "voice_id_en": scenario_eleven.get("voice_id_en") or eleven_cfg.get("voice_id_en") or voice_id,
        "voice_id_de": scenario_eleven.get("voice_id_de") or eleven_cfg.get("voice_id_de") or voice_id,
        "voice_id_fr": scenario_eleven.get("voice_id_fr") or eleven_cfg.get("voice_id_fr") or voice_id,
        "voice_id_es": scenario_eleven.get("voice_id_es") or eleven_cfg.get("voice_id_es") or voice_id,
        "base_url": str(scenario_eleven.get("base_url") or eleven_cfg.get("base_url") or BASE_URL).rstrip("/"),
        "public_base_url": public_base_url,
        "verbosity": verbosity,
        "max_tokens": max_tokens_by_verbosity.get(verbosity, 180),
        "agent_id": (
            str(scenario_eleven.get("agent_id")).strip()
            if scenario_eleven.get("agent_id")
            else (str(eleven_cfg.get("agent_id")).strip() if eleven_cfg.get("agent_id") else None)
        ),
        "update_only": bool(scenario_eleven.get("update_only", eleven_cfg.get("update_only", False))),
        "refresh_tools": bool(scenario_eleven.get("refresh_tools", eleven_cfg.get("refresh_tools", False))),
    }

def _instruction_prefix(scenario_config: dict[str, Any]) -> str:
    features = scenario_config.get("features") if isinstance(scenario_config.get("features"), dict) else {}
    caller_rules = bool(features.get("caller_id_rules", True))
    verbosity = str(
        (scenario_config.get("elevenlabs") or {}).get("verbosity")
        or scenario_config.get("verbosity")
        or "medium"
    ).strip().lower()
    verbosity_map = {
        "low": "Rispondi in modo molto sintetico: al massimo 1-2 frasi brevi, senza preamboli. ",
        "medium": "Rispondi in modo sintetico ma completo. ",
        "high": "Puoi dare piu' dettaglio del solito, senza diventare prolisso. ",
    }
    base_prefix = (
        "Usa current_datetime come unica fonte di verita' per data, ora e giorno della settimana correnti a Roma. "
        "Non basarti su system time o su supposizioni interne quando devi ragionare su riferimenti temporali relativi o su combinazioni tra giorno della settimana e data numerica. "
        "Regola lingua: se l'utente parla in una lingua diversa dall'italiano per due turni consecutivi, chiama il system tool language_detection per passare a quella lingua e continua in quella lingua finche' l'utente non cambia lingua di nuovo. "
        + verbosity_map.get(verbosity, verbosity_map["medium"])
    )
    if not caller_rules:
        return base_prefix
    return (
        base_prefix
        + "Il numero del chiamante e': {{system__caller_id}}. Caso 1: se e' presente, usalo come riferimento primario per identificare il chiamante e i suoi appuntamenti e consideralo gia' disponibile. "
        "In questo caso non chiedere il numero da zero, non dire frasi come 'potrei avere il suo numero' e non chiederne conferma: usalo direttamente e in silenzio per cercare appuntamenti, verificare disponibilita' e prenotare. "
        "Caso 2: se {{system__caller_id}} e' mancante, vuoto o inutilizzabile, chiedi gentilmente il numero di telefono solo quando serve davvero. "
    )


def prepare_elevenlabs_instructions(prompt_text: str, scenario_config: dict[str, Any]) -> str:
    instructions = (prompt_text or "").strip()
    if not instructions:
        return instructions
    instructions = re.sub(
        r"Parla sempre in italiano,[^.]*\.\s*",
        "",
        instructions,
        flags=re.IGNORECASE,
    )
    instructions = re.sub(
        r"salvo esplicita richiesta di un'altra lingua\.\s*",
        "",
        instructions,
        flags=re.IGNORECASE,
    )
    prefix = _instruction_prefix(scenario_config)
    instructions, count = re.subn(
        r"^La data e ora correnti a Roma sono[^.]*\.\s*",
        prefix,
        instructions,
        flags=re.IGNORECASE,
    )
    if count == 0:
        instructions = f"{prefix}{instructions}"
    return instructions


def _load_knowledge_base_ids(path: str | None) -> list[str]:
    if not path:
        return []
    kb_path = (ASCOLTA_ROOT / path).resolve()
    data = read_json_file(kb_path)
    if isinstance(data, list):
        return [str(item) for item in data if str(item).strip()]
    return []


def _format_knowledge_base(items: list[str] | None, settings: dict[str, Any]) -> list[dict[str, str]]:
    formatted: list[dict[str, str]] = []
    if not items:
        return formatted
    for item in items:
        if not item:
            continue
        if isinstance(item, dict):
            formatted.append(item)
            continue
        try:
            kb_item = request("GET", f"/convai/knowledge-base/{item}", base_url=settings["base_url"])
        except Exception:
            continue
        if isinstance(kb_item, dict) and kb_item.get("id") and kb_item.get("type") and kb_item.get("name"):
            formatted.append(
                {
                    "id": str(kb_item.get("id")),
                    "type": str(kb_item.get("type")),
                    "name": str(kb_item.get("name")),
                }
            )
    return formatted


def _render_template(text: str, context: dict[str, str]) -> str:
    rendered = text or ""
    for key, value in context.items():
        rendered = rendered.replace(f"{{{{{key}}}}}", value)
    return rendered


def _extract_websites(scenario_config: dict[str, Any]) -> list[str]:
    websites: list[str] = []
    raw = scenario_config.get("websites")
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str) and item.strip():
                websites.append(item.strip())
            elif isinstance(item, dict):
                url = str(item.get("url") or "").strip()
                if url:
                    websites.append(url)
    if not websites:
        city_site = str(scenario_config.get("city_site") or "").strip()
        if city_site:
            websites.append(city_site)
        rag_sync = scenario_config.get("rag_sync") if isinstance(scenario_config.get("rag_sync"), dict) else {}
        seed_url = str(rag_sync.get("seed_url") or "").strip()
        if seed_url and seed_url not in websites:
            websites.append(seed_url)
    return websites


def _build_prompt_context(scenario_config: dict[str, Any]) -> dict[str, str]:
    city_name = str(scenario_config.get("city_name") or "la citta").strip()
    label_override = str(scenario_config.get("supported_languages_label") or "").strip()
    languages = scenario_config.get("languages") if isinstance(scenario_config.get("languages"), list) else []
    language_map = {"it": "italiano", "en": "inglese", "de": "tedesco", "fr": "francese"}
    supported_languages = ", ".join(
        [language_map.get(str(code).lower(), str(code)) for code in languages if str(code).strip()]
    )
    if label_override:
        supported_languages = label_override
    if not supported_languages:
        supported_languages = "italiano"
    features = scenario_config.get("features") if isinstance(scenario_config.get("features"), dict) else {}
    websites = _extract_websites(scenario_config)
    sources: list[str] = []
    if features.get("rag_site_sync") and websites:
        sources.append(f"- contenuti sincronizzati periodicamente da: {', '.join(websites)}")
    if features.get("rag_documents"):
        sources.append("- documenti aggiuntivi caricati nel knowledge base")
    sources_description = "\n".join(sources) if sources else "- fonti limitate; rispondi solo se trovi l'informazione"
    return {
        "city_name": city_name,
        "city_site": websites[0] if websites else "",
        "supported_languages": supported_languages,
        "sources_description": sources_description,
    }


def prompt_bundle() -> tuple[str, str, str, list[str], dict[str, Any]]:
    cfg = load_config()
    scenario = resolve_scenario(cfg, "elevenlabs")
    scenario_name = str(scenario.get("name") or "tenant_runtime").strip().lower()
    scenario_config = load_scenario_config(scenario.get("config_path"))
    prompt_context = _build_prompt_context(scenario_config)
    overrides = cfg.get("prompt_overrides") if isinstance(cfg.get("prompt_overrides"), dict) else {}
    prompt_text = str(overrides.get("primary_prompt") or "").strip()
    if not prompt_text:
        raise RuntimeError("Primary prompt missing from runtime configuration")
    prompt_text = _render_template(prompt_text or "", prompt_context)
    instructions = prepare_elevenlabs_instructions(prompt_text or "", scenario_config)
    if not instructions:
        raise RuntimeError("Primary prompt resolved to an empty instruction set")
    response_cfg = cfg.get("response") if isinstance(cfg.get("response"), dict) else {}
    first_message_raw = str(
        response_cfg.get("first_message")
        or overrides.get("secondary_prompt")
        or scenario.get("first_message")
        or ""
    ).strip()
    if not first_message_raw:
        raise RuntimeError("First message missing from runtime configuration")
    first_message = _render_template(first_message_raw, prompt_context)
    knowledge_base_ids = _load_knowledge_base_ids(scenario_config.get("knowledge_base_path"))
    return scenario_name, instructions, first_message, knowledge_base_ids, scenario_config


def request(method: str, path: str, payload: dict[str, Any] | None = None, *, base_url: str) -> dict[str, Any]:
    if not API_KEY:
        raise RuntimeError("ELEVENLABS_API_KEY missing")
    body = None if payload is None else json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{base_url}{path}",
        data=body,
        method=method,
        headers={"xi-api-key": API_KEY, "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode()
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def create_tool(
    tool_name: str,
    description: str,
    parameters: dict[str, Any],
    *,
    public_base_url: str,
    base_url: str,
) -> dict[str, Any]:
    parameters = deepcopy(parameters)
    required = set(parameters.get("required") or [])
    properties = parameters.get("properties") or {}
    converted_properties: dict[str, Any] = {}

    for name, spec in properties.items():
        prop_type = spec.get("type", "string")
        if tool_name in {"calcom_book_appointment", "calcom_list_bookings"} and name == "caller_phone":
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

    schema = {
        "type": "object",
        "description": parameters.get("description", f"Arguments for {tool_name}"),
        "required": list(required),
        "properties": converted_properties,
    }
    payload = {
        "tool_config": {
            "name": tool_name,
            "description": description,
            "type": "webhook",
            "response_timeout_secs": 20,
            "force_pre_tool_speech": tool_name.startswith("calcom_") or tool_name.startswith("calendar_"),
            "api_schema": {
                "url": f"{public_base_url}/api/elevenlabs/tools/{tool_name}",
                "method": "POST",
                "request_body_schema": schema,
                "request_headers": {
                    "Content-Type": "application/json",
                    "X-Tool-Secret": TOOL_SECRET,
                },
            },
            "dynamic_variables": {"dynamic_variable_placeholders": {}},
        }
    }
    return request("POST", "/convai/tools", payload, base_url=base_url)


def _load_all_languages() -> list[str]:
    languages_path = ASCOLTA_ROOT / "common" / "languages" / "elevenlabs_agents_all.json"
    data = read_json_file(languages_path)
    if isinstance(data, list):
        return [str(code).strip().lower() for code in data if str(code).strip()]
    return []


def _build_language_presets(settings: dict[str, Any], scenario_config: dict[str, Any]) -> dict[str, Any]:
    localized = (
        scenario_config.get("first_message_localized")
        if isinstance(scenario_config.get("first_message_localized"), dict)
        else {}
    )
    raw_languages = scenario_config.get("languages")
    if isinstance(raw_languages, str) and raw_languages.strip().lower() in {"all", "all_elevenlabs"}:
        language_codes = _load_all_languages()
    elif isinstance(raw_languages, list):
        language_codes = [str(code).strip().lower() for code in raw_languages if str(code).strip()]
    else:
        language_codes = []
    if not language_codes and localized:
        language_codes = [str(code).strip().lower() for code in localized.keys() if str(code).strip()]

    if language_codes:
        presets: dict[str, dict[str, Any]] = {}
        for lang_code in language_codes:
            message = localized.get(lang_code) if isinstance(localized, dict) else None
            voice_key = f"voice_id_{lang_code}"
            voice_id = settings.get(voice_key) or settings.get("voice_id")
            overrides: dict[str, Any] = {"agent": {"language": None}, "tts": {"voice_id": voice_id}}
            if isinstance(message, str) and message.strip():
                overrides["agent"]["first_message"] = message.strip()
            presets[lang_code] = {"overrides": overrides, "first_message_translation": None}
        if presets:
            return presets

    return {
        "en": {
            "overrides": {
                "agent": {
                    "first_message": "Hello. Please tell me your full name. How can I help?",
                    "language": None,
                },
                "tts": {"voice_id": settings["voice_id_en"]},
            },
            "first_message_translation": None,
        }
    }


def build_conversation_config(
    prompt: str,
    first_message: str,
    tool_ids: list[str],
    settings: dict[str, Any],
    knowledge_base: list[dict[str, str]] | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    language = settings["language"]
    voice_id = settings["voice_id"]
    scenario_config = scenario_config or {}
    payload: dict[str, Any] = {
        "language_presets": _build_language_presets(settings, scenario_config),
        "agent": {
            "first_message": first_message,
            "language": language,
            "prompt": {
                "prompt": prompt,
                "llm": settings["agent_llm"],
                "temperature": 0.4,
                "max_tokens": settings["max_tokens"],
                "tool_ids": tool_ids,
                "knowledge_base": knowledge_base or [],
                "built_in_tools": {
                    "language_detection": {"name": "language_detection", "params": {}},
                },
            },
        },
        "tts": {"model_id": "eleven_flash_v2_5", "voice_id": voice_id},
    }
    scenario_eleven = scenario_config.get("elevenlabs") if isinstance(scenario_config.get("elevenlabs"), dict) else {}
    conv_override = (
        scenario_eleven.get("conversation_config")
        if isinstance(scenario_eleven.get("conversation_config"), dict)
        else {}
    )
    payload = deep_merge_dicts(payload, conv_override)
    payload.setdefault("agent", {})
    payload["agent"].setdefault("prompt", {})
    payload["agent"]["first_message"] = first_message
    payload["agent"]["language"] = language
    payload["agent"]["prompt"]["prompt"] = prompt
    payload["agent"]["prompt"]["llm"] = settings["agent_llm"]
    payload["agent"]["prompt"]["max_tokens"] = settings["max_tokens"]
    payload["agent"]["prompt"]["tool_ids"] = tool_ids
    payload["agent"]["prompt"]["knowledge_base"] = knowledge_base or []
    if knowledge_base:
        payload["agent"]["prompt"].setdefault("rag", {})
        payload["agent"]["prompt"]["rag"]["enabled"] = True
    timezone = scenario_eleven.get("timezone") or scenario_config.get("timezone") or settings.get("timezone")
    if timezone:
        payload["agent"]["prompt"]["timezone"] = timezone
    payload.setdefault("tts", {})
    payload["tts"]["voice_id"] = voice_id
    payload["language_presets"] = _build_language_presets(settings, scenario_config)
    return payload


def create_agent(
    tool_ids: list[str],
    prompt: str,
    first_message: str,
    settings: dict[str, Any],
    knowledge_base: list[dict[str, str]] | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": settings["agent_name"],
        "conversation_config": build_conversation_config(
            prompt, first_message, tool_ids, settings, knowledge_base, scenario_config
        ),
    }
    return request("POST", "/convai/agents/create", payload, base_url=settings["base_url"])


def update_agent(
    agent_id: str,
    tool_ids: list[str],
    prompt: str,
    first_message: str,
    settings: dict[str, Any],
    knowledge_base: list[dict[str, str]] | None = None,
    scenario_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "name": settings["agent_name"],
        "conversation_config": build_conversation_config(
            prompt, first_message, tool_ids, settings, knowledge_base, scenario_config
        ),
    }
    return request("PATCH", f"/convai/agents/{agent_id}", payload, base_url=settings["base_url"])


def get_agent(agent_id: str, settings: dict[str, Any]) -> dict[str, Any]:
    return request("GET", f"/convai/agents/{agent_id}", base_url=settings["base_url"])


def resolve_agent_id(settings: dict[str, Any]) -> str | None:
    if settings.get("agent_id"):
        return settings["agent_id"]
    return read_text_file(AGENT_ID_FILE)


def write_agent_id(agent_id: str) -> None:
    AGENT_ID_FILE.write_text(agent_id.strip() + "\n", encoding="utf-8")


def main() -> int:
    if not API_KEY:
        print("ELEVENLABS_API_KEY missing", file=sys.stderr)
        return 2
    if not TOOL_SECRET:
        print("ELEVENLABS_TOOL_SECRET missing", file=sys.stderr)
        return 2

    variant, prompt, first_message, knowledge_base_ids, scenario_config = prompt_bundle()
    settings = load_effective_settings(scenario_config)
    if not settings["public_base_url"]:
        print("ASCOLTA_PUBLIC_BASE_URL missing", file=sys.stderr)
        return 2

    knowledge_base = _format_knowledge_base(knowledge_base_ids, settings)
    agent_id = resolve_agent_id(settings)
    created_tools: list[dict[str, str | None]] = []
    tool_ids: list[str] = []
    update_only = settings.get("update_only", False)
    refresh_tools = settings.get("refresh_tools", False)

    if agent_id and update_only and not refresh_tools:
        agent_data = get_agent(agent_id, settings)
        tool_ids = (
            agent_data.get("conversation_config", {})
            .get("agent", {})
            .get("prompt", {})
            .get("tool_ids")
            or []
        )
    else:
        for tool in load_tool_definitions(scenario_config):
            created = create_tool(
                tool["name"],
                tool["description"],
                tool["parameters"],
                public_base_url=settings["public_base_url"],
                base_url=settings["base_url"],
            )
            created_tools.append(
                {"name": tool["name"], "id": created.get("tool_id") or created.get("id")}
            )
        tool_ids = [str(item["id"]) for item in created_tools if item["id"]]

    if agent_id:
        agent = update_agent(agent_id, tool_ids, prompt, first_message, settings, knowledge_base, scenario_config)
    else:
        if update_only:
            print("ELEVENLABS_AGENT_ID missing for update-only run", file=sys.stderr)
            return 2
        agent = create_agent(tool_ids, prompt, first_message, settings, knowledge_base, scenario_config)
        created_id = agent.get("agent_id") or agent.get("id")
        if created_id:
            write_agent_id(str(created_id))

    current_id = agent_id or agent.get("agent_id") or agent.get("id")
    print(
        json.dumps(
            {
                "variant": variant,
                "agent_id": current_id,
                "tools": created_tools,
                "agent": agent,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
