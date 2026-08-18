"""
Ascolta - Telephony provisioning router (admin-UI-facing).

Answers maintainer's explicit request (18/08): "questa procedura dovrà essere
eseguibile tramite interfaccia ascolta, insieme con le istruzioni per
reindirizzare da zadarma o equivalente". One endpoint that does both halves
of connecting a real phone number to an Ascolta project:

  1. Register the number with xAI's byo_trunk SIP gateway
     (app/services/xai_provisioning.py) -> gives us a webhook signing
     secret and the exact SIP URI (sip:{number}@sip.voice.x.ai) to send it.
  2. Point the number's carrier-side routing at that SIP URI. If the
     tenant has Zadarma API credentials configured, this is automated
     (app/services/zadarma_provisioning.py). If not - or the tenant uses a
     different carrier - the response includes the manual steps to do it
     by hand, so the admin UI always has something concrete to show,
     never a dead end.
  3. Create/update the inbound_endpoints row so the Fase 2 kernel resolver
     (resolve_inbound()) actually routes calls for this number to this
     project once traffic starts arriving.

This does NOT run automatically on any schedule or on project creation -
registering a number with xAI re-points its live SIP routing (see
xai_provisioning.py's docstring), so it only ever runs when an admin
explicitly triggers it for one specific number from the UI. That explicit
click is the human-confirmation step this used to require manually.
"""

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.services import xai_provisioning, zadarma_provisioning
from app.services.credentials.manager import CredentialsManager

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectNumberRequest(BaseModel):
    project_id: UUID
    phone_number: str = Field(..., description="E.164, e.g. +39 000 000 0000")
    name: Optional[str] = Field(None, description="Label for the xAI registration; defaults to the project slug")


