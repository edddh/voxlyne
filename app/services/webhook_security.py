"""
Voxlyne - Webhook signature verification and idempotency.

Shared by app/routers/webhook.py (OpenAI) and app/routers/webhook_vapi.py.
Signature verification is opt-in (see app/config.py): while the matching
secret isn't configured, verification is skipped with one warning per
process, not enforced - see the field docstrings in config.py for why.
"""

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import Request

from app.config import get_settings
from app.database.db import get_database

logger = logging.getLogger(__name__)

_warned_openai_unverified = False
_warned_vapi_unverified = False


class WebhookVerificationError(Exception):
    """Raised when a webhook's signature is present but invalid."""


async def verify_openai_signature(raw_body: bytes, request: Request) -> None:
    """
    Verify an OpenAI webhook using the Standard Webhooks scheme
    (webhook-id/webhook-timestamp/webhook-signature headers), via the
    openai SDK's own unwrap(). No-op (with one warning) if
    OPENAI_WEBHOOK_SECRET isn't set.

    Raises WebhookVerificationError if a secret is configured and the
    signature doesn't check out. Never raises just because a secret isn't
    configured - see module docstring.
    """
    global _warned_openai_unverified
    settings = get_settings()

    if not settings.openai_webhook_secret:
        if not _warned_openai_unverified:
            logger.warning(
                "OPENAI_WEBHOOK_SECRET non configurato: la firma dei webhook "
                "OpenAI non viene verificata. Impostalo solo dopo aver "
                "configurato lo stesso secret anche nella console OpenAI."
            )
            _warned_openai_unverified = True
        return

    from openai import OpenAI

    client = OpenAI(api_key=settings.openai_api_key)
    try:
        client.webhooks.unwrap(raw_body, request.headers, secret=settings.openai_webhook_secret)
    except Exception as e:
        raise WebhookVerificationError(f"OpenAI webhook signature invalid: {e}") from e


async def verify_vapi_signature(raw_body: bytes, request: Request) -> None:
    """
    Verify a Vapi webhook via HMAC-SHA256 of the raw body against the
    x-vapi-signature header. No-op (with one warning) if
    VAPI_WEBHOOK_SECRET isn't set. Same non-raising behavior as
    verify_openai_signature when unconfigured.
    """
    global _warned_vapi_unverified
    settings = get_settings()

    if not settings.vapi_webhook_secret:
        if not _warned_vapi_unverified:
            logger.warning(
                "VAPI_WEBHOOK_SECRET non configurato: la firma dei webhook "
                "Vapi non viene verificata. Impostalo solo dopo aver "
                "configurato lo stesso secret sulla server URL in Vapi."
            )
            _warned_vapi_unverified = True
        return

    signature = request.headers.get("x-vapi-signature", "")
    expected = hmac.new(
        settings.vapi_webhook_secret.encode("utf-8"), raw_body, hashlib.sha256
    ).hexdigest()

    if not signature or not hmac.compare_digest(signature, expected):
        raise WebhookVerificationError("Vapi webhook signature invalid or missing")


async def is_duplicate_event(provider: str, event_id: Optional[str]) -> bool:
    """
    Record (provider, event_id) in webhook_events. Returns True if this
    exact event was already processed (caller should skip side effects and
    return success anyway, so the provider doesn't retry forever), False
    if this is the first time - in which case it's now recorded, so a
    concurrent duplicate delivery landing at the same moment still can't
    both proceed (UNIQUE constraint, not a check-then-insert race).

    event_id=None (provider sent nothing usable) is never treated as a
    duplicate - every such event is processed, since there's no way to
    tell them apart from a fresh one.
    """
    if not event_id:
        return False

    db = get_database()
    try:
        await db.execute(
            "INSERT INTO webhook_events (provider, event_id) VALUES (:provider, :event_id)",
            {"provider": provider, "event_id": event_id},
        )
        return False
    except Exception as e:
        # asyncpg raises a UniqueViolationError (wrapped) on the UNIQUE
        # (provider, event_id) constraint - anything else is a real error,
        # not a duplicate, and should not be swallowed as one.
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            logger.info(f"Webhook event duplicato ignorato: {provider}/{event_id}")
            return True
        raise
