#!/usr/bin/env python3
"""
Ported from earlier-prototype via ascolta-salvage-2026-07-24, adapted for ascolta.
Self-contained: no import/runtime dependency on the earlier-prototype or ascolta directories.

18/08/2026 (Grok/xAI priority - see memory ascolta-grok-priority, and
runtime_workers/livekit_agent.py's identical treatment): the
"realtime.call.incoming" path in handle_webhook() no longer resolves
prompt/voice/language from the static scenario config file - it calls the
Fase 2 kernel resolver (app.services.agent_versions.resolve_inbound()),
keyed on the SIP "To" header, same as webhook.py's OpenAI path.

Per explicit request ("non voglio il fallback su .env"): the xAI api_key is
NO LONGER read from an environment variable at all, anywhere, including at
process startup - LegacyController.__init__() no longer builds an
AsyncOpenAI client or requires XAI_API_KEY. The key is resolved strictly
per-tenant (resolve_provider_api_key(), CredentialsManager, service_type
"voice", provider "xai") once a call's dialed number resolves to a tenant.
No resolvable tenant or no stored credential for it = the call is declined
(see handle_webhook), never answered with a fallback/shared/global key.

Tools (call_tool/handle_function_call, Cal.com/Nextcloud) intentionally
UNTOUCHED by this pass - still built once at startup from the static
scenario_config file (self.tools = build_tools(scenario_config) in
__init__). Same scope limit as the LiveKit worker: the Tool Registry
governance layer is Fase 4, not built, so wiring tools to real per-tenant
config now would be built on sand. Every call answered by this worker
today runs with the tools defined in whatever scenario file happened to be
loaded at process startup, regardless of which tenant actually answers -
a known, deliberate gap, not silently ignored.

NOT VERIFIED against a live xAI SIP call or webhook (no network path to
xAI/a real SIP trunk from this environment). Verified: py_compile, a full
in-process handle_webhook() call with a synthetic realtime.call.incoming
payload - correctly resolves tenant/project/prompt/voice/api_key for a
known number, and declines (not crashes) for an unresolvable one.
"""
import asyncio
import json
import logging
import os
import re
import signal
import sys
from types import SimpleNamespace
from difflib import SequenceMatcher
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode
from typing import Any
from zoneinfo import ZoneInfo

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import httpx
import websockets
from openai import AsyncOpenAI

from app.database.db import get_database
from app.integrations.common.config import active_services, load_config, load_realtime_config, load_scenario_config, resolve_scenario
from app.integrations.common.tools import build_tools
from app.integrations.voice_core.scenario import resolve_voice_bundle
from app.integrations.voice_core.state import VoiceCallState, VoiceStateStore
from app.integrations.voice_core.xai_session import build_xai_session_update
from app.models.schemas import CallStatus
from app.services.agent_versions import resolve_inbound, resolve_provider_api_key

SERVICE_DIR = Path(__file__).resolve().parent
ROOT = SERVICE_DIR
DEFAULT_ENV = Path(os.environ.get("ASCOLTA_GLOBAL_ENV") or REPO_ROOT / ".env")
NC_API = os.environ.get("NC_API_PATH") or str(REPO_ROOT / "workspace" / "scripts" / "nc-api")
ELEVEN_TRANSCRIPTS_DIR = REPO_ROOT / "runtime" / "transcripts"
CONFIG_PATH = Path(os.environ.get("ASCOLTA_CONFIG_PATH") or REPO_ROOT / "ascolta-stack-config.json")
def load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def setup_logging() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    log_path = ROOT / "service.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(),
        ],
    )


