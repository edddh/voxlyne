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

import json
import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.config import get_settings
from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.services import elevenlabs_provisioning
from app.services import xai_provisioning, zadarma_provisioning
from app.services.credentials.manager import CredentialsManager
from app.services.demo_showcase import is_demo_tenant

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectNumberRequest(BaseModel):
    project_id: UUID
    phone_number: str = Field(..., description="E.164, e.g. +39 000 000 0000")
    name: Optional[str] = Field(None, description="Label for the provider registration; defaults to the project slug")


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str):
        try:
            data = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return dict(data) if isinstance(data, dict) else {}
    return {}


def _xai_target(phone_number: str) -> str:
    return zadarma_provisioning.xai_sip_uri(phone_number)


def _eleven_target(phone_number: str) -> str:
    return elevenlabs_provisioning.elevenlabs_target_sip_uri(phone_number)


def _build_eleven_manual_instructions(phone_number: str, sip_uri: str, rollback_sip_uri: str | None) -> dict[str, str]:
    rollback_note = (
        f"\n5. Per tornare alla configurazione precedente, reimposta il target SIP a: {rollback_sip_uri}"
        if rollback_sip_uri
        else ""
    )
    return {
        "provider": "zadarma",
        "phone_number": phone_number,
        "target_sip_uri": sip_uri,
        "steps": (
            f"1. In ElevenLabs Agents importa il numero {phone_number} come SIP trunk e assegnagli l'agente provisionato.\n"
            f"2. In Zadarma apri il numero {phone_number} e scegli l'inoltro verso URI SIP esterno.\n"
            f"3. Imposta come destinazione: {sip_uri}\n"
            f"4. Salva la modifica e fai una chiamata di prova."
            f"{rollback_note}"
        ),
    }


async def _set_inbound_endpoint(phone_number: str, tenant_id: UUID, project_id: UUID) -> None:
    db = get_database()
    existing = await db.fetch_one(
        "SELECT id FROM inbound_endpoints WHERE identifier = :id",
        {"id": phone_number},
    )
    if existing:
        await db.execute(
            """UPDATE inbound_endpoints
               SET project_id = :project_id, tenant_id = :tenant_id, is_active = TRUE
               WHERE id = :id""",
            {"id": existing["id"], "project_id": str(project_id), "tenant_id": str(tenant_id)},
        )
    else:
        await db.execute(
            """INSERT INTO inbound_endpoints (tenant_id, project_id, identifier, identifier_type, is_active)
               VALUES (:tenant_id, :project_id, :identifier, 'phone_number', TRUE)""",
            {"tenant_id": str(tenant_id), "project_id": str(project_id), "identifier": phone_number},
        )


async def _save_project_provider_config(project_id: UUID, provider_config: dict[str, Any]) -> None:
    db = get_database()
    await db.execute(
        """
        UPDATE projects
        SET voice_provider_config = :voice_provider_config,
            updated_at = NOW()
        WHERE id = :id
        """,
        {"id": str(project_id), "voice_provider_config": json.dumps(provider_config)},
    )


