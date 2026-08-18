"""
Ascolta - xAI SIP-direct Webhook Router.

18/08/2026 (Grok/xAI priority): moved LegacyController's webhook handling
out of the standalone runtime_workers/realtime_service.py process and into
the main FastAPI app - the flow is structurally identical to webhook.py's
OpenAI path (webhook -> resolve tenant -> accept/open session -> events),
so it belongs in the same process instead of a second one to deploy and
monitor. LegacyController.handle_webhook() itself is untouched (same
kernel-resolver wiring from the previous commit) - only how it gets called
changed.

runtime_workers/realtime_service.py is NOT deleted: its RequestHandler/
ThreadingHTTPServer standalone-process path stays available (main()) for
anyone who wants to run it outside this app, but nothing here depends on
it anymore.
"""

import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter()

# Built lazily, once, on first use - not at import time. Importing
# runtime_workers.realtime_service is cheap, but LegacyController.__init__
# does a couple of file reads (load_config/load_scenario_config for the
# tools list - see ADR-0002, tools intentionally not kernel-integrated
# yet), no reason to pay that at every app boot if this router is never hit.
_controller = None


def _get_controller():
    global _controller
    if _controller is None:
        from runtime_workers.realtime_service import LegacyController

        _controller = LegacyController()
    return _controller


@router.post("/webhook/xai-call")
async def handle_xai_webhook(request: Request) -> Dict[str, Any]:
    """
    xAI's realtime.call.incoming / realtime.call.ended events. See
    LegacyController.handle_webhook() (runtime_workers/realtime_service.py)
    for the actual logic - signature verification (opt-in, same as
    OpenAI/Vapi - see app/services/webhook_security.py's pattern, mirrored
    here via self.webhook_secret), kernel resolver, per-tenant api_key.

    No FastAPI BackgroundTasks needed: handle_webhook() -> start_call_session()
    already does asyncio.create_task() internally for the call's realtime
    session, which keeps running after this handler returns on the same
    event loop uvicorn is already using.
    """
    controller = _get_controller()
    raw_body = await request.body()
    headers = dict(request.headers)

    try:
        result = await controller.handle_webhook(raw_body, headers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.exception("xAI webhook handling failed")
        raise HTTPException(status_code=500, detail=str(e))

    return result
