"""
Ascolta - Zadarma number-to-SIP-URI provisioning.

Companion to xai_provisioning.py: that half registers a number WITH xAI
("here is a number you'll receive calls for"); this half tells Zadarma
(or whichever carrier owns the PSTN number) WHERE to actually send the
SIP traffic for it. Together they complete the chain Zadarma (PSTN) ->
xAI SIP gateway -> Ascolta webhook that maintainer asked for (18/08:
"insieme con le istruzioni per reindirizzare da zadarma o equivalente").

Confirmed via official docs before writing this (WebFetch, not guessed):
- xAI byo_trunk expects SIP traffic at sip:{number}@sip.voice.x.ai;transport=tls
  (https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech/sip)
- Zadarma's `PUT /v1/direct_numbers/set_sip_id/` assigns a virtual/direct
  number to an *external* SIP URI - this is the redirect-to-a-foreign-SIP-
  server endpoint, distinct from `PUT /v1/sip/redirection/` (which forwards
  to a phone number, for busy/unavailable call-forwarding - not this case).
  (https://zadarma.com/en/support/api/)

NOT the same credentials as earlier-prototype's SIP trunk login/password
(ZADARMA_SIP_USERNAME/PASSWORD in .env - those authenticate a SIP
REGISTER, they don't call the REST API). Zadarma's REST API needs a
separate API key/secret pair (from the Zadarma dashboard, Settings > API),
resolved per-tenant like every other credential here - no env fallback,
same rule as xai_provisioning.py. If a tenant hasn't configured that
pair, callers should fall back to showing manual instructions
(see build_manual_instructions() below) instead of failing silently.
"""

import base64
import hashlib
import hmac
import logging
import urllib.parse
from typing import Any, Dict, Optional
from uuid import UUID

import httpx

logger = logging.getLogger(__name__)

ZADARMA_API_BASE = "https://api.zadarma.com"
SET_SIP_ID_PATH = "/v1/direct_numbers/set_sip_id/"


async def _resolve_zadarma_api_credentials(tenant_id: UUID) -> Optional[Dict[str, str]]:
    """
    Per-tenant Zadarma REST API key/secret - service_type="telephony",
    provider="zadarma". Distinct row from the xai voice credential; a
    tenant can have neither, either, or both configured. No env fallback
    (same CredentialsManager._fetch_db_credentials() pattern as
    resolve_provider_api_key() in agent_versions.py).
    """
    if not tenant_id:
        return None
    from app.services.credentials.manager import CredentialsManager

    manager = CredentialsManager()
    creds = await manager._fetch_db_credentials(
        entity_type="tenant", entity_id=tenant_id, service_type="telephony", provider="zadarma",
    )
    if not creds or not creds.get("api_key") or not creds.get("api_secret"):
        return None
    return creds


def _sign_request(method_path: str, params: Dict[str, Any], api_secret: str) -> str:
    """
    Zadarma's HMAC-SHA1 signature scheme, exactly as documented:
    sort params alphabetically by key, http_build_query-encode them,
    then HMAC-SHA1( method_path + encoded_params + md5(encoded_params),
    api_secret ), base64-encoded.
    """
    sorted_params = dict(sorted(params.items()))
    encoded = urllib.parse.urlencode(sorted_params)
    md5_hash = hashlib.md5(encoded.encode("utf-8")).hexdigest()
    to_sign = f"{method_path}{encoded}{md5_hash}"
    digest = hmac.new(api_secret.encode("utf-8"), to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode("utf-8")


def xai_sip_uri(phone_number: str) -> str:
    """The exact URI xAI's byo_trunk docs specify - see module docstring."""
    return f"sip:{phone_number}@sip.voice.x.ai;transport=tls"


async def point_number_at_sip_uri(
    tenant_id: UUID,
    phone_number: str,
    sip_uri: str,
) -> Dict[str, Any]:
    """
    Calls Zadarma's PUT /v1/direct_numbers/set_sip_id/ to redirect
    phone_number's SIP routing at an external sip_uri (e.g. xai_sip_uri(...)
    or a LiveKit SIP trunk endpoint). Requires the tenant to have a
    Zadarma API key/secret configured (service_type="telephony",
    provider="zadarma") - raises ValueError if not, so the caller can show
    manual instructions instead (see build_manual_instructions()).
    """
    creds = await _resolve_zadarma_api_credentials(tenant_id)
    if not creds:
        raise ValueError(
            f"No telephony/zadarma API credential (api_key + api_secret) stored for "
            f"tenant {tenant_id} - cannot call Zadarma's API. Use "
            f"build_manual_instructions() to show the manual dashboard steps instead."
        )

    params = {"number": phone_number, "sip_id": sip_uri}
    signature = _sign_request(SET_SIP_ID_PATH, params, creds["api_secret"])

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.put(
            ZADARMA_API_BASE + SET_SIP_ID_PATH,
            headers={"Authorization": f"{creds['api_key']}:{signature}"},
            data=params,
        )

    if resp.status_code >= 300:
        logger.error(f"Zadarma set_sip_id failed: {resp.status_code} {resp.text}")
        raise RuntimeError(f"Zadarma set_sip_id failed: {resp.status_code} {resp.text}")

    result = resp.json()
    if isinstance(result, dict) and result.get("status") not in (None, "success"):
        # Zadarma returns 200 with a status/message field even on logical
        # errors (e.g. wrong number, no permission) - surface it explicitly
        # rather than reporting success on a 200 that isn't actually one.
        logger.error(f"Zadarma set_sip_id returned non-success status: {result}")
        raise RuntimeError(f"Zadarma set_sip_id error: {result}")

    logger.info(f"Zadarma: {phone_number} -> {sip_uri}")
    return result


def build_manual_instructions(phone_number: str, sip_uri: str) -> Dict[str, str]:
    """
    Fallback shown in the admin UI when a tenant hasn't configured Zadarma
    API credentials (or is using a different carrier entirely) - the exact
    manual steps to reach the same end state by hand in the Zadarma
    dashboard. Kept as data (not just a hardcoded UI string) so other
    routers/tests can reuse the same text.
    """
    return {
        "provider": "zadarma",
        "phone_number": phone_number,
        "target_sip_uri": sip_uri,
        "steps": (
            f"1. Accedi al pannello Zadarma (my.zadarma.com).\n"
            f"2. Vai su 'Numeri virtuali' (Direct numbers) e seleziona {phone_number}.\n"
            f"3. Nella sezione di instradamento della chiamata, scegli 'Inoltra a un URI SIP esterno' "
            f"e inserisci: {sip_uri}\n"
            f"4. Salva. Le chiamate in arrivo su {phone_number} verranno da questo momento "
            f"inviate direttamente a questo indirizzo SIP, non più all'account SIP interno Zadarma.\n"
            f"5. (Alternativa via API, se l'automazione è configurata per questo tenant: "
            f"Ascolta può farlo automaticamente con le credenziali API Zadarma - vedi Credenziali tenant, "
            f"servizio 'telephony', provider 'zadarma'.)"
        ),
    }
