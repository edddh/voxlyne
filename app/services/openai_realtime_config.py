"""Shared OpenAI Realtime model configuration for project voice engines."""

import json
from typing import Any


DEFAULT_OPENAI_REALTIME_MODEL = "gpt-realtime"
OPENAI_REALTIME_MODELS = frozenset({
    "gpt-realtime",
    "gpt-realtime-1.5",
    "gpt-realtime-2",
})


def get_openai_realtime_model(provider_config: Any) -> str:
    if isinstance(provider_config, str):
        try:
            provider_config = json.loads(provider_config)
        except json.JSONDecodeError:
            provider_config = {}
    if not isinstance(provider_config, dict):
        return DEFAULT_OPENAI_REALTIME_MODEL
    openai_config = provider_config.get("openai")
    if not isinstance(openai_config, dict):
        return DEFAULT_OPENAI_REALTIME_MODEL
    model = openai_config.get("model")
    return model if model in OPENAI_REALTIME_MODELS else DEFAULT_OPENAI_REALTIME_MODEL


def validate_openai_realtime_model(provider_config: Any) -> None:
    if not isinstance(provider_config, dict):
        return
    openai_config = provider_config.get("openai")
    if not isinstance(openai_config, dict) or "model" not in openai_config:
        return
    if openai_config["model"] not in OPENAI_REALTIME_MODELS:
        allowed = ", ".join(sorted(OPENAI_REALTIME_MODELS))
        raise ValueError(f"Unsupported OpenAI Realtime model; allowed values: {allowed}")
