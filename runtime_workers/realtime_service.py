#!/usr/bin/env python3
"""
Ported from earlier-prototype via ascolta-salvage-2026-07-24, adapted for ascolta.
Self-contained: no import/runtime dependency on the earlier-prototype or ascolta directories.
Status: starting point for Milestone 5 (see README) - not yet wired into
app.services.voice.factory / CallManager. Config/env resolution here is still
file-based (ascolta-stack-config.json); the DB-driven credential/config
resolution (CredentialsManager.get_credentials_with_fallback) will replace it
when the concrete voice engine classes are implemented.
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

from app.integrations.common.config import active_services, load_config, load_realtime_config, load_scenario_config, resolve_scenario
from app.integrations.common.tools import build_tools
from app.integrations.voice_core.scenario import resolve_voice_bundle
from app.integrations.voice_core.state import VoiceCallState, VoiceStateStore
from app.integrations.voice_core.xai_session import build_xai_session_update

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
        if self.provider in {"xai", "grok"}:
            api_key = os.environ.get("XAI_API_KEY", "").strip() or os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("XAI_API_KEY missing")
            base_url = str(realtime_cfg.get("base_url") or "https://api.x.ai/v1").rstrip("/")
            websocket_base_url = str(realtime_cfg.get("websocket_base_url") or "wss://api.x.ai/v1/realtime").rstrip("/")
            self.client = AsyncOpenAI(api_key=api_key, base_url=base_url, websocket_base_url=websocket_base_url)
        else:
            api_key = os.environ.get("OPENAI_API_KEY", "").strip()
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY missing")
            self.client = AsyncOpenAI(api_key=api_key)
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
        for header in sip_headers or []:
            if isinstance(header, dict):
                name = header.get("name", "") or ""
                value = header.get("value", "") or ""
            else:
                name = getattr(header, "name", "") or ""
                value = getattr(header, "value", "") or ""
            if name.lower() not in {"from", "p-asserted-identity", "remote-party-id"}:
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

    async def call_tool(self, name: str, arguments: dict[str, Any], call_id: str | None = None) -> dict[str, Any]:
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

    async def handle_webhook(self, payload: bytes, headers: dict[str, str]) -> dict[str, Any]:
        text = payload.decode()
        if self.webhook_secret:
            self.client.webhooks.verify_signature(text, headers, secret=self.webhook_secret)
            event = self.client.webhooks.unwrap(text, headers, secret=self.webhook_secret)
            event_type = event.type
            event_data = event.data
        else:
            body = json.loads(text)
            event_type = body.get("type")
            event_data = body.get("data", {})

        logging.info("Webhook received: %s", event_type)

        if event_type == "realtime.call.incoming":
            config = load_config()
            services = active_services(config)
            if "realtime" not in services and "openai" not in services:
                return {"status": "ignored", "reason": "realtime_disabled"}
            call_id = getattr(event_data, "call_id", None) or event_data.get("call_id")
            if not call_id:
                raise ValueError("Missing call_id")
            sip_headers = getattr(event_data, "sip_headers", None) or event_data.get("sip_headers", [])
            caller_number = self.extract_phone_from_sip_headers(sip_headers)
            variant, instructions, first_message = self.prompt_bundle()
            self.call_context.put(
                VoiceCallState(
                    call_id=call_id,
                    scenario_name=variant,
                    caller_number=caller_number,
                    instructions=instructions,
                    first_message=first_message,
                    response_language=self.response_language or "it",
                    provider=self.provider,
                    model=str(self.model or ""),
                    voice=str(self.voice or ""),
                )
            )
            logging.info("Incoming call %s prompt_variant=%s caller_number=%s", call_id, variant, caller_number or "unknown")
            await self.start_call_session(call_id)
            return {"status": "accepted", "call_id": call_id}

        if event_type in {"realtime.call.ended", "call.ended"}:
            call_id = getattr(event_data, "call_id", None) or event_data.get("call_id")
            if call_id and call_id in self.active_calls:
                task = self.active_calls.pop(call_id)
                task.cancel()
            if call_id:
                self.call_context.pop(call_id, None)
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
        headers = {"Authorization": f"Bearer {self.client.api_key}"}

        async with websockets.connect(ws_url, additional_headers=headers) as conn:
            await conn.send(
                json.dumps(
                    {
                        "type": "session.update",
                        "session": build_xai_session_update(
                            voice=self.voice,
                            language=self.response_language,
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
                elif etype == "conversation.item.input_audio_transcription.completed":
                    logging.info("User transcript [%s]: %s", call_id, event.get("transcript", ""))
                elif etype == "response.output_audio_transcript.done":
                    logging.info("Assistant transcript [%s]: %s", call_id, event.get("transcript", ""))
                elif etype == "response.function_call_arguments.done":
                    await self.handle_function_call(conn, SimpleNamespace(**event), call_id)
                elif etype == "error":
                    logging.error("Realtime error [%s]: %s", call_id, event)
                elif etype == "response.done":
                    status = (event.get("response") or {}).get("status")
                    logging.info("Response done [%s]: %s", call_id, status)

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
