"""
Ported from earlier-prototype via ascolta-salvage-2026-07-24, adapted for ascolta.

18/08/2026 (Grok/xAI priority - see memory ascolta-grok-priority): config
resolution switched from the static file loader (load_config/
load_realtime_config/resolve_voice_bundle - earlier-prototype's original, single-tenant
approach) to the Fase 2 kernel resolver (app.services.agent_versions.
resolve_inbound), keyed on the SIP trunk's dialed number instead of a
process-wide config file. Same contract as ADR-0002: the algorithm (LiveKit
session tuning, endpointing/interruption/preemptive-generation config,
latency logging) is earlier-prototype's, unchanged; the config *source* is the kernel,
not a file.

Tools deliberately NOT wired to the resolver yet (kept as _livekit_tools/
_load_legacy_controller below, unused for now): the Tool Registry governance
layer (policy/idempotency/audit) is Fase 4, not built. Every call answered
through this worker today runs with tools=[] - a real, honest scope limit,
not an oversight.

NOT VERIFIED against a live LiveKit connection - this environment has no
network path to a real LiveKit server/SIP trunk. Verified: py_compile,
that resolve_inbound() (already proven end-to-end against calls.py's
webhook path) is called correctly here too. The LiveKit-specific parts
(wait_for_participant, sip.trunkPhoneNumber attribute) are implemented per
LiveKit's own docs (confirmed via WebSearch before writing this, not
guessed) but need a real inbound SIP call to confirm end-to-end - same
kind of gap as the Dockerfile before it was build-tested.
"""
from __future__ import annotations

import importlib.util
import json
import logging
import os
import sys
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.integrations.common.tools import build_tools
from app.services.agent_versions import resolve_inbound, resolve_provider_api_key
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, RunContext, cli, function_tool
from livekit.agents.llm.tool_context import ToolFlag
from livekit.plugins import openai, xai

DEFAULT_AGENT_NAME = os.environ.get("ASCOLTA_LIVEKIT_AGENT_NAME", "ascolta-livekit")
FALLBACK_PROMPT = (
    "Rispondi in modo cortese e sintetico, nella lingua dell'interlocutore. "
    "Se non hai informazioni certe sull'argomento, dillo esplicitamente invece di inventare."
)
FALLBACK_FIRST_MESSAGE = "Salve, sono un assistente AI. Come posso aiutarla?"
WRITE_TOOL_NAMES = {
    "calcom_book_appointment",
    "calcom_reschedule_booking",
    "calcom_cancel_booking",
    "calendar_create",
    "calendar_edit",
    "calendar_delete",
    "tasks_create",
    "tasks_edit",
    "tasks_complete",
    "tasks_delete",
    "contacts_create",
    "contacts_edit",
    "contacts_delete",
}


