"""
Voxlyne - Agent version and inbound endpoint management API (Fase 3).

Gives an admin/creator a way to publish/rollback agent_versions and manage
inbound_endpoints without touching the database directly - the kernel
pieces added in Fase 2 (app/services/agent_versions.py) had no API surface
until now.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.services.agent_versions import list_versions, publish_version, rollback_to_version
from app.services import elevenlabs_provisioning

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Agent Versions"])


# ===========================================
# Schemas
# ===========================================

class AgentVersionResponse(BaseModel):
    id: UUID
    version_number: int
    status: str
    prompt_a: Optional[str] = None
    prompt_b: Optional[str] = None
    consent_message: Optional[str] = None
    voice_name: Optional[str] = None
    language: Optional[str] = None
    voice_engine: Optional[str] = None
    published_at: Optional[str] = None
    created_at: str


class InboundEndpointCreate(BaseModel):
    project_id: UUID
    identifier: str = Field(..., min_length=1, max_length=255)
    identifier_type: str = Field(default="sip", pattern="^(sip|phone_number)$")


class InboundEndpointResponse(BaseModel):
    id: UUID
    project_id: UUID
    tenant_id: Optional[UUID] = None
    identifier: str
    identifier_type: str
    is_active: bool
    created_at: str


# ===========================================
# Helpers
# ===========================================

async def _assert_project_access(project_id: UUID, current_user: CurrentUser) -> None:
    db = get_database()
    project = await db.fetch_one(
        "SELECT id, tenant_id FROM projects WHERE id = :id",
        {"id": str(project_id)},
    )
    if not project or not check_tenant_access(current_user, project["tenant_id"]):
        raise HTTPException(status_code=404, detail="Project not found")


async def _sync_elevenlabs_agent(project_id: UUID) -> None:
    """Keep the direct ElevenLabs agent aligned with the published snapshot."""
    db = get_database()
    project = await db.fetch_one(
        "SELECT voice_engine FROM projects WHERE id = :id",
        {"id": str(project_id)},
    )
    if not project or project["voice_engine"] != "elevenlabs_agent":
        return

    try:
        await elevenlabs_provisioning.provision_agent_for_project(project_id)
    except Exception as exc:
        logger.exception("ElevenLabs sync failed after publishing project=%s", project_id)
        raise HTTPException(
            status_code=502,
            detail="Versione pubblicata, ma la sincronizzazione con ElevenLabs non e' riuscita. Riprova il publish.",
        ) from exc


# ===========================================
# Agent versions
# ===========================================

def _to_response(v: dict) -> AgentVersionResponse:
    return AgentVersionResponse(
        id=v["id"],
        version_number=v["version_number"],
        status=v["status"],
        prompt_a=v.get("prompt_a"),
        prompt_b=v.get("prompt_b"),
        consent_message=v.get("consent_message"),
        voice_name=v["voice_name"],
        language=v["language"],
        voice_engine=v["voice_engine"],
        published_at=v["published_at"].isoformat() if v["published_at"] else None,
        created_at=v["created_at"].isoformat(),
    )


@router.get("/api/projects/{project_id}/versions", response_model=List[AgentVersionResponse])
async def get_versions(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """List every version of this project's agent, newest first."""
    await _assert_project_access(project_id, current_user)
    versions = await list_versions(project_id)
    return [_to_response(v) for v in versions]


