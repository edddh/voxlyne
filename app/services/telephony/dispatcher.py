"""
Ascolta - Telephony Dispatcher

Resolves a TelephonyProvider name to a BaseTelephonyProvider instance,
mirroring app.services.crm.dispatcher's provider-selection pattern.

Foundations phase only: no concrete provider classes exist yet
(app/services/telephony/providers/livekit_sip.py, zadarma_sip.py land in the
next implementation phase, see README Milestone 5). get_telephony_provider
raises NotImplementedError until then, so callers can already be written
against this interface.
"""

import logging
from typing import Dict, Type

from app.services.telephony.base import BaseTelephonyProvider

logger = logging.getLogger(__name__)

_PROVIDER_REGISTRY: Dict[str, Type[BaseTelephonyProvider]] = {}


def get_telephony_provider(provider: str) -> BaseTelephonyProvider:
    """
    Resolve a provider name ('livekit', 'zadarma') to a provider instance.

    Raises:
        NotImplementedError: no concrete telephony providers are registered
            yet in this foundations phase.
        ValueError: unknown provider name.
    """
    if provider not in ("livekit", "zadarma"):
        raise ValueError(f"Unknown telephony provider: {provider}")

    provider_cls = _PROVIDER_REGISTRY.get(provider)
    if provider_cls is None:
        raise NotImplementedError(
            f"Telephony provider '{provider}' is not implemented yet - "
            "concrete providers (app/services/telephony/providers/) land in "
            "the next implementation phase."
        )
    return provider_cls()