@router.post("/telephony/connect-number")
async def connect_number(
    body: ConnectNumberRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
) -> Dict[str, Any]:
    db = get_database()
    project = await db.fetch_one(
        "SELECT id, tenant_id, slug FROM projects WHERE id = :id",
        {"id": str(body.project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Project has no owning tenant - cannot resolve credentials")
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=403, detail="Access denied to this project")

    settings = get_settings()
    webhook_url = f"{settings.webhook_base_url.rstrip('/')}/api/webhook/xai-call"

    # --- 1. xAI side: register the number, get back a webhook signing secret ---
    try:
        xai_result = await xai_provisioning.register_byo_trunk_number(
            tenant_id=tenant_id,
            phone_number=body.phone_number,
            webhook_url=webhook_url,
            name=body.name or project["slug"],
        )
    except ValueError as e:
        # No xai voice credential for this tenant - not an xAI API failure,
        # a missing prerequisite. 400, not 500.
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=f"xAI registration failed: {e}")

    # Persist what we got back (dispatch signing secret, phone_number_id) so
    # webhook signature verification can be turned on later, and so a future
    # "disconnect number" action knows what to delete. Best-effort: a failure
    # here shouldn't undo the xAI registration that already succeeded.
    dispatch_secret = (xai_result.get("webhook") or {}).get("dispatchSigningSecret")
    phone_number_id = xai_result.get("id") or xai_result.get("phoneNumberId")
    try:
        manager = CredentialsManager()
        await manager.set_credentials(
            entity_type="tenant",
            entity_id=tenant_id,
            service_type="telephony",
            provider="xai",
            data={
                "dispatch_signing_secret": dispatch_secret or "",
                "phone_number_id": phone_number_id or "",
                "phone_number": body.phone_number,
            },
            credential_key=f"number:{body.phone_number}",
        )
    except Exception:
        logger.exception("Failed to persist xAI dispatch secret/phone_number_id (registration itself succeeded)")

    # --- 2. Carrier side: point the number at xAI's SIP URI ---
    sip_uri = zadarma_provisioning.xai_sip_uri(body.phone_number)
    zadarma_status = "not_attempted"
    zadarma_detail: Dict[str, Any] = {}
    try:
        zadarma_result = await zadarma_provisioning.point_number_at_sip_uri(
            tenant_id=tenant_id, phone_number=body.phone_number, sip_uri=sip_uri,
        )
        zadarma_status = "automated"
        zadarma_detail = {"result": zadarma_result}
    except ValueError:
        # No Zadarma API credentials for this tenant - expected/common case,
        # not an error. Show manual instructions instead.
        zadarma_status = "manual_required"
        zadarma_detail = zadarma_provisioning.build_manual_instructions(body.phone_number, sip_uri)
    except RuntimeError as e:
        zadarma_status = "failed"
        zadarma_detail = {
            "error": str(e),
            **zadarma_provisioning.build_manual_instructions(body.phone_number, sip_uri),
        }

    # --- 3. Kernel: route this number to this project once calls arrive ---
    existing = await db.fetch_one(
        "SELECT id FROM inbound_endpoints WHERE identifier = :id",
        {"id": body.phone_number},
    )
    if existing:
        await db.execute(
            """UPDATE inbound_endpoints
               SET project_id = :project_id, tenant_id = :tenant_id, is_active = TRUE
               WHERE id = :id""",
            {"id": existing["id"], "project_id": str(body.project_id), "tenant_id": str(tenant_id)},
        )
    else:
        await db.execute(
            """INSERT INTO inbound_endpoints (tenant_id, project_id, identifier, identifier_type, is_active)
               VALUES (:tenant_id, :project_id, :identifier, 'phone_number', TRUE)""",
            {"tenant_id": str(tenant_id), "project_id": str(body.project_id), "identifier": body.phone_number},
        )

    return {
        "phone_number": body.phone_number,
        "webhook_url": webhook_url,
        "xai": {
            "status": "registered",
            "phone_number_id": phone_number_id,
            "sip_uri": sip_uri,
        },
        "zadarma": {"status": zadarma_status, **zadarma_detail},
        "inbound_endpoint": "active",
    }


class DisconnectNumberRequest(BaseModel):
    project_id: UUID
    phone_number: str = Field(..., description="E.164, must match how it was registered by connect-number")


@router.post("/telephony/disconnect-number")
async def disconnect_number(
    body: DisconnectNumberRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
) -> Dict[str, Any]:
    """
    Reverses connect_number(): deregisters the number from xAI (so it
    stops routing calls there) and deactivates its inbound_endpoints row
    (calls immediately stop resolving to this project even if xAI's own
    deregistration is slow to propagate). Does NOT touch the Zadarma-side
    SIP redirect - undoing that safely needs to know what to point the
    number back AT (its previous SIP account, another gateway...), which
    connect_number() never captured; leaving it pointed at xAI's now-dead
    registration just means the number stops working until an admin
    redirects it again, the same failure mode as forgetting to reconnect
    a phone line - visible and safe, not a silent misroute.
    """
    db = get_database()
    project = await db.fetch_one(
        "SELECT id, tenant_id FROM projects WHERE id = :id", {"id": str(body.project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Project has no owning tenant")
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=403, detail="Access denied to this project")

    manager = CredentialsManager()
    creds = await manager._fetch_db_credentials(
        entity_type="tenant", entity_id=tenant_id, service_type="telephony", provider="xai",
        credential_key=f"number:{body.phone_number}",
    )
    phone_number_id = creds.get("phone_number_id") if creds else None

    xai_status = "not_registered_via_ascolta"
    if phone_number_id:
        try:
            await xai_provisioning.deregister_byo_trunk_number(tenant_id, phone_number_id)
            xai_status = "deregistered"
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=f"xAI deregistration failed: {e}")

    result = await db.execute(
        "UPDATE inbound_endpoints SET is_active = FALSE WHERE identifier = :id AND project_id = :project_id",
        {"id": body.phone_number, "project_id": str(body.project_id)},
    )

    return {"phone_number": body.phone_number, "xai": xai_status, "inbound_endpoint": "deactivated"}