@router.post("/api/projects/{project_id}/versions/publish", response_model=AgentVersionResponse)
async def publish(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Freeze the project's current prompt/voice/language/engine into a new
    published version. Immediately live for inbound calls resolved through
    an inbound_endpoint pointing at this project (app/routers/webhook.py).
    """
    await _assert_project_access(project_id, current_user)
    try:
        result = await publish_version(project_id, created_by=current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _sync_elevenlabs_agent(project_id)

    versions = await list_versions(project_id)
    published = next(v for v in versions if v["id"] == result["id"])
    return _to_response(published)


@router.post("/api/projects/{project_id}/versions/{version_id}/rollback", response_model=AgentVersionResponse)
async def rollback(
    project_id: UUID,
    version_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Make an older, already-published version active again. Doesn't touch
    the project's current draft - only what inbound calls actually get.
    """
    await _assert_project_access(project_id, current_user)
    try:
        await rollback_to_version(project_id, version_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    await _sync_elevenlabs_agent(project_id)

    versions = await list_versions(project_id)
    published = next((v for v in versions if v["id"] == version_id), None)
    if not published:
        raise HTTPException(status_code=404, detail="Version not found")
    return _to_response(published)


# ===========================================
# Inbound endpoints
# ===========================================

@router.get("/api/inbound-endpoints", response_model=List[InboundEndpointResponse])
async def list_endpoints(
    project_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    List inbound endpoints. RLS already scopes this to the caller's tenant
    (see db_migrations/versions/22d55674165c_*.py) - the WHERE clause here
    is only for the optional project_id filter, tenant isolation doesn't
    depend on it.
    """
    db = get_database()
    if project_id:
        rows = await db.fetch_all(
            "SELECT * FROM inbound_endpoints WHERE project_id = :project_id ORDER BY created_at DESC",
            {"project_id": str(project_id)},
        )
    else:
        rows = await db.fetch_all("SELECT * FROM inbound_endpoints ORDER BY created_at DESC")
    return [
        InboundEndpointResponse(
            id=r["id"],
            project_id=r["project_id"],
            tenant_id=r["tenant_id"],
            identifier=r["identifier"],
            identifier_type=r["identifier_type"],
            is_active=r["is_active"],
            created_at=r["created_at"].isoformat(),
        )
        for r in rows
    ]


@router.post("/api/inbound-endpoints", response_model=InboundEndpointResponse, status_code=status.HTTP_201_CREATED)
async def create_endpoint(
    request: InboundEndpointCreate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    await _assert_project_access(request.project_id, current_user)
    db = get_database()

    project = await db.fetch_one(
        "SELECT tenant_id FROM projects WHERE id = :id", {"id": str(request.project_id)}
    )
    existing = await db.fetch_one(
        "SELECT id FROM inbound_endpoints WHERE identifier = :identifier",
        {"identifier": request.identifier},
    )
    if existing:
        raise HTTPException(status_code=409, detail=f"Endpoint already exists for '{request.identifier}'")

    row = await db.fetch_one(
        """
        INSERT INTO inbound_endpoints (tenant_id, project_id, identifier, identifier_type, created_by)
        VALUES (:tenant_id, :project_id, :identifier, :identifier_type, :created_by)
        RETURNING *
        """,
        {
            "tenant_id": str(project["tenant_id"]) if project["tenant_id"] else None,
            "project_id": str(request.project_id),
            "identifier": request.identifier,
            "identifier_type": request.identifier_type,
            "created_by": str(current_user.id),
        },
    )
    logger.info(f"Inbound endpoint created: {request.identifier} -> project={request.project_id} by {current_user.email}")
    return InboundEndpointResponse(
        id=row["id"],
        project_id=row["project_id"],
        tenant_id=row["tenant_id"],
        identifier=row["identifier"],
        identifier_type=row["identifier_type"],
        is_active=row["is_active"],
        created_at=row["created_at"].isoformat(),
    )


@router.delete("/api/inbound-endpoints/{endpoint_id}")
async def delete_endpoint(
    endpoint_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    db = get_database()
    existing = await db.fetch_one(
        "SELECT id, project_id FROM inbound_endpoints WHERE id = :id", {"id": str(endpoint_id)}
    )
    if not existing:
        raise HTTPException(status_code=404, detail="Endpoint not found")
    await _assert_project_access(existing["project_id"], current_user)

    await db.execute("DELETE FROM inbound_endpoints WHERE id = :id", {"id": str(endpoint_id)})
    logger.info(f"Inbound endpoint deleted: {endpoint_id} by {current_user.email}")
    return {"success": True}
