"""
Ascolta - xAI phone number provisioning (byo_trunk).

Registers a phone number the tenant already owns (via Zadarma or another
SIP provider - "byo_trunk" = bring your own trunk, this does NOT purchase
a number) with xAI's SIP gateway, pointing its webhook at this app's real
/api/webhook/xai-call endpoint. Confirmed via xAI's own docs before writing
this (WebFetch/WebSearch, not guessed): POST https://api.x.ai/v2/phone-numbers,
body {origin: "byo_trunk", name, phone_number, webhook: {name, url}}, response
includes a webhook.dispatch_signing_secret ("whsec_...") to verify future
webhook deliveries.

Deliberately NOT auto-run against a real number: registering a number
re-points its existing SIP routing at xAI - doing this against a number
already registered elsewhere (e.g. earlier-prototype's own byo_trunk registration)
would silently break whatever is using it today. Always confirm the exact
number with a human first (see FEATURE_MATRIX.md).
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

import httpx

from app.services.agent_versions import resolve_provider_api_key

logger = logging.getLogger(__name__)

XAI_PHONE_NUMBERS_URL = "https://api.x.ai/v2/phone-numbers"


async def register_byo_trunk_number(
    tenant_id: UUID,
    phone_number: str,
    webhook_url: str,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Register phone_number with xAI as a byo_trunk SIP number, webhook
    pointed at webhook_url (must be this app's real, publicly reachable
    /api/webhook/xai-call - see app/routers/webhook_xai.py).

    Uses the SAME per-tenant xai/voice credential the call-handling path
    uses (resolve_provider_api_key) - no separate "admin" xAI key, no env
    fallback, same rule as everywhere else in this integration (18/08).

    Returns xAI's response dict, which includes webhook.dispatch_signing_secret
    - the caller is responsible for storing that (e.g. as a tenant
    credential, service_type="webhook", provider="xai") if webhook
    signature verification should be turned on for this number. Not done
    automatically here: deciding to enable signature verification is a
    deliberate step (see app/services/webhook_security.py's opt-in pattern
    for the OpenAI/Vapi webhooks), not a side effect of registration.
    """
    api_key = await resolve_provider_api_key(tenant_id, "xai")
    if not api_key:
        raise ValueError(f"No voice/xai credential stored for tenant {tenant_id} - cannot provision.")

    payload = {
        "origin": "byo_trunk",
        "name": name or f"Ascolta {phone_number}",
        "phone_number": phone_number,
        "webhook": {
            "name": f"Ascolta webhook {phone_number}",
            "url": webhook_url,
        },
    }

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(
            XAI_PHONE_NUMBERS_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )

    if resp.status_code >= 300:
        logger.error(f"xAI phone number registration failed: {resp.status_code} {resp.text}")
        raise RuntimeError(f"xAI registration failed: {resp.status_code} {resp.text}")

    result = resp.json()
    logger.info(f"Registered {phone_number} with xAI byo_trunk -> {webhook_url}")
    return result