@lru_cache(maxsize=1)
def _load_legacy_controller() -> Any:
    module_path = ROOT / "runtime_workers" / "realtime_service.py"
    spec = importlib.util.spec_from_file_location("ascolta_realtime_service", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load legacy controller from {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module.LegacyController()


def _jsonish(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def _extract_caller_phone(ctx: JobContext) -> str | None:
    candidates: list[Any] = []
    for attr in ("metadata",):
        candidates.append(getattr(ctx, attr, None))
    job = getattr(ctx, "job", None)
    if job is not None:
        candidates.append(getattr(job, "metadata", None))
    room = getattr(ctx, "room", None)
    if room is not None:
        candidates.append(getattr(room, "metadata", None))

    for candidate in candidates:
        mapping = _jsonish(candidate)
        if not mapping:
            continue
        for key in (
            "caller_number",
            "caller_phone",
            "system__caller_id",
            "phone",
            "from",
            "callerId",
        ):
            value = mapping.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def _livekit_tools(controller: Any, caller_phone: str | None, scenario_config: dict[str, Any]) -> list[Any]:
    tool_defs = build_tools(scenario_config)
    tools: list[Any] = []

    for spec in tool_defs:
        if spec.get("type") != "function":
            continue
        name = str(spec.get("name") or "").strip()
        if not name:
            continue

        description = str(spec.get("description") or name)
        raw_schema = dict(spec)

        async def _handler(raw_arguments: dict[str, object], context: RunContext, *, _tool_name: str = name) -> Any:
            args = dict(raw_arguments or {})
            if caller_phone:
                args.setdefault("caller_phone", caller_phone)
                args.setdefault("phone", caller_phone)
            if _tool_name in WRITE_TOOL_NAMES:
                context.disallow_interruptions()
            try:
                return await controller.call_tool(_tool_name, args)
            except Exception:
                logging.exception("LiveKit tool failed: %s", _tool_name)
                raise

        tools.append(
            function_tool(
                _handler,
                name=name,
                description=description,
                raw_schema=raw_schema,
                flags=ToolFlag.IGNORE_ON_ENTER,
            )
        )

    return tools


class LegacyPrototypeLiveKitAgent(Agent):
    def __init__(self, *, instructions: str, tools: list[Any]) -> None:
        super().__init__(instructions=instructions, tools=tools, allow_interruptions=True)


_agent_server_kwargs: dict[str, Any] = {
    "log_level": os.environ.get("LIVEKIT_LOG_LEVEL", "info"),
    "load_threshold": float(os.environ.get("LIVEKIT_LOAD_THRESHOLD", "999")),
}
if os.environ.get("LIVEKIT_WORKER_PORT"):
    _agent_server_kwargs["port"] = int(os.environ["LIVEKIT_WORKER_PORT"])

server = AgentServer(**_agent_server_kwargs)


async def _resolve_trunk_number(ctx: JobContext) -> str | None:
    """
    The dialed number for an inbound SIP call arrives as a participant
    attribute (sip.trunkPhoneNumber), not in job/room metadata - confirmed
    via LiveKit's own docs before writing this (see module docstring), the
    same way OpenAI's "To" SIP header was confirmed before webhook.py's
    resolver. wait_for_participant() returns immediately if the SIP
    participant already joined, otherwise waits for it.
    """
    try:
        participant = await ctx.wait_for_participant()
    except Exception:
        logging.exception("wait_for_participant failed - no SIP participant joined?")
        return None
    number = (participant.attributes or {}).get("sip.trunkPhoneNumber")
    return number.strip() if isinstance(number, str) and number.strip() else None


@server.rtc_session(agent_name=DEFAULT_AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    call_started = time.monotonic()

    # Fase 2 kernel resolver (app.services.agent_versions.resolve_inbound),
    # not earlier-prototype's static config file - see module docstring. `resolved`
    # is None both when the number has no active inbound_endpoint and when
    # extraction itself fails; either way this is a tracked fallback
    # (logged below), never a silent "just answer somehow" (ADR-0001 rule
    # 9), same policy already applied to the OpenAI SIP path.
    trunk_number = await _resolve_trunk_number(ctx)
    resolved = await resolve_inbound(trunk_number) if trunk_number else None

    if trunk_number and not resolved:
        logging.warning(
            f"Nessun inbound_endpoint attivo per '{trunk_number}' (LiveKit) - "
            f"fallback su prompt generico."
        )
    elif not trunk_number:
        logging.warning("sip.trunkPhoneNumber non disponibile sul participant - fallback su prompt generico.")
    else:
        logging.info(
            f"Inbound LiveKit risolto: '{trunk_number}' -> tenant={resolved['tenant_id']} "
            f"project={resolved['project_id']} agent_version={resolved['agent_version_id']}"
        )

    # Tools deliberately not wired here yet - Fase 4 (Tool Registry), see
    # module docstring. _livekit_tools/_load_legacy_controller are kept in
    # this file, unused, for when that governance layer exists.
    tools: list[Any] = []
    prompt_text = (resolved or {}).get("prompt_a") or FALLBACK_PROMPT
    first_message = (resolved or {}).get("consent_message") or FALLBACK_FIRST_MESSAGE

    provider_raw = (resolved or {}).get("voice_engine") or "livekit_xai"
    provider = "openai" if "openai" in provider_raw else "xai"
    if provider == "openai":
        model = "gpt-realtime"
        voice = (resolved or {}).get("voice_name") or "marin"
        openai_api_key = await resolve_provider_api_key((resolved or {}).get("tenant_id"), "openai")
        if not openai_api_key:
            raise RuntimeError(
                f"Nessuna credenziale voice/openai per tenant={((resolved or {}).get('tenant_id'))} - "
                f"niente fallback su env (richiesta esplicita 18/08), la chiamata non puo' procedere."
            )
        realtime_model = openai.realtime.RealtimeModel(model=model, voice=voice, api_key=openai_api_key)
    else:
        model = "grok-voice-fast-1.0"
        voice = (resolved or {}).get("voice_name") or "eve"
        if voice.islower():
            voice = voice.title()
        xai_api_key = await resolve_provider_api_key((resolved or {}).get("tenant_id"), "xai")
        if not xai_api_key:
            raise RuntimeError(
                f"Nessuna credenziale voice/xai per tenant={((resolved or {}).get('tenant_id'))} - "
                f"niente fallback su env (richiesta esplicita 18/08), la chiamata non puo' procedere."
            )
        realtime_model = xai.realtime.RealtimeModel(model=model, voice=voice, api_key=xai_api_key)
    logging.info("LiveKit realtime provider=%s model=%s voice=%s", provider, model, voice)

    session = AgentSession(
        llm=realtime_model,
        turn_handling={
            "endpointing": {
                "mode": "dynamic",
                "min_delay": float(os.environ.get("ASCOLTA_ENDPOINTING_MIN_DELAY", "0.12")),
                "max_delay": float(os.environ.get("ASCOLTA_ENDPOINTING_MAX_DELAY", "0.65")),
                "alpha": float(os.environ.get("ASCOLTA_ENDPOINTING_ALPHA", "0.55")),
            },
            "interruption": {
                "enabled": True,
                "mode": "vad",
                "discard_audio_if_uninterruptible": True,
                "min_duration": float(os.environ.get("ASCOLTA_INTERRUPTION_MIN_DURATION", "0.12")),
                "min_words": int(os.environ.get("ASCOLTA_INTERRUPTION_MIN_WORDS", "0")),
                "resume_false_interruption": False,
            },
            "preemptive_generation": {
                "enabled": True,
                "preemptive_tts": True,
                "max_speech_duration": float(os.environ.get("ASCOLTA_PREEMPTIVE_MAX_SPEECH_DURATION", "5.0")),
                "max_retries": int(os.environ.get("ASCOLTA_PREEMPTIVE_MAX_RETRIES", "1")),
            },
        },
    )

    @session.on("agent_state_changed")
    def _on_agent_state_changed(event: Any) -> None:
        logging.info(
            "LiveKit latency state agent old=%s new=%s since_call_start=%.3fs",
            getattr(event, "old_state", ""),
            getattr(event, "new_state", ""),
            time.monotonic() - call_started,
        )

    @session.on("user_state_changed")
    def _on_user_state_changed(event: Any) -> None:
        logging.info(
            "LiveKit latency state user old=%s new=%s since_call_start=%.3fs",
            getattr(event, "old_state", ""),
            getattr(event, "new_state", ""),
            time.monotonic() - call_started,
        )

    @session.on("user_input_transcribed")
    def _on_user_input_transcribed(event: Any) -> None:
        if not getattr(event, "is_final", False):
            return
        logging.info(
            "LiveKit latency user_final_transcript chars=%s since_call_start=%.3fs text=%r",
            len(getattr(event, "transcript", "") or ""),
            time.monotonic() - call_started,
            (getattr(event, "transcript", "") or "")[:160],
        )

    @session.on("conversation_item_added")
    def _on_conversation_item_added(event: Any) -> None:
        item = getattr(event, "item", None)
        role = getattr(item, "role", "")
        metrics = getattr(item, "metrics", None)
        logging.info(
            "LiveKit latency conversation_item role=%s metrics=%s since_call_start=%.3fs",
            role,
            metrics,
            time.monotonic() - call_started,
        )

    agent = LegacyPrototypeLiveKitAgent(
        instructions=prompt_text,
        tools=tools,
    )

    await session.start(room=ctx.room, agent=agent)
    await session.generate_reply(
        instructions=(
            "Pronuncia subito e integralmente il seguente messaggio iniziale, "
            "senza riassumerlo, senza cambiarne lingua o ordine, e senza aggiungere altro prima: "
            f"{first_message}"
        )
    )


if __name__ == "__main__":
    cli.run_app(server)
