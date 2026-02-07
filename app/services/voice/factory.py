"""
Ascolta - Voice Engine Factory

Creates the appropriate voice engine based on project configuration.
"""

import logging
from typing import Dict, Optional

from app.config import get_settings
from app.services.voice.base import BaseVoiceEngine, VoiceEngineType

logger = logging.getLogger(__name__)

# Cache engine instances to reuse connections
_engine_cache: Dict[VoiceEngineType, BaseVoiceEngine] = {}


def get_voice_engine(engine_type: str = "openai_realtime") -> BaseVoiceEngine:
    """
    Get a voice engine instance by type.

    Args:
        engine_type: Voice engine type string (from project settings)

    Returns:
        Configured BaseVoiceEngine instance
    """
    try:
        vtype = VoiceEngineType(engine_type)
    except ValueError:
        logger.warning(f"Unknown voice engine type '{engine_type}', falling back to openai_realtime")
        vtype = VoiceEngineType.OPENAI_REALTIME

    if vtype in _engine_cache:
        return _engine_cache[vtype]

    engine = _create_engine(vtype)
    _engine_cache[vtype] = engine
    return engine


def _create_engine(vtype: VoiceEngineType) -> BaseVoiceEngine:
    """Create a new voice engine instance."""
    settings = get_settings()

    if vtype == VoiceEngineType.OPENAI_REALTIME:
        from app.services.voice.openai_realtime import OpenAIRealtimeEngine
        return OpenAIRealtimeEngine(settings=settings)

    elif vtype == VoiceEngineType.VAPI:
        from app.services.voice.vapi_engine import VapiEngine
        return VapiEngine(settings=settings)

    else:
        raise ValueError(f"Unsupported voice engine type: {vtype}")


def clear_engine_cache() -> None:
    """Clear the engine cache (useful for testing)."""
    _engine_cache.clear()
