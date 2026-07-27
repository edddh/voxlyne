from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.integrations.common.config import load_config, load_scenario_config, resolve_scenario
from .prompting import resolve_prompt_template


@dataclass(frozen=True)
class VoiceScenarioBundle:
    scenario_name: str
    prompt_text: str
    first_message: str
    scenario_config: dict[str, Any]


def _build_sources_description(scenario_config: dict[str, Any]) -> str:
    parts: list[str] = []

    websites = scenario_config.get("websites")
    if isinstance(websites, list):
        cleaned = [str(item).strip() for item in websites if str(item).strip()]
        if cleaned:
            website_text = ", ".join(cleaned[:3])
            if len(cleaned) == 1:
                parts.append(f"- sito ufficiale del Comune: {website_text}")
            else:
                parts.append(f"- siti ufficiali del Comune: {website_text}")

    kb_path = scenario_config.get("knowledge_base_path")
    if isinstance(kb_path, str) and kb_path.strip():
        parts.append("- knowledge base interna derivata dai contenuti istituzionali e documentali del Comune")

    if not parts:
        parts.append("- contenuti istituzionali e fonti ufficiali del Comune disponibili nel sistema")

    return "\n".join(parts)


def resolve_voice_bundle(service: str = "realtime") -> VoiceScenarioBundle:
    config = load_config()
    scenario = resolve_scenario(config, service)
    scenario_name = str(scenario.get("name") or "tenant_runtime").strip().lower()
    overrides = config.get("prompt_overrides") if isinstance(config.get("prompt_overrides"), dict) else {}
    prompt_override = str(overrides.get("primary_prompt") or overrides.get("prompt_a") or "").strip()
    first_message_override = str(overrides.get("secondary_prompt") or overrides.get("prompt_b") or "").strip()
    first_message = first_message_override or str(scenario.get("first_message") or "").strip()
    scenario_config = load_scenario_config(scenario.get("config_path"))

    if not prompt_override:
        raise RuntimeError("Primary prompt missing from runtime configuration")
    if not first_message:
        raise RuntimeError("First message missing from runtime configuration")

    prompt_text = prompt_override.replace(
        "{{sources_description}}",
        _build_sources_description(scenario_config),
    )
    return VoiceScenarioBundle(
        scenario_name=scenario_name,
        prompt_text=resolve_prompt_template(prompt_text),
        first_message=first_message,
        scenario_config=scenario_config,
    )