def read_text_file(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return content or None
class LegacyController:
    calcom_default_event_type_id: str | None = None
    calcom_standard_event_type_id: str | None = None
    calcom_sport_event_type_id: str | None = None

    def __init__(self) -> None:
        cfg = load_config()
        response_cfg = cfg.get("response") if isinstance(cfg.get("response"), dict) else {}
        realtime_cfg = load_realtime_config(cfg)
        calcom_cfg = cfg.get("calcom") if isinstance(cfg.get("calcom"), dict) else {}
        scenario = resolve_scenario(cfg, "realtime")
        scenario_config = load_scenario_config(scenario.get("config_path"))

        self.response_language = str(response_cfg.get("language") or "it").strip().lower()
        self.provider = str(realtime_cfg.get("provider") or os.environ.get("ASCOLTA_REALTIME_PROVIDER") or "openai").strip().lower()
        self.model = realtime_cfg.get("model") or ("grok-voice-latest" if self.provider in {"xai", "grok"} else "gpt-realtime-mini")
        self.voice = realtime_cfg.get("voice") or ("eve" if self.provider in {"xai", "grok"} else "sage")
        self.input_format = realtime_cfg.get("input_format") or "audio/pcma"
        self.output_format = realtime_cfg.get("output_format") or "audio/pcma"
        self.webhook_secret = (
            os.environ.get("XAI_WEBHOOK_SECRET", "").strip()
            or os.environ.get("OPENAI_WEBHOOK_SECRET", "").strip()
            or None
        )
        self.elevenlabs_tool_secret = os.environ.get("ELEVENLABS_TOOL_SECRET", "").strip() or None
        self.calcom_api_key = os.environ.get("CALCOM_API_KEY", "").strip() or None
        self.calcom_base_url = str(calcom_cfg.get("base_url") or "https://api.cal.com/v2").rstrip("/")
        self.calcom_default_username = str(calcom_cfg.get("username") or "").strip() or None
        self.calcom_default_event_type_id = str(calcom_cfg.get("event_type_id") or "").strip() or None
        self.calcom_standard_event_type_id = str(calcom_cfg.get("standard_event_type_id") or "").strip() or None
        self.calcom_sport_event_type_id = str(calcom_cfg.get("sport_event_type_id") or "").strip() or None

        # 18/08: NO client built here anymore, and no XAI_API_KEY/OPENAI_API_KEY
        # read from env at all - explicit request from maintainer ("non voglio il
        # fallback su .env"). The api_key is per-tenant, only known once a call
        # comes in and the kernel resolver (resolve_inbound) says which tenant
        # it belongs to - see handle_webhook() below, which builds a fresh
        # AsyncOpenAI client per call instead of once here at startup.
        # base_url/websocket_base_url are NOT secrets (they're the same xAI
        # endpoint for everyone), kept as process-level config.
        self.xai_base_url = str(realtime_cfg.get("base_url") or "https://api.x.ai/v1").rstrip("/")
        self.xai_websocket_base_url = str(realtime_cfg.get("websocket_base_url") or "wss://api.x.ai/v1/realtime").rstrip("/")

        self.tools = build_tools(scenario_config)
        self.active_calls: dict[str, asyncio.Task[Any]] = {}
        self.call_context = VoiceStateStore()

    def prompt_bundle(self) -> tuple[str, str, str]:
        bundle = resolve_voice_bundle("realtime")
        return bundle.scenario_name, bundle.prompt_text, bundle.first_message

    def store_elevenlabs_transcript(self, payload: dict[str, Any]) -> dict[str, Any]:
        ELEVEN_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
        data = payload.get("data") or payload
        conversation_id = data.get("conversation_id") or f"unknown-{int(datetime.now().timestamp())}"
        transcript = data.get("transcript") or []
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        json_path = ELEVEN_TRANSCRIPTS_DIR / f"{conversation_id}.json"
        md_path = ELEVEN_TRANSCRIPTS_DIR / f"{conversation_id}.md"
        metrics_path = ELEVEN_TRANSCRIPTS_DIR / f"{conversation_id}.latency.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

        metrics: dict[str, Any] = {
            "conversation_id": conversation_id,
            "event_timestamp": payload.get("event_timestamp"),
            "metadata": metadata,
            "turns": [],
            "summary": {},
        }
        assistant_latencies: list[float] = []
        previous_user_time: float | None = None

        lines = [f"# ElevenLabs Transcript {conversation_id}", ""]
        if metadata:
            lines.append("## Metadata")
            lines.append("")
            for key in ("start_time_unix_secs", "call_duration_secs", "cost", "phone_call"):
                if key in metadata:
                    lines.append(f"- `{key}`: `{metadata.get(key)}`")
            lines.append("")

        if isinstance(transcript, list):
            for idx, turn in enumerate(transcript):
                if not isinstance(turn, dict):
                    continue
                role = turn.get("role") or turn.get("speaker") or "unknown"
                text = turn.get("message") or turn.get("text") or turn.get("content") or ""
                time_in_call = turn.get("time_in_call_secs")
                turn_metrics = turn.get("conversation_turn_metrics")
                latency_from_previous_user = None
                if isinstance(time_in_call, (int, float)):
                    if str(role).lower() in {"user", "caller"}:
                        previous_user_time = float(time_in_call)
                    elif previous_user_time is not None:
                        latency_from_previous_user = max(0.0, float(time_in_call) - previous_user_time)
                        assistant_latencies.append(latency_from_previous_user)

                metrics["turns"].append({
                    "index": idx,
                    "role": role,
                    "time_in_call_secs": time_in_call,
                    "latency_from_previous_user_turn_secs": latency_from_previous_user,
                    "conversation_turn_metrics": turn_metrics,
                    "text_chars": len(str(text)),
                })

                prefix = f"[{time_in_call}s] " if time_in_call is not None else ""
                if text:
                    lines.append(f"**{prefix}{role}**: {text}")
                    if latency_from_previous_user is not None:
                        lines.append(f"`latency_from_previous_user_turn_secs`: {latency_from_previous_user:.3f}")
                    if turn_metrics:
                        lines.append(f"`conversation_turn_metrics`: `{json.dumps(turn_metrics, ensure_ascii=False)}`")
                    lines.append("")

        if assistant_latencies:
            metrics["summary"] = {
                "assistant_turn_count": len(assistant_latencies),
                "latency_min_secs": min(assistant_latencies),
                "latency_max_secs": max(assistant_latencies),
                "latency_avg_secs": sum(assistant_latencies) / len(assistant_latencies),
            }
            lines.append("## Latency Summary")
            lines.append("")
            for key, value in metrics["summary"].items():
                if isinstance(value, float):
                    lines.append(f"- `{key}`: `{value:.3f}`")
                else:
                    lines.append(f"- `{key}`: `{value}`")
            lines.append("")

        metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2))
        md_path.write_text("\n".join(lines))
        logging.info("ElevenLabs transcript stored conversation_id=%s latency_summary=%s", conversation_id, metrics.get("summary"))
        return {
            "status": "ok",
            "conversation_id": conversation_id,
            "json_path": str(json_path),
            "markdown_path": str(md_path),
            "latency_path": str(metrics_path),
            "latency_summary": metrics.get("summary"),
        }

    async def run_nc_api(self, *args: str) -> dict[str, Any]:
        proc = await asyncio.create_subprocess_exec(
            NC_API,
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(stderr.decode().strip() or stdout.decode().strip() or f"nc-api failed ({proc.returncode})")
        return json.loads(stdout.decode())

    async def calcom_request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        api_version: str = "2024-08-13",
    ) -> dict[str, Any]:
        if not self.calcom_api_key:
            raise RuntimeError("CALCOM_API_KEY missing")
        headers = {
            "Authorization": f"Bearer {self.calcom_api_key}",
            "Content-Type": "application/json",
            "cal-api-version": api_version,
        }
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.request(
                method,
                f"{self.calcom_base_url}{path}",
                headers=headers,
                json=payload,
                params=params,
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError:
            logging.getLogger(__name__).error(
                "Cal.com error %s %s -> %s: %s",
                method,
                path,
                response.status_code,
                response.text,
            )
            raise
        return response.json()

    def to_utc_iso(self, value: str) -> str:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Europe/Rome"))
        return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def sanitize_isoish_datetime(self, value: str) -> str:
        cleaned = value.strip()
        # Fix malformed times like 2026-03-16T17:0000.000+01:00 -> 2026-03-16T17:00:00.000+01:00
        cleaned = re.sub(r"T(\d{2}):(\d{2})(\d{2}\.\d+)([+-]\d{2}:\d{2})$", r"T\1:\2:\3\4", cleaned)
        # Fix compact minute+second forms like T170000+01:00 or T170000.000+01:00
        cleaned = re.sub(r"T(\d{2})(\d{2})(\d{2}(?:\.\d+)?)([+-]\d{2}:\d{2})$", r"T\1:\2:\3\4", cleaned)
        return cleaned

    def parse_rome_datetime(self, value: str) -> datetime:
        dt = datetime.fromisoformat(self.sanitize_isoish_datetime(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo("Europe/Rome"))
        return dt.astimezone(ZoneInfo("Europe/Rome"))

    def snap_past_datetime_forward(self, dt: datetime) -> datetime:
        now = datetime.now(ZoneInfo("Europe/Rome"))
        if dt >= now:
            return dt
        days_ahead = (dt.weekday() - now.weekday()) % 7
        candidate = now.replace(
            hour=dt.hour,
            minute=dt.minute,
            second=dt.second,
            microsecond=dt.microsecond,
        ) + timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
        return candidate

    def normalize_local_datetime(self, value: str) -> str:
        dt = self.parse_rome_datetime(value)
        normalized = self.snap_past_datetime_forward(dt)
        return normalized.isoformat()

    def normalize_local_range(self, start_value: str, end_value: str) -> tuple[str, str]:
        start_dt = self.parse_rome_datetime(start_value)
        end_dt = self.parse_rome_datetime(end_value)
        now = datetime.now(ZoneInfo("Europe/Rome"))
        if end_dt > now:
            if start_dt < now:
                start_dt = now
            return start_dt.isoformat(), end_dt.isoformat()
        if end_dt <= start_dt:
            end_dt = start_dt + timedelta(days=7)
        duration = end_dt - start_dt
        normalized_start = self.snap_past_datetime_forward(start_dt)
        normalized_end = normalized_start + duration
        return normalized_start.isoformat(), normalized_end.isoformat()

    def extract_phone_from_sip_headers(self, sip_headers: list[Any]) -> str | None:
        return self.extract_header_value(sip_headers, {"from", "p-asserted-identity", "remote-party-id"})

    def extract_header_value(self, sip_headers: list[Any], header_names: set[str]) -> str | None:
        """
        Generalized version of extract_phone_from_sip_headers (which now
        delegates here) - added 18/08 to also read the "To" header (the
        dialed number), needed by the kernel resolver in handle_webhook().
        Same regex, same header dict/object shape handling.
        """
        for header in sip_headers or []:
            if isinstance(header, dict):
                name = header.get("name", "") or ""
                value = header.get("value", "") or ""
            else:
                name = getattr(header, "name", "") or ""
                value = getattr(header, "value", "") or ""
            if name.lower() not in header_names:
                continue
            match = re.search(r"(?:sip:|tel:)(\+?[0-9][0-9]{5,})", value)
            if match:
                return match.group(1)
        return None

    def normalize_phone_number(self, value: str | None) -> str | None:
        if not value:
            return None
        raw = re.sub(r"[^\d+]", "", value.strip())
        if not raw:
            return None
        if raw.startswith("+"):
            digits = "+" + re.sub(r"\D", "", raw[1:])
            return digits if len(digits) >= 8 else None
        digits = re.sub(r"\D", "", raw)
        if digits.startswith("39") and len(digits) >= 10:
            return f"+{digits}"
        if digits.startswith("0") and len(digits) >= 8:
            return f"+39{digits}"
        if len(digits) in {9, 10}:
            return f"+39{digits}"
        return None

    def extract_phone_from_text(self, text: str | None) -> str | None:
        if not text:
            return None
        matches = re.findall(r"(?:\+?\d[\d\s\-]{6,}\d)", text)
        for match in matches:
            normalized = self.normalize_phone_number(match)
            if normalized:
                return normalized
        return None

    def infer_visit_kind(self, value: str | None) -> str | None:
        if not value:
            return None
        text = value.lower()
        sport_markers = (
            "sport",
            "sportiv",
            "agonistic",
            "agonist",
            "agonistico",
            "agonistica",
            "idoneit",
            "certificat",
            "pallanuoto",
        )
        if any(marker in text for marker in sport_markers):
            return "sport"
        standard_markers = (
            "standard",
            "visita",
            "controll",
            "dolor",
            "ricetta",
        )
        if any(marker in text for marker in standard_markers):
            return "standard"
        return None

    def resolve_event_type_id(self, requested: str | None = None, arguments: dict[str, Any] | None = None) -> int:
        default_id = getattr(self, "calcom_default_event_type_id", None)
        standard_id = getattr(self, "calcom_standard_event_type_id", None)
        sport_id = getattr(self, "calcom_sport_event_type_id", None)
        inferred_kind = self.infer_visit_kind(requested)
        if not inferred_kind and arguments:
            for key in ("appointment_type", "appointment_type", "event_type_id", "execution_message", "notes", "reason_hint"):
                inferred_kind = self.infer_visit_kind(str(arguments.get(key) or ""))
                if inferred_kind:
                    break

        if inferred_kind == "sport" and sport_id:
            value = sport_id
        elif inferred_kind == "standard":
            value = standard_id or default_id
        else:
            normalized = (requested or "").strip().lower()
            if normalized in {"sport", "sportiva", "sportivo", "agonistica", "agonistico"} and sport_id:
                value = sport_id
            elif normalized in {"standard", "standard", "standard", "visita", "visita standard"}:
                value = standard_id or default_id
            else:
                value = requested or standard_id or default_id

        if not value:
            raise RuntimeError("Cal.com eventTypeId missing")
        return int(value)

    def normalize_name(self, value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()

    def annotate_slot_days(self, response: dict[str, Any]) -> dict[str, Any]:
        data = response.get("data")
        if not isinstance(data, dict):
            return response
        weekday_it = {
            "Monday": "lunedì",
            "Tuesday": "martedì",
            "Wednesday": "mercoledì",
            "Thursday": "giovedì",
            "Friday": "venerdì",
            "Saturday": "sabato",
            "Sunday": "domenica",
        }
        month_it = {
            1: "gennaio",
            2: "febbraio",
            3: "marzo",
            4: "aprile",
            5: "maggio",
            6: "giugno",
            7: "luglio",
            8: "agosto",
            9: "settembre",
            10: "ottobre",
            11: "novembre",
            12: "dicembre",
        }
        annotated: list[dict[str, Any]] = []
        spoken_options: list[dict[str, Any]] = []
        for day, slots in data.items():
            try:
                dt = datetime.fromisoformat(str(day)).replace(tzinfo=ZoneInfo("Europe/Rome"))
                weekday = dt.strftime("%A")
                weekday_label = weekday_it.get(weekday, weekday)
                date_label = f"{dt.day} {month_it.get(dt.month, dt.strftime('%B'))}"
            except Exception:
                weekday = None
                weekday_label = None
                date_label = str(day)
            annotated.append(
                {
                    "date": day,
                    "weekday": weekday,
                    "weekdayIt": weekday_label,
                    "dateLabelIt": date_label,
                    "slots": slots,
                }
            )
            if slots and len(spoken_options) < 4:
                first = slots[0]
                start = first.get("start") if isinstance(first, dict) else None
                time_label = None
                if isinstance(start, str):
                    try:
                        start_dt = self.normalize_local_datetime(start)
                        time_label = start_dt.strftime("%H:%M")
                    except Exception:
                        time_label = None
                spoken_options.append(
                    {
                        "date": day,
                        "weekday": weekday,
                        "weekdayIt": weekday_label,
                        "dateLabelIt": date_label,
                        "time": time_label,
                        "start": start,
                        "spoken": " ".join(
                            part for part in [weekday_label, date_label, f"alle {time_label}" if time_label else None] if part
                        ),
                    }
                )
        response["annotatedDays"] = annotated
        response["spokenOptions"] = spoken_options
        return response

    def booking_phone(self, booking: dict[str, Any]) -> str | None:
        attendees = booking.get("attendees") or []
        for attendee in attendees:
            phone = attendee.get("phoneNumber")
            if phone:
                return phone
        fields = booking.get("bookingFieldsResponses") or {}
        return fields.get("attendeePhoneNumber")

    def booking_names(self, booking: dict[str, Any]) -> list[str]:
        names: list[str] = []
        for attendee in booking.get("attendees") or []:
            if attendee.get("name"):
                names.append(attendee["name"])
        fields = booking.get("bookingFieldsResponses") or {}
        if fields.get("name"):
            names.append(fields["name"])
        return names

    def booking_name_score(self, booking: dict[str, Any], target_name: str) -> float:
        target = self.normalize_name(target_name)
        if not target:
            return 0.0
        scores = []
        for candidate in self.booking_names(booking):
            norm = self.normalize_name(candidate)
            if not norm:
                continue
            scores.append(SequenceMatcher(None, target, norm).ratio())
        return max(scores, default=0.0)

    def booking_reason_score(self, booking: dict[str, Any], reason_hint: str) -> float:
        target = self.normalize_name(reason_hint)
        if not target:
            return 0.0
        metadata = booking.get("metadata") or {}
        haystack = " ".join(
            filter(
                None,
                [
                    metadata.get("execution_message"),
                    metadata.get("notes"),
                    booking.get("title"),
                    booking.get("description"),
                ],
            )
        )
        norm = self.normalize_name(haystack)
        if not norm:
            return 0.0
        if target in norm:
            return 1.0
        return SequenceMatcher(None, target, norm).ratio()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        call_id: str | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        if name == "search_knowledge_base":
            # project_id is stashed in scenario_name and tenant_id in
            # metadata by the realtime.call.incoming resolver above (see
            # handle_webhook) - not a real "scenario name", reused because
            # VoiceCallState predates the kernel resolver and adding a
            # first-class project_id field to it is a bigger change than
            # this needs (same reuse the resolver itself already relies on).
            state = self.call_context.get(call_id) if call_id else None
            query = arguments.get("query", "")
            effective_project_id = project_id or (state.scenario_name if state else None)
            effective_tenant_id = tenant_id or (state.metadata.get("tenant_id") if state else None)
            if not effective_project_id:
                logging.warning("search_knowledge_base: no call context for call_id=%s query=%r", call_id, query)
                return {"status": "error", "message": "No project context for this call"}
            from uuid import UUID as _UUID

            from app.services.rag.search import search_knowledge_base

            try:
                results = await search_knowledge_base(
                    project_id=_UUID(effective_project_id),
                    tenant_id=_UUID(effective_tenant_id) if effective_tenant_id else None,
                    query=query,
                    top_k=5,
                )
            except ValueError as e:
                logging.warning(
                    "search_knowledge_base unavailable: project=%s query=%r error=%s",
                    effective_project_id,
                    query,
                    e,
                )
                return {"status": "unavailable", "message": "Knowledge base not configured for this project"}
            top_score = round(results[0]["similarity"], 3) if results else None
            logging.info(
                "search_knowledge_base: project=%s query=%r -> %d result(s), top_similarity=%s",
                effective_project_id, query, len(results), top_score,
            )
            if not results:
                return {"status": "no_results"}
            return {"status": "ok", "results": results}
        if name == "request_human_operator":
            # 19/08 (collaborator, poi maintainer): versione minima per un test reale
            # prima di generalizzare - un solo numero fisso letto da
            # output_config.transfer.human_operator_number sul progetto,
            # trasferimento vero via xAI realtime "refer" API. Se il
            # progetto non ha un numero configurato, si ricade sul
            # comportamento precedente (il modello si congeda e chiude).
            state = self.call_context.get(call_id) if call_id else None
            if state:
                state.metadata["declined_reason"] = "human_requested"
            logging.info("request_human_operator called [%s]", call_id)
            transferred = await self._try_transfer_to_human(call_id, state)
            if transferred:
                return {"status": "transferring"}
            return {"status": "acknowledged"}
        if name == "current_datetime":
            now = datetime.now(ZoneInfo("Europe/Rome"))
            return {
                "timezone": "Europe/Rome",
                "weekday": now.strftime("%A"),
                "date": now.strftime("%Y-%m-%d"),
                "time": now.strftime("%H:%M"),
                "iso": now.isoformat(),
                "human": now.strftime("%A %d %B %Y %H:%M"),
            }
        if name == "calcom_get_availability":
            start_value, end_value = self.normalize_local_range(arguments["from"], arguments["to"])
            params = {
                "start": self.to_utc_iso(start_value),
                "end": self.to_utc_iso(end_value),
                "timeZone": "Europe/Rome",
            }
            params["eventTypeId"] = self.resolve_event_type_id(arguments.get("event_type_id"), arguments)
            response = await self.calcom_request("GET", "/slots", params=params, api_version="2024-09-04")
            return self.annotate_slot_days(response)
        if name == "calcom_book_appointment":
            phone = (
                arguments.get("phone")
                or arguments.get("caller_phone")
                or arguments.get("caller_id")
                or arguments.get("system__caller_id")
            )
            if not phone and call_id:
                state = self.call_context.get(call_id)
                phone = state.caller_number if state else None
            phone = self.normalize_phone_number(phone)
            if not phone:
                phone = self.extract_phone_from_text(arguments.get("notes"))
            if not phone:
                phone = self.extract_phone_from_text(arguments.get("execution_message"))
            if not phone:
                raise RuntimeError("Missing patient phone number for Cal.com booking")
            start_value = self.normalize_local_datetime(arguments["start"])
            payload = {
                "start": self.to_utc_iso(start_value),
                "eventTypeId": self.resolve_event_type_id(arguments.get("event_type_id"), arguments),
                "attendee": {
                    "name": arguments["name"],
                    "email": arguments.get("email") or "admin@example.test",
                    "phoneNumber": phone,
                    "timeZone": "Europe/Rome",
                    "language": "it",
                },
            }
            notes_parts = []
            if arguments.get("execution_message"):
                notes_parts.append(f"Motivo: {arguments['execution_message']}")
            if arguments.get("notes"):
                notes_parts.append(arguments["notes"])
            if notes_parts:
                payload["metadata"] = {
                    "execution_message": arguments.get("execution_message") or "",
                    "notes": "\n".join(notes_parts),
                }
            return await self.calcom_request("POST", "/bookings", payload=payload, api_version="2024-08-13")
        if name == "calcom_list_bookings":
            params: dict[str, Any] = {
                "status": arguments.get("status") or "upcoming",
                "sortStart": "asc",
                "take": 50,
            }
            if arguments.get("booking_uid"):
                params["bookingUid"] = arguments["booking_uid"]
            if arguments.get("event_type_id"):
                params["eventTypeId"] = self.resolve_event_type_id(arguments.get("event_type_id"), arguments)
            if arguments.get("from"):
                params["afterStart"] = self.to_utc_iso(self.normalize_local_datetime(arguments["from"]))
            if arguments.get("to"):
                params["beforeEnd"] = self.to_utc_iso(self.normalize_local_datetime(arguments["to"]))
            response = await self.calcom_request("GET", "/bookings", params=params, api_version="2026-02-25")
            bookings = response.get("data") or []

            caller_phone = arguments.get("phone") or arguments.get("caller_phone")
            if call_id:
                state = self.call_context.get(call_id)
                caller_phone = caller_phone or (state.caller_number if state else None)
            caller_phone = self.normalize_phone_number(caller_phone)
            target_name = arguments.get("attendee_name")
            reason_hint = arguments.get("reason_hint")

            matched_by = "range"
            if caller_phone:
                phone_matches = [b for b in bookings if self.booking_phone(b) == caller_phone]
                if phone_matches:
                    bookings = phone_matches
                    matched_by = "caller_phone"

            if target_name:
                scored = []
                for booking in bookings:
                    score = self.booking_name_score(booking, target_name)
                    if score >= 0.58:
                        scored.append((score, booking))
                if scored:
                    scored.sort(key=lambda item: item[0], reverse=True)
                    bookings = [booking for _, booking in scored]
                    matched_by = f"{matched_by}+fuzzy_name"

            if reason_hint:
                scored = []
                for booking in bookings:
                    score = self.booking_reason_score(booking, reason_hint)
                    if score >= 0.45:
                        scored.append((score, booking))
                if scored:
                    scored.sort(key=lambda item: item[0], reverse=True)
                    bookings = [booking for _, booking in scored]
                    matched_by = f"{matched_by}+reason_hint"

            response["data"] = bookings
            response["matchedBy"] = matched_by
            response["callerPhone"] = caller_phone
            return response
        if name == "calcom_reschedule_booking":
            start_value = self.normalize_local_datetime(arguments["start"])
            payload = {
                "start": self.to_utc_iso(start_value),
                "reschedulingReason": arguments.get("rescheduling_reason") or "Rescheduled by phone",
            }
            logging.getLogger(__name__).info(
                "Cal.com reschedule payload booking_uid=%s start=%s",
                arguments.get("booking_uid"),
                payload.get("start"),
            )
            return await self.calcom_request(
                "POST",
                f"/bookings/{arguments['booking_uid']}/reschedule",
                payload=payload,
                api_version="2024-08-13",
            )
        if name == "calcom_cancel_booking":
            payload = {
                "cancellationReason": arguments.get("cancellation_reason") or "Cancelled by phone",
            }
            return await self.calcom_request(
                "POST",
                f"/bookings/{arguments['booking_uid']}/cancel",
                payload=payload,
                api_version="2024-08-13",
            )
        calendar = arguments.get("calendar") or "Personal"
        if name == "calendar_list":
            return await self.run_nc_api(
                "calendar",
                "list",
                "--calendar",
                calendar,
                "--from",
                arguments["from"],
                "--to",
                arguments["to"],
            )
        if name == "calendar_create":
            cmd = [
                "calendar",
                "create",
                "--calendar",
                calendar,
                "--summary",
                arguments["summary"],
                "--start",
                arguments["start"],
                "--end",
                arguments["end"],
            ]
            return await self.run_nc_api(*cmd)
        if name == "calendar_edit":
            cmd = ["calendar", "edit", "--calendar", calendar, "--uid", arguments["uid"]]
            if arguments.get("summary"):
                cmd += ["--summary", arguments["summary"]]
            if arguments.get("start"):
                cmd += ["--start", arguments["start"]]
            if arguments.get("end"):
                cmd += ["--end", arguments["end"]]
            return await self.run_nc_api(*cmd)
        if name == "calendar_delete":
            return await self.run_nc_api(
                "calendar",
                "delete",
                "--calendar",
                calendar,
                "--uid",
                arguments["uid"],
            )
        if name == "tasks_list":
            cmd = ["tasks", "list"]
            if arguments.get("calendar"):
                cmd += ["--calendar", arguments["calendar"]]
            return await self.run_nc_api(*cmd)
        if name == "tasks_create":
            cmd = ["tasks", "create", "--title", arguments["title"]]
            if arguments.get("calendar"):
                cmd += ["--calendar", arguments["calendar"]]
            if arguments.get("due"):
                cmd += ["--due", arguments["due"]]
            if arguments.get("priority"):
                cmd += ["--priority", str(arguments["priority"])]
            if arguments.get("description"):
                cmd += ["--description", arguments["description"]]
            return await self.run_nc_api(*cmd)
        if name == "tasks_edit":
            cmd = ["tasks", "edit", "--uid", arguments["uid"]]
            if arguments.get("calendar"):
                cmd += ["--calendar", arguments["calendar"]]
            if arguments.get("title"):
                cmd += ["--title", arguments["title"]]
            if arguments.get("due"):
                cmd += ["--due", arguments["due"]]
            if arguments.get("priority"):
                cmd += ["--priority", str(arguments["priority"])]
            if arguments.get("description"):
                cmd += ["--description", arguments["description"]]
            return await self.run_nc_api(*cmd)
        if name == "tasks_complete":
            cmd = ["tasks", "complete", "--uid", arguments["uid"]]
            if arguments.get("calendar"):
                cmd += ["--calendar", arguments["calendar"]]
            return await self.run_nc_api(*cmd)
        if name == "tasks_delete":
            cmd = ["tasks", "delete", "--uid", arguments["uid"]]
            if arguments.get("calendar"):
                cmd += ["--calendar", arguments["calendar"]]
            return await self.run_nc_api(*cmd)
        if name == "contacts_search":
            cmd = ["contacts", "search", "--query", arguments["query"]]
            if arguments.get("addressbook"):
                cmd += ["--addressbook", arguments["addressbook"]]
            return await self.run_nc_api(*cmd)
        if name == "contacts_create":
            cmd = ["contacts", "create", "--name", arguments["name"]]
            if arguments.get("addressbook"):
                cmd += ["--addressbook", arguments["addressbook"]]
            for key, flag in (
                ("email", "--email"),
                ("phone", "--phone"),
                ("organization", "--organization"),
                ("title", "--title"),
                ("note", "--note"),
            ):
                if arguments.get(key):
                    cmd += [flag, arguments[key]]
            return await self.run_nc_api(*cmd)
        if name == "contacts_edit":
            cmd = ["contacts", "edit", "--uid", arguments["uid"]]
            if arguments.get("addressbook"):
                cmd += ["--addressbook", arguments["addressbook"]]
            for key, flag in (
                ("name", "--name"),
                ("email", "--email"),
                ("phone", "--phone"),
                ("organization", "--organization"),
                ("title", "--title"),
                ("note", "--note"),
            ):
                if arguments.get(key):
                    cmd += [flag, arguments[key]]
            return await self.run_nc_api(*cmd)
        if name == "contacts_delete":
            cmd = ["contacts", "delete", "--uid", arguments["uid"]]
            if arguments.get("addressbook"):
                cmd += ["--addressbook", arguments["addressbook"]]
            return await self.run_nc_api(*cmd)
        if name == "files_list":
            return await self.run_nc_api("files", "list", "--path", arguments.get("path") or "/Shared")
        if name == "files_search":
            return await self.run_nc_api("files", "search", "--query", arguments["query"])
        if name == "files_get":
            return await self.run_nc_api("files", "get", "--path", arguments["path"])
        raise ValueError(f"Unknown tool: {name}")

    async def _try_transfer_to_human(self, call_id: str | None, state: Any) -> bool:
        """
        Trasferimento SIP reale verso un numero fisso, letto da
        output_config.transfer.human_operator_number sul progetto (vedi
        VoiceCallState.scenario_name = project_id). Versione minima
        (19/08, maintainer: "costruisco solo il tool minimo... tu fai una
        chiamata vera") - un solo numero, nessuna scelta per tipo di
        richiesta ancora. Usa la refer API di xAI realtime, verificata
        live con un call_id finto (400 "invalid call_id", non 404/401 -
        endpoint/auth/shape corretti).
        Ritorna True se il trasferimento e' stato tentato con successo
        (risposta 2xx da xAI), False altrimenti (nessun numero configurato
        o errore - in quel caso il modello si congeda e chiude da solo,
        comportamento precedente).
        """
        if not call_id or not state or not state.scenario_name:
            logging.warning("Transfer: missing call_id/state/scenario_name [%s]", call_id)
            return False
        tenant_id = state.metadata.get("tenant_id")
        try:
            db = get_database()
            # projects ha FORCE RLS (tenant_isolation_select) - una query
            # diretta senza contesto restituisce silenziosamente 0 righe,
            # non un errore (bug reale trovato qui: il primo tentativo di
            # trasferimento non falliva con un'eccezione, spariva e basta -
            # nessun log, "row" era semplicemente None). tenant_id e' gia'
            # noto (state.metadata, popolato all'accettazione della
            # chiamata), stesso pattern usato per la verifica via
            # TestClient altrove nel progetto.
            async with db.transaction():
                if tenant_id:
                    await db.execute(
                        "SELECT set_config('app.tenant_id', :tid, true)", {"tid": str(tenant_id)}
                    )
                row = await db.fetch_one(
                    "SELECT output_config FROM projects WHERE id = :id",
                    {"id": state.scenario_name},
                )
        except Exception:
            logging.exception("Transfer: failed to load project %s", state.scenario_name)
            return False
        if not row:
            logging.warning(
                "Transfer: project %s not found (RLS or missing row, tenant_id=%s)",
                state.scenario_name, tenant_id,
            )
            return False
        output_config = row["output_config"]
        if isinstance(output_config, str):
            try:
                output_config = json.loads(output_config)
            except json.JSONDecodeError:
                output_config = {}
        transfer_cfg = (output_config or {}).get("transfer") or {}
        # 19/08 (maintainer, dopo il primo test fallito con tel:+numero -> 502
        # grezzo di Cloudflare, non un errore JSON pulito come col call_id
        # finto): "non ho mai acquistato un numero fisico su x.ai" - ipotesi
        # e' che target_uri "tel:" richieda a x.ai un'uscita PSTN che non
        # abbiamo, mentre un target_uri "sip:" resta dentro la loro
        # infrastruttura di segnalazione. target_uri esplicito (nuovo campo)
        # ha priorita' e permette di testare un URI SIP diretto; il vecchio
        # human_operator_number resta come fallback retrocompatibile per un
        # numero telefonico semplice.
        target_uri = transfer_cfg.get("target_uri")
        if not target_uri:
            number = transfer_cfg.get("human_operator_number")
            target_uri = f"tel:{number}" if number else None
        if not target_uri:
            logging.info("Transfer: no target_uri/human_operator_number configured for project %s", state.scenario_name)
            return False
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.xai_base_url}/realtime/calls/{call_id}/refer",
                    headers={"Authorization": f"Bearer {state.api_key}"},
                    json={"target_uri": target_uri},
                )
            if response.status_code // 100 != 2:
                logging.error(
                    "Transfer failed [%s] -> %s: HTTP %s %s",
                    call_id, target_uri, response.status_code, response.text,
                )
                return False
            logging.info("Transfer accepted [%s] -> %s: %s", call_id, target_uri, response.text)
            return True
        except Exception:
            logging.exception("Transfer request failed [%s] -> %s", call_id, target_uri)
            return False

    async def _create_call_record(
        self, xai_call_id: str, caller_number: str, resolved: dict[str, Any],
    ) -> "uuid.UUID":
        """
        Ascolta's own `calls` row for this xAI call - see the 18/08 fix note
        above its call site. Mirrors app/routers/webhook.py's
        handle_call_started() INSERT for the OpenAI path: Ascolta's own
        internal id (not xAI's call_id string, which goes in the new
        xai_call_id column - same pattern as vapi_call_id/twilio_call_sid).
        No RLS bypass needed here despite running outside a request
        context: `calls` has no RLS policy at all (deliberately, see
        FEATURE_MATRIX.md - the inbound path historically never populated
        tenant_id; this fix populates it, but the RLS decision for `calls`
        itself is unchanged/out of scope here).
        """
        import uuid

        internal_call_id = uuid.uuid4()
        db = get_database()
        await db.execute(
            """
            INSERT INTO calls (
                id, phone_number, status, xai_call_id, started_at,
                project_id, tenant_id, agent_version_id, voice_engine, direction, session_model
            ) VALUES (
                :id, :phone_number, :status, :xai_call_id, :started_at,
                :project_id, :tenant_id, :agent_version_id, 'xai_sip_direct', 'inbound', :session_model
            )
            """,
            {
                "id": str(internal_call_id),
                "phone_number": caller_number or "unknown",
                "status": CallStatus.IN_PROGRESS.value,
                "xai_call_id": xai_call_id,
                "started_at": datetime.now(timezone.utc),
                "project_id": str(resolved["project_id"]),
                "tenant_id": str(resolved["tenant_id"]),
                "agent_version_id": str(resolved["agent_version_id"]) if resolved.get("agent_version_id") else None,
                "session_model": str(self.model or "grok-voice-latest"),
            },
        )
        return internal_call_id

    async def _persist_transcript(
        self,
        internal_call_id: str,
        role: str,
        text: str,
        row_id: int | None = None,
    ) -> int | None:
        """Same schema/pattern as app/services/realtime_session.py's _persist_transcript (OpenAI path)."""
        if not text:
            return row_id
        db = get_database()
        try:
            if row_id is not None:
                updated = await db.fetch_one(
                    """
                    UPDATE transcripts
                    SET content = :content, timestamp = :timestamp
                    WHERE id = :id
                    RETURNING id
                    """,
                    {
                        "id": row_id,
                        "content": text,
                        "timestamp": datetime.now(timezone.utc),
                    },
                )
                if updated:
                    return int(updated["id"])
            previous = await db.fetch_one(
                """
                SELECT id, content
                FROM transcripts
                WHERE call_id = :call_id AND role = :role
                ORDER BY timestamp DESC
                LIMIT 1
                """,
                {
                    "call_id": internal_call_id,
                    "role": role,
                },
            )
            # xAI inbound can emit progressively longer "completed"
            # transcripts for the same utterance. Keep only the latest
            # extension instead of storing every prefix as a new turn.
            if previous:
                previous_text = (previous["content"] or "").strip()
                current_text = text.strip()
                if current_text == previous_text:
                    return int(previous["id"])
                if previous_text and current_text.startswith(previous_text):
                    updated = await db.fetch_one(
                        """
                        UPDATE transcripts
                        SET content = :content, timestamp = :timestamp
                        WHERE id = :id
                        RETURNING id
                        """,
                        {
                            "id": previous["id"],
                            "content": text,
                            "timestamp": datetime.now(timezone.utc),
                        },
                    )
                    return int(updated["id"]) if updated else int(previous["id"])
            created = await db.fetch_one(
                """
                INSERT INTO transcripts (call_id, role, content, timestamp)
                VALUES (:call_id, :role, :content, :timestamp)
                RETURNING id
                """,
                {
                    "call_id": internal_call_id,
                    "role": role,
                    "content": text,
                    "timestamp": datetime.now(timezone.utc),
                },
            )
            return int(created["id"]) if created else None
        except Exception:
            logging.exception("Failed to persist transcript for call %s", internal_call_id)
            return row_id

    def _merge_user_transcript_fragments(self, fragments: list[str]) -> str:
        merged = ""
        for fragment in fragments:
            cleaned = (fragment or "").strip()
            if not cleaned:
                continue
            if not merged:
                merged = cleaned
                continue
            if cleaned.startswith(merged):
                merged = cleaned
                continue
            if merged.startswith(cleaned):
                continue
            overlap = self._find_fragment_overlap(merged, cleaned)
            if overlap > 0:
                merged = f"{merged}{cleaned[overlap:]}"
            else:
                merged = f"{merged} {cleaned}"
        return merged.strip()

    def _find_fragment_overlap(self, previous: str, current: str) -> int:
        prev = previous.strip()
        curr = current.strip()
        max_overlap = min(len(prev), len(curr))
        for size in range(max_overlap, 4, -1):
            if prev[-size:].lower() == curr[:size].lower():
                return size
        return 0

    async def _finalize_call_record(self, state: "VoiceCallState") -> None:
        """
        Marks the call completed and triggers post-processing (JSON
        extraction, PDF/email if enabled, CRM sync) - same
        call_manager.CallManager the OpenAI path uses, reused as-is rather
        than reimplemented here.

        Idempotency guard (20/08): now called from two places - the
        'call.ended'/'realtime.call.ended' webhook (the original, only
        path) and run_call()'s own finally block (added because when
        xAI's realtime WebSocket just drops - "no close frame received or
        sent", no webhook ever follows - neither ran, and the call sat
        'in_progress' with no ended_at until session_cleanup.py swept it
        up ~20 minutes later and mislabeled it 'declined'; real incident,
        see calls id=414a2c41... on 19/08, 24 real transcript turns but
        never finalized). If both end up firing for the same call, this
        must not run _handle_interview_complete (PDF/email/CRM) twice.
        """
        internal_call_id = state.metadata.get("internal_call_id")
        if not internal_call_id:
            return
        if state.metadata.get("_finalized"):
            return
        state.metadata["_finalized"] = True

        db = get_database()

        # 20/08 (maintainer): "Rifiutata" per xai_sip_direct deve scattare
        # solo se il chiamante riattacca senza dire nulla, o chiede
        # esplicitamente un operatore umano - non e' piu' un mislabel del
        # cleanup (vedi session_cleanup.py, corretto separatamente).
        # Seconda correzione, stesso giorno: "se uno ha chiesto
        # l'operatore umano forse bisognerebbe dire qualcosa tipo
        # 'Inoltro'" - giusto, non e' lo stesso esito di un riattacco
        # silenzioso. Status dedicato ESCALATED (db_migrations/versions/
        # a3905808ab22_*) per quel caso; DECLINED resta solo "nessun
        # coinvolgimento": se non e' mai stato persistito un turno
        # "user", il chiamante non ha mai parlato.
        final_status = CallStatus.COMPLETED.value
        if state.metadata.get("declined_reason") == "human_requested":
            final_status = CallStatus.ESCALATED.value
        else:
            try:
                user_turns = await db.fetch_val(
                    "SELECT COUNT(*) FROM transcripts WHERE call_id = :id AND role = 'user'",
                    {"id": internal_call_id},
                )
                if not user_turns:
                    final_status = CallStatus.DECLINED.value
            except Exception:
                logging.exception("Failed to check transcript activity for %s", internal_call_id)

        from app.services.pricing import (
            cost_usd_from_ticks,
            estimate_xai_call_cost_usd,
            load_xai_voice_pricing_per_minute,
        )

        billable_audio_seconds = state.metadata.get("billable_audio_seconds")
        actual_cost_ticks = state.metadata.get("cost_in_usd_ticks")
        session_model = state.metadata.get("session_model") or state.model
        cost_usd = cost_usd_from_ticks(actual_cost_ticks)
        cost_source = "exact" if cost_usd is not None else None
        if cost_usd is None:
            pricing_per_minute = await load_xai_voice_pricing_per_minute(db)
            cost_usd = estimate_xai_call_cost_usd(
                billable_audio_seconds,
                model_name=session_model,
                pricing_per_minute=pricing_per_minute,
            )
            if cost_usd is not None:
                cost_source = "est_billable"

        try:
            await db.execute(
                """
                UPDATE calls SET ended_at = COALESCE(ended_at, :ended_at), status = :status,
                       billable_audio_seconds = :billable_audio_seconds,
                       session_model = COALESCE(session_model, :session_model),
                       cost_in_usd_ticks = :cost_in_usd_ticks,
                       cost_source = :cost_source,
                       cost_usd = :cost_usd
                WHERE id = :id
                """,
                {
                    "id": internal_call_id,
                    "ended_at": datetime.now(timezone.utc),
                    "status": final_status,
                    "billable_audio_seconds": billable_audio_seconds,
                    "session_model": session_model,
                    "cost_in_usd_ticks": actual_cost_ticks,
                    "cost_source": cost_source,
                    "cost_usd": cost_usd,
                },
            )
        except Exception:
            logging.exception("Failed to finalize call record for %s", internal_call_id)
            return

        from app.services.call_manager import CallManager
        from uuid import UUID as _UUID

        # Same pattern as app/routers/webhook.py (which also instantiates
        # its own CallManager() rather than importing a shared singleton -
        # there isn't one).
        await CallManager()._handle_interview_complete(_UUID(internal_call_id))

    async def handle_webhook(self, payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
        text = payload.decode()
        if self.webhook_secret:
            # Crypto-only operation (HMAC/signature check), doesn't call
            # xAI over the network - a throwaway client is fine here, no
            # tenant context exists yet at this point anyway.
            verify_client = AsyncOpenAI(api_key="signature-verification-only", base_url=self.xai_base_url)
            verify_client.webhooks.verify_signature(text, headers, secret=self.webhook_secret)
            event = verify_client.webhooks.unwrap(text, headers, secret=self.webhook_secret)
            event_type = event.type
            event_data = event.data
        else:
            body = json.loads(text)
            event_type = body.get("type")
            event_data = body.get("data", {})

        logging.info("Webhook received: %s", event_type)

        if event_type == "realtime.call.incoming":
            call_id = getattr(event_data, "call_id", None) or event_data.get("call_id")
            if not call_id:
                raise ValueError("Missing call_id")
            sip_headers = getattr(event_data, "sip_headers", None) or event_data.get("sip_headers", [])
            caller_number = self.extract_phone_from_sip_headers(sip_headers)
            dialed_number = self.extract_header_value(sip_headers, {"to"})

            # Fase 2 kernel resolver, same function already proven on the
            # OpenAI SIP and LiveKit paths - see app/routers/webhook.py and
            # runtime_workers/livekit_agent.py. No static config fallback
            # here: without a resolved tenant there is no api_key to answer
            # with at all (see __init__), so an unresolved number can only
            # be declined, not silently answered with someone else's key.
            resolved = await resolve_inbound(dialed_number) if dialed_number else None
            if not resolved:
                logging.warning(
                    "xAI SIP diretto: nessun inbound_endpoint per '%s' - chiamata rifiutata (nessuna chiave globale di fallback).",
                    dialed_number,
                )
                return {"status": "declined", "reason": "no_endpoint", "call_id": call_id}

            api_key = await resolve_provider_api_key(resolved["tenant_id"], "xai")
            if not api_key:
                logging.warning(
                    "xAI SIP diretto: nessuna credenziale voice/xai per tenant=%s - chiamata rifiutata.",
                    resolved["tenant_id"],
                )
                return {"status": "declined", "reason": "no_credentials", "call_id": call_id}

            instructions = resolved["prompt_a"]
            first_message = resolved.get("consent_message") or "Salve, come posso aiutarla?"
            voice = resolved.get("voice_name") or self.voice
            language = resolved.get("language") or self.response_language or "it"

            # Ascolta's own call record - was entirely missing before 18/08
            # (maintainer: "ma la trascrizione delle telefonate e gli analytics
            # sono a posto?" - they weren't, for this path: this worker only
            # ever ran the live audio session, no `calls` row, no
            # transcript, no post-processing trigger - a real call left no
            # trace in the DB at all). Mirrors app/routers/webhook.py's
            # handle_call_started() for the OpenAI path.
            internal_call_id = await self._create_call_record(
                xai_call_id=call_id,
                caller_number=caller_number,
                resolved=resolved,
            )

            self.call_context.put(
                VoiceCallState(
                    call_id=call_id,
                    scenario_name=str(resolved["project_id"]),
                    caller_number=caller_number,
                    instructions=instructions,
                    first_message=first_message,
                    response_language=language,
                    provider="xai",
                    model=str(self.model or "grok-voice-fast-1.0"),
                    voice=str(voice),
                    api_key=api_key,
                    metadata={"tenant_id": str(resolved["tenant_id"]), "internal_call_id": str(internal_call_id)},
                )
            )
            logging.info(
                "Inbound xAI risolto: '%s' -> tenant=%s project=%s agent_version=%s caller=%s",
                dialed_number, resolved["tenant_id"], resolved["project_id"], resolved["agent_version_id"], caller_number or "unknown",
            )
            await self.start_call_session(call_id)
            return {"status": "accepted", "call_id": call_id}

        if event_type in {"realtime.call.ended", "call.ended"}:
            call_id = getattr(event_data, "call_id", None) or event_data.get("call_id")
            if call_id and call_id in self.active_calls:
                task = self.active_calls.pop(call_id)
                task.cancel()
            state = self.call_context.get(call_id) if call_id else None
            if call_id:
                self.call_context.pop(call_id, None)
            if state:
                await self._finalize_call_record(state)
            return {"status": "ended", "call_id": call_id}

        return {"status": "ignored", "event_type": event_type}

    async def start_call_session(self, call_id: str) -> None:
        if call_id in self.active_calls:
            logging.info("Call %s already active", call_id)
            return

        task = asyncio.create_task(self.run_call(call_id), name=f"ascolta-call-{call_id}")
        task.add_done_callback(lambda t, cid=call_id: self._finalize_call_task(cid, t))
        self.active_calls[call_id] = task

    def _finalize_call_task(self, call_id: str, task: asyncio.Task[Any]) -> None:
        self.active_calls.pop(call_id, None)
        try:
            exc = task.exception()
        except asyncio.CancelledError:
            logging.info("Call task cancelled [%s]", call_id)
            return
        except Exception:
            logging.exception("Unable to inspect call task [%s]", call_id)
            return

        if exc is not None:
            logging.exception("Call task failed [%s]", call_id, exc_info=exc)

    async def run_call(self, call_id: str) -> None:
        logging.info("Starting control plane for call %s", call_id)
        call_state = self.call_context.get(call_id)
        if not call_state:
            raise RuntimeError(f"Call state missing for realtime session: {call_id}")
        instructions = call_state.instructions
        first_message = call_state.first_message
        query = urlencode({"call_id": call_id})
        ws_url = f"wss://api.x.ai/v1/realtime?{query}"
        if not call_state.api_key:
            raise RuntimeError(f"Call {call_id} has no api_key in its resolved state - this should be unreachable (handle_webhook declines before reaching here)")
        headers = {"Authorization": f"Bearer {call_state.api_key}"}

        # try/finally (20/08): before this, finalization only happened
        # via the 'call.ended' webhook handler - if the connection to xAI
        # just dies (ConnectionClosedError, network drop, etc.) instead
        # of a clean hangup that produces that webhook, nothing ever
        # finalized the call. It would sit 'in_progress' until
        # session_cleanup.py's 20-minute stale-session sweep force-closed
        # it as 'declined' - a misleading label for what was really an
        # abandoned/uncaught disconnect, not a consent refusal. Now the
        # call gets finalized (status, duration, post-processing trigger)
        # the moment the session loop ends, for any reason.
        try:
            async with websockets.connect(ws_url, additional_headers=headers) as conn:
                await conn.send(
                    json.dumps(
                        {
                            "type": "session.update",
                            "session": build_xai_session_update(
                                voice=call_state.voice,
                                language=call_state.response_language,
                                instructions=instructions,
                                tools=self.tools,
                            ),
                        },
                        ensure_ascii=True,
                    )
                )
                await conn.send(
                    json.dumps(
                        {
                            "type": "response.create",
                            "response": {
                                "instructions": (
                                    "Pronuncia subito e integralmente il seguente messaggio iniziale, "
                                    "senza riassumerlo, senza cambiare lingua o ordine, e senza aggiungere altro prima: "
                                    f"{first_message}"
                                ),
                            },
                        },
                        ensure_ascii=True,
                    )
                )

                async for raw_event in conn:
                    event = json.loads(raw_event)
                    etype = event.get("type", "")
                    if etype == "session.created":
                        logging.info("Session created for call %s", call_id)
                    elif etype in {
                        "conversation.item.input_audio_transcription.updated",
                        "conversation.item.input_audio_transcription.completed",
                    }:
                        transcript_text = event.get("transcript", "")
                        logging.info("User transcript [%s][%s]: %s", call_id, etype, transcript_text)
                        internal_call_id = call_state.metadata.get("internal_call_id")
                        if internal_call_id:
                            item_id = (
                                event.get("item_id")
                                or event.get("id")
                                or (event.get("item") or {}).get("id")
                            )
                            user_items = call_state.metadata.setdefault("_current_user_item_ids", [])
                            user_texts = call_state.metadata.setdefault("_current_user_item_texts", {})
                            current_user_row_id = call_state.metadata.get("_current_user_row_id")
                            if item_id and item_id not in user_items:
                                user_items.append(item_id)
                            if item_id:
                                user_texts[item_id] = transcript_text
                                merged_user_text = self._merge_user_transcript_fragments(
                                    [user_texts[item] for item in user_items if user_texts.get(item)]
                                )
                            else:
                                merged_user_text = transcript_text
                            persisted_row_id = await self._persist_transcript(
                                internal_call_id,
                                "user",
                                merged_user_text,
                                row_id=current_user_row_id,
                            )
                            if persisted_row_id is not None:
                                call_state.metadata["_current_user_row_id"] = persisted_row_id
                    elif etype == "response.output_audio_transcript.done":
                        transcript_text = event.get("transcript", "")
                        logging.info("Assistant transcript [%s]: %s", call_id, transcript_text)
                        internal_call_id = call_state.metadata.get("internal_call_id")
                        if internal_call_id:
                            await self._persist_transcript(internal_call_id, "assistant", transcript_text)
                            call_state.metadata.pop("_current_user_row_id", None)
                            call_state.metadata.pop("_current_user_item_ids", None)
                            call_state.metadata.pop("_current_user_item_texts", None)
                    elif etype == "response.function_call_arguments.done":
                        await self.handle_function_call(conn, SimpleNamespace(**event), call_id)
                    elif etype == "error":
                        logging.error("Realtime error [%s]: %s", call_id, event)
                    elif etype == "response.done":
                        status = (event.get("response") or {}).get("status")
                        logging.info("Response done [%s]: %s", call_id, status)
                        response_obj = event.get("response") or {}
                        response_id = response_obj.get("id") or event.get("response_id")
                        # Seguiamo solo i campi documentati per cost
                        # tracking (`usage.cost_in_usd_ticks`) e
                        # registriamo il payload rilevante di
                        # response.done per fissare la shape reale del
                        # flusso SIP/realtime voice in ambiente di sviluppo.
                        usage = event.get("usage") or response_obj.get("usage") or {}
                        logging.info(
                            "Response done payload [%s]: event_keys=%s response_keys=%s usage=%s response_usage=%s",
                            call_id,
                            sorted(event.keys()),
                            sorted(response_obj.keys()),
                            event.get("usage"),
                            response_obj.get("usage"),
                        )
                        billable = usage.get("billable_audio_seconds")
                        if billable:
                            response_billable = call_state.metadata.setdefault("_response_billable_audio_seconds", {})
                            if response_id:
                                response_billable[response_id] = max(
                                    response_billable.get(response_id, 0),
                                    billable,
                                )
                                call_state.metadata["billable_audio_seconds"] = sum(response_billable.values())
                            else:
                                call_state.metadata["billable_audio_seconds"] = max(
                                    call_state.metadata.get("billable_audio_seconds", 0),
                                    billable,
                                )
                        # xAI cost tracking: exact billed amount per
                        # call, in integer USD ticks. Stesso discorso
                        # del campo sopra: se il provider lo manda come
                        # valore cumulativo, sommare gonfia tutto.
                        # Conserviamo quindi il massimo osservato.
                        cost_ticks = usage.get("cost_in_usd_ticks")
                        if cost_ticks is not None:
                            call_state.metadata["cost_in_usd_ticks"] = max(
                                call_state.metadata.get("cost_in_usd_ticks", 0),
                                cost_ticks,
                            )
                            logging.info(
                                "Response done [%s]: exact usage found billable=%s cost_in_usd_ticks=%s",
                                call_id,
                                billable,
                                cost_ticks,
                            )
                        else:
                            logging.info(
                                "Response done [%s]: no exact cost_in_usd_ticks billable=%s usage_keys=%s",
                                call_id,
                                billable,
                                sorted(usage.keys()),
                            )
        finally:
            await self._finalize_call_record(call_state)

    async def handle_function_call(self, conn: Any, event: Any, call_id: str | None = None) -> None:
        name = event.name
        raw_arguments = event.arguments or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            logging.exception("Malformed function call arguments for %s: %r", name, raw_arguments)
            result = {
                "status": "error",
                "message": "Malformed function call arguments",
                "tool": name,
            }
            await conn.send(
                json.dumps(
                    {
                        "type": "conversation.item.create",
                        "item": {
                            "type": "function_call_output",
                            "call_id": event.call_id,
                            "output": json.dumps(result, ensure_ascii=True),
                        },
                    },
                    ensure_ascii=True,
                )
            )
            await conn.send(
                json.dumps(
                    {
                        "type": "response.create",
                        "response": {
                            "instructions": (
                                "Il tool call precedente aveva argomenti non validi. "
                                "Ripeti l'operazione con argomenti JSON completi e corretti, "
                                "senza cambiare il senso della richiesta dell'utente."
                            )
                        },
                    },
                    ensure_ascii=True,
                )
            )
            return
        logging.info("Tool call: %s %s", name, arguments)
        try:
            result = await self.call_tool(name, arguments, call_id=call_id)
        except Exception as exc:
            result = {"status": "error", "message": str(exc)}
            logging.exception("Tool call failed: %s", name)

        await conn.send(
            json.dumps(
                {
                    "type": "conversation.item.create",
                    "item": {
                        "type": "function_call_output",
                        "call_id": event.call_id,
                        "output": json.dumps(result, ensure_ascii=True),
                    },
                },
                ensure_ascii=True,
            )
        )
        await conn.send(json.dumps({"type": "response.create"}, ensure_ascii=True))


class RequestHandler(BaseHTTPRequestHandler):
    server_version = "LegacyPrototypeRealtime/0.1"

    def _is_authorized_tool_request(self) -> bool:
        expected = getattr(self.server.controller, "elevenlabs_tool_secret", None)  # type: ignore[attr-defined]
        if not expected:
            return False
        provided = self.headers.get("X-Tool-Secret", "").strip()
        return bool(provided) and provided == expected

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json(200, {"status": "ok"})
            return
        if self.path == "/api/elevenlabs/manifest":
            self._send_json(
                200,
                {
                    "status": "ok",
                    "toolsBaseUrl": "/api/elevenlabs/tools/{tool_name}",
                    "authHeader": "X-Tool-Secret",
                    "supportedTools": [
                        "calcom_get_availability",
                        "calcom_book_appointment",
                        "calcom_list_bookings",
                        "calcom_reschedule_booking",
                        "calcom_cancel_booking",
                        "calendar_list",
                        "calendar_create",
                        "calendar_edit",
                        "calendar_delete",
                        "tasks_list",
                        "tasks_create",
                        "tasks_edit",
                        "tasks_complete",
                        "tasks_delete",
                        "contacts_search",
                        "contacts_create",
                        "contacts_edit",
                        "contacts_delete",
                        "files_list",
                        "files_search",
                        "files_get",
                    ],
                },
            )
            return
        self._send_json(404, {"status": "not_found"})

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = self.rfile.read(length)
        if self.path == "/api/webhook/call":
            headers = {k: v for k, v in self.headers.items()}
            future = asyncio.run_coroutine_threadsafe(
                self.server.controller.handle_webhook(payload, headers),  # type: ignore[attr-defined]
                self.server.loop,  # type: ignore[attr-defined]
            )
            try:
                result = future.result(timeout=15)
                self._send_json(200, result)
            except Exception as exc:
                logging.exception("Webhook handling failed")
                self._send_json(500, {"status": "error", "message": str(exc)})
            return

        if self.path.startswith("/api/elevenlabs/tools/"):
            if not self._is_authorized_tool_request():
                self._send_json(403, {"status": "forbidden"})
                return
            tool_name = self.path.rsplit("/", 1)[-1]
            try:
                body = json.loads(payload.decode() or "{}")
            except json.JSONDecodeError:
                self._send_json(400, {"status": "error", "message": "invalid_json"})
                return
            if not isinstance(body, dict):
                body = {}
            arguments = body.get("arguments")
            if arguments is None:
                arguments = body
            if not isinstance(arguments, dict):
                arguments = {}
            if isinstance(body, dict):
                for key in ("caller_phone", "caller_id", "system__caller_id", "phone"):
                    if key in body and key not in arguments:
                        arguments[key] = body.get(key)
                metadata = body.get("metadata")
                if isinstance(metadata, dict):
                    for key in ("caller_phone", "caller_id", "system__caller_id", "phone"):
                        if key in metadata and key not in arguments:
                            arguments[key] = metadata.get(key)
            call_id = body.get("call_id")
            future = asyncio.run_coroutine_threadsafe(
                self.server.controller.call_tool(tool_name, arguments, call_id=call_id),  # type: ignore[attr-defined]
                self.server.loop,  # type: ignore[attr-defined]
            )
            try:
                result = future.result(timeout=30)
                self._send_json(200, {"status": "ok", "tool": tool_name, "result": result})
            except Exception as exc:
                logging.exception("ElevenLabs tool failed: %s", tool_name)
                self._send_json(500, {"status": "error", "tool": tool_name, "message": str(exc)})
            return

        if self.path == "/api/elevenlabs/post-call":
            try:
                body = json.loads(payload.decode() or "{}")
            except json.JSONDecodeError:
                self._send_json(400, {"status": "error", "message": "invalid_json"})
                return
            result = self.server.controller.store_elevenlabs_transcript(body)  # type: ignore[attr-defined]
            self._send_json(200, result)
            return

        self._send_json(404, {"status": "not_found"})

    def log_message(self, format: str, *args: Any) -> None:
        logging.info("%s - %s", self.address_string(), format % args)


def main() -> None:
    load_env_file(DEFAULT_ENV)
    load_env_file(ROOT / ".env")
    setup_logging()

    cfg = load_config()
    runtime_cfg = cfg.get("runtime") if isinstance(cfg.get("runtime"), dict) else {}
    host = runtime_cfg.get("realtime_host") or "127.0.0.1"
    port = int(runtime_cfg.get("realtime_port") or 3381)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    controller = LegacyController()

    server = ThreadingHTTPServer((host, port), RequestHandler)
    server.controller = controller  # type: ignore[attr-defined]
    server.loop = loop  # type: ignore[attr-defined]

    def shutdown(*_: Any) -> None:
        logging.info("Shutdown requested")
        import threading

        threading.Thread(target=server.shutdown, daemon=True).start()
        loop.call_soon_threadsafe(loop.stop)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    async def runner() -> None:
        await asyncio.Event().wait()

    loop.create_task(runner())

    import threading

    threading.Thread(target=loop.run_forever, daemon=True).start()
    logging.info("Ascolta realtime service listening on http://%s:%s", host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