@router.post("/telephony/connect-number")
async def connect_number(
    body: ConnectNumberRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
) -> Dict[str, Any]:
    db = get_database()
    project = await db.fetch_one(
        "SELECT id, tenant_id, slug, name, voice_engine, voice_provider_config FROM projects WHERE id = :id",
        {"id": str(body.project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Project has no owning tenant - cannot resolve credentials")
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=403, detail="Access denied to this project")

    if is_demo_tenant(tenant_id):
        raise HTTPException(status_code=403, detail="Demo projects cannot connect phone numbers")

    provider_config = _json_object(project["voice_provider_config"])
    previous_endpoint = await db.fetch_one(
        """
        SELECT e.project_id, p.name, p.voice_engine
        FROM inbound_endpoints e
        LEFT JOIN projects p ON p.id = e.project_id
        WHERE e.identifier = :identifier AND e.is_active = TRUE
        LIMIT 1
        """,
        {"identifier": body.phone_number},
    )
    previous_target_sip_uri = None
    if previous_endpoint and previous_endpoint["voice_engine"] == "xai_sip_direct":
        previous_target_sip_uri = _xai_target(body.phone_number)
    elif previous_endpoint and previous_endpoint["voice_engine"] == "elevenlabs_agent":
        previous_target_sip_uri = _eleven_target(body.phone_number)

    rollback_cfg = provider_config.get("rollback") if isinstance(provider_config.get("rollback"), dict) else {}
    rollback_cfg.update(
        {
            "phone_number": body.phone_number,
            "previous_project_id": str(previous_endpoint["project_id"]) if previous_endpoint else None,
            "previous_project_name": previous_endpoint["name"] if previous_endpoint else None,
            "previous_voice_engine": previous_endpoint["voice_engine"] if previous_endpoint else None,
            "previous_target_sip_uri": previous_target_sip_uri,
        }
    )
    provider_config["rollback"] = rollback_cfg

    if project["voice_engine"] == "elevenlabs_agent":
        eleven_status: dict[str, Any]
        try:
            eleven_status = await elevenlabs_provisioning.provision_agent_for_project(body.project_id)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=f"ElevenLabs provisioning failed: {e}")

        target_sip_uri = _eleven_target(body.phone_number)
        eleven_cfg = provider_config.get("elevenlabs") if isinstance(provider_config.get("elevenlabs"), dict) else {}
        eleven_cfg.update(
            {
                "phone_number": body.phone_number,
                "target_sip_uri": target_sip_uri,
                "routing_mode": "manual_sip_trunk",
            }
        )
        provider_config["elevenlabs"] = eleven_cfg
        await _save_project_provider_config(body.project_id, provider_config)
        await _set_inbound_endpoint(body.phone_number, tenant_id, body.project_id)

        return {
            "phone_number": body.phone_number,
            "provider": "elevenlabs_agent",
            "elevenlabs": {
                **eleven_status,
                "sip_uri": target_sip_uri,
            },
            "zadarma": {
                "status": "manual_required",
                **_build_eleven_manual_instructions(
                    body.phone_number,
                    target_sip_uri,
                    rollback_cfg.get("previous_target_sip_uri"),
                ),
            },
            "rollback": rollback_cfg,
            "inbound_endpoint": "active",
        }

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
    provider_config["rollback"] = rollback_cfg
    await _save_project_provider_config(body.project_id, provider_config)
    await _set_inbound_endpoint(body.phone_number, tenant_id, body.project_id)

    return {
        "phone_number": body.phone_number,
        "provider": "xai_sip_direct",
        "webhook_url": webhook_url,
        "xai": {
            "status": "registered",
            "phone_number_id": phone_number_id,
            "sip_uri": sip_uri,
        },
        "zadarma": {"status": zadarma_status, **zadarma_detail},
        "rollback": rollback_cfg,
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
        "SELECT id, tenant_id, voice_engine, voice_provider_config FROM projects WHERE id = :id",
        {"id": str(body.project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Project has no owning tenant")
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=403, detail="Access denied to this project")

    provider_config = _json_object(project["voice_provider_config"])
    rollback_cfg = provider_config.get("rollback") if isinstance(provider_config.get("rollback"), dict) else {}

    if project["voice_engine"] == "elevenlabs_agent":
        await db.execute(
            "UPDATE inbound_endpoints SET is_active = FALSE WHERE identifier = :id AND project_id = :project_id",
            {"id": body.phone_number, "project_id": str(body.project_id)},
        )
        previous_project_id = rollback_cfg.get("previous_project_id")
        if previous_project_id:
            await db.execute(
                """
                UPDATE inbound_endpoints
                SET project_id = :previous_project_id,
                    tenant_id = :tenant_id,
                    is_active = TRUE
                WHERE identifier = :identifier
                """,
                {
                    "previous_project_id": previous_project_id,
                    "tenant_id": str(tenant_id),
                    "identifier": body.phone_number,
                },
            )
        return {
            "phone_number": body.phone_number,
            "provider": "elevenlabs_agent",
            "inbound_endpoint": "deactivated",
            "rollback": rollback_cfg,
            "zadarma": {
                "status": "manual_required",
                "target_sip_uri": rollback_cfg.get("previous_target_sip_uri"),
                "steps": (
                    f"Reimposta in Zadarma l'URI SIP esterno del numero {body.phone_number} a "
                    f"{rollback_cfg.get('previous_target_sip_uri') or 'quello precedente'}."
                ),
            },
        }

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

    await db.execute(
        "UPDATE inbound_endpoints SET is_active = FALSE WHERE identifier = :id AND project_id = :project_id",
        {"id": body.phone_number, "project_id": str(body.project_id)},
    )

    return {
        "phone_number": body.phone_number,
        "provider": "xai_sip_direct",
        "xai": xai_status,
        "inbound_endpoint": "deactivated",
    }
