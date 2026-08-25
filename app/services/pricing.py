"""Ascolta - voice call cost estimation."""

import json
from typing import Optional

# grok-voice-latest = alias di grok-voice-think-fast-2.0 dal 5/8/2026
# (fonte: bleap.finance/en-us/blog/all-about-grok-voice-think-fast-2-0),
# $0.08/min audio (fonte: docs.x.ai/docs/models).
#
# Importante per questo progetto: il percorso `xai_sip_direct` oggi NON
# usa un numero provisionato da xAI, ma una numerazione esterna inoltrata
# via SIP (Zadarma). Quindi il fallback stimato non deve aggiungere la
# surcharge telephony da $0.01/min che xAI applica solo quando la
# numerazione e' acquistata/provisionata direttamente da loro.
#
# Le tool call (search_knowledge_base, calcom, ecc.) si fatturano a parte
# e non sono incluse qui - non abbiamo ancora dati di utilizzo per quelle.
USD_TICKS_PER_USD = 10_000_000_000
VOICE_PRICING_SETTINGS_KEY = "xai_voice_pricing_per_minute"
DEFAULT_XAI_VOICE_MODEL = "grok-voice-latest"
DEFAULT_XAI_VOICE_PRICING_PER_MINUTE = {
    "grok-voice-latest": 0.08,
    "grok-voice-think-fast-2.0": 0.08,
    "grok-voice-think-fast-1.0": 0.05,
}


def cost_usd_from_ticks(cost_in_usd_ticks: Optional[int]) -> Optional[float]:
    """
    xAI returns exact billed cost as integer ticks, where 1 USD = 1e10
    ticks. None means the provider didn't include the exact billed amount
    for that response.
    """
    if cost_in_usd_ticks is None:
        return None
    return round(cost_in_usd_ticks / USD_TICKS_PER_USD, 10)


def default_xai_voice_pricing_per_minute() -> dict[str, float]:
    return dict(DEFAULT_XAI_VOICE_PRICING_PER_MINUTE)


def normalize_xai_voice_pricing_per_minute(
    pricing: Optional[dict[str, object]],
) -> dict[str, float]:
    normalized = default_xai_voice_pricing_per_minute()
    if not pricing:
        return normalized
    for model, raw_rate in pricing.items():
        if not isinstance(model, str):
            continue
        try:
            rate = float(raw_rate)
        except (TypeError, ValueError):
            continue
        if rate <= 0:
            continue
        normalized[model] = round(rate, 6)
    return normalized


async def load_xai_voice_pricing_per_minute(db) -> dict[str, float]:
    row = await db.fetch_one(
        "SELECT value FROM settings WHERE key = :key",
        {"key": VOICE_PRICING_SETTINGS_KEY},
    )
    if not row or not row["value"]:
        return default_xai_voice_pricing_per_minute()
    try:
        parsed = json.loads(row["value"])
    except (TypeError, ValueError, json.JSONDecodeError):
        return default_xai_voice_pricing_per_minute()
    if not isinstance(parsed, dict):
        return default_xai_voice_pricing_per_minute()
    return normalize_xai_voice_pricing_per_minute(parsed)


def resolve_xai_voice_rate_per_minute(
    pricing_per_minute: dict[str, float],
    model_name: Optional[str],
) -> float:
    if model_name and model_name in pricing_per_minute:
        return pricing_per_minute[model_name]
    if model_name == "grok-voice-think-fast-2":
        return pricing_per_minute.get(
            "grok-voice-think-fast-2.0",
            pricing_per_minute[DEFAULT_XAI_VOICE_MODEL],
        )
    return pricing_per_minute.get(
        DEFAULT_XAI_VOICE_MODEL,
        DEFAULT_XAI_VOICE_PRICING_PER_MINUTE[DEFAULT_XAI_VOICE_MODEL],
    )


def estimate_xai_call_cost_usd(
    audio_seconds: Optional[int],
    model_name: Optional[str] = None,
    pricing_per_minute: Optional[dict[str, float]] = None,
) -> Optional[float]:
    if audio_seconds is None:
        return None
    pricing = normalize_xai_voice_pricing_per_minute(pricing_per_minute)
    rate_per_minute = resolve_xai_voice_rate_per_minute(pricing, model_name)
    minutes = audio_seconds / 60
    return round(minutes * rate_per_minute, 4)
