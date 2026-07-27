"""
Ported from earlier-prototype via ascolta-salvage-2026-07-24, adapted for ascolta.
Self-contained: no import/runtime dependency on the earlier-prototype or ascolta directories.
Status: starting point for Milestone 5 (see README) - not yet wired into
app.services.voice.factory / CallManager. Config/env resolution here is still
file-based (ascolta-stack-config.json); the DB-driven credential/config
resolution (CredentialsManager.get_credentials_with_fallback) will replace it
when the concrete voice engine classes are implemented.
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

from app.integrations.common.config import load_config, load_realtime_config
from app.integrations.common.tools import build_tools
from livekit.agents import Agent, AgentServer, AgentSession, JobContext, RunContext, cli, function_tool
from livekit.agents.llm.tool_context import ToolFlag
from livekit.plugins import openai, xai
from app.integrations.voice_core.scenario import resolve_voice_bundle

DEFAULT_AGENT_NAME = os.environ.get("ASCOLTA_LIVEKIT_AGENT_NAME", "ascolta-livekit")
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
    module_path = ROOT / "runtime" / "realtime_service.py"
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


@server.rtc_session(agent_name=DEFAULT_AGENT_NAME)
async def entrypoint(ctx: JobContext) -> None:
    call_started = time.monotonic()
    config = load_config()
    realtime_cfg = load_realtime_config(config)
    bundle = resolve_voice_bundle("realtime")
    minimal_latency_test = bool(realtime_cfg.get("minimal_latency_test")) or os.environ.get("ASCOLTA_MINIMAL_LATENCY_TEST", "").lower() in {"1", "true", "yes", "on"}
    if minimal_latency_test:
        logging.info("LiveKit minimal latency test enabled: tools disabled and prompt minimized")
        tools = []
        prompt_text = "Rispondi garbatamente, in modo molto breve e naturale, nella lingua dell'interlocutore."
        first_message = "Salve, sono un assistente AI. Come posso aiutarla?"
    else:
        controller = _load_legacy_controller()
        caller_phone = _extract_caller_phone(ctx)
        tools = _livekit_tools(controller, caller_phone, bundle.scenario_config)
        prompt_text = bundle.prompt_text
        first_message = bundle.first_message

    provider = str(realtime_cfg.get("provider") or "xai").strip().lower()
    if provider == "openai":
        model = str(realtime_cfg.get("model") or "gpt-realtime").strip() or "gpt-realtime"
        voice = str(realtime_cfg.get("voice") or "marin").strip() or "marin"
        realtime_model = openai.realtime.RealtimeModel(model=model, voice=voice)
    else:
        model = str(realtime_cfg.get("model") or "grok-voice-fast-1.0").strip() or "grok-voice-fast-1.0"
        voice = str(realtime_cfg.get("voice") or "eve").strip() or "eve"
        if voice.islower():
            voice = voice.title()
        realtime_model = xai.realtime.RealtimeModel(model=model, voice=voice)
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
