"""
Ascolta - Credentials Management Router
M5.5: API endpoints for managing project-level service credentials
M5: extended with tenant-level service credentials (LLM/voice/telephony keys
settable per tenant, with project-level override - see CredentialsManager)
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.services.credentials.manager import CredentialsManager

logger = logging.getLogger(__name__)
router = APIRouter()


async def _check_project_access(project_id: UUID, current_user: CurrentUser) -> None:
    """Verify the project exists and the current user's tenant may access it."""
    db = get_database()
    project = await db.fetch_one(
        "SELECT tenant_id FROM projects WHERE id = :id",
        {"id": str(project_id)},
    )
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this project")


async def _check_tenant_access(tenant_id: UUID, current_user: CurrentUser) -> None:
    """Verify the tenant exists and the current user may access it."""
    db = get_database()
    tenant = await db.fetch_one(
        "SELECT id FROM tenants WHERE id = :id",
        {"id": str(tenant_id)},
    )
    if not tenant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tenant not found")

    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied to this tenant")


# ===========================================
# Request/Response Models
# ===========================================


class CredentialCreateRequest(BaseModel):
    """Request to create/update credentials."""

    service_type: str = Field(..., description="Service category (crm, voice, telephony, tts, calendar)")
    provider: str = Field(..., description="Provider name (vapi, twilio, elevenlabs, hubspot, etc.)")
    credential_key: Optional[str] = Field(default="default", description="Reference key for multiple credentials")
    data: Dict[str, str] = Field(..., description="Credential key-value pairs (will be encrypted)")
    expires_at: Optional[datetime] = Field(default=None, description="Optional expiration for OAuth tokens")


class CredentialResponse(BaseModel):
    """Response with credential metadata (NO sensitive data)."""

    id: int
    service_type: str
    provider: str
    credential_key: str
    is_active: bool
    last_used_at: Optional[datetime]
    expires_at: Optional[datetime]
    created_at: datetime


class CredentialListResponse(BaseModel):
    """List of credentials."""

    credentials: List[CredentialResponse]


class CredentialTestRequest(BaseModel):
    """Request to test credentials."""

    service_type: str
    provider: str
    data: Dict[str, str]


class CredentialTestResponse(BaseModel):
    """Test connection result."""

    success: bool
    message: str
    error: Optional[str] = None


# ===========================================
# Endpoints
# ===========================================


@router.post("/projects/{project_id}/credentials", response_model=CredentialResponse)
async def create_project_credential(
    project_id: UUID,
    request: CredentialCreateRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> CredentialResponse:
    """
    Create or update credentials for a project.

    The credentials are encrypted before storage.
    If credentials for the same service/provider/key exist, they will be updated.
    """
    await _check_project_access(project_id, current_user)
    db = get_database()

    # Verify project exists
    project = await db.fetch_one(
        "SELECT id FROM projects WHERE id = :id",
        {"id": str(project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Save credentials
    creds_manager = CredentialsManager()
    try:
        credential_id = await creds_manager.set_credentials(
            entity_type="project",
            entity_id=project_id,
            service_type=request.service_type,
            provider=request.provider,
            data=request.data,
            credential_key=request.credential_key,
            expires_at=request.expires_at,
        )

        # Fetch the created/updated credential metadata
        cred = await db.fetch_one(
            """
            SELECT id, service_type, provider, credential_key, is_active,
                   last_used_at, expires_at, created_at
            FROM service_credentials
            WHERE id = :id
            """,
            {"id": credential_id},
        )

        if not cred:
            raise HTTPException(status_code=500, detail="Failed to retrieve saved credential")

        return CredentialResponse(**dict(cred))

    except Exception as e:
        logger.error(f"Failed to save credentials: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {str(e)}")


@router.get("/projects/{project_id}/credentials", response_model=CredentialListResponse)
async def list_project_credentials(
    project_id: UUID,
    service_type: Optional[str] = None,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> CredentialListResponse:
    """
    List all credentials for a project (metadata only, NO sensitive data).

    Optionally filter by service_type.
    """
    await _check_project_access(project_id, current_user)
    db = get_database()

    # Verify project exists
    project = await db.fetch_one(
        "SELECT id FROM projects WHERE id = :id",
        {"id": str(project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # List credentials
    creds_manager = CredentialsManager()
    credentials_list = await creds_manager.list_credentials(
        entity_type="project",
        entity_id=project_id,
        service_type=service_type,
    )

    return CredentialListResponse(
        credentials=[CredentialResponse(**cred) for cred in credentials_list]
    )


@router.delete("/projects/{project_id}/credentials/{credential_id}")
async def delete_project_credential(
    project_id: UUID,
    credential_id: int,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> Dict[str, Any]:
    """
    Delete credentials for a project (soft-delete by default).
    """
    await _check_project_access(project_id, current_user)
    db = get_database()

    # Verify credential belongs to project
    cred = await db.fetch_one(
        """
        SELECT id FROM service_credentials
        WHERE id = :id
          AND entity_type = 'project'
          AND entity_id = :project_id
        """,
        {"id": credential_id, "project_id": str(project_id)},
    )

    if not cred:
        raise HTTPException(
            status_code=404,
            detail="Credential not found or does not belong to this project",
        )

    # Delete
    creds_manager = CredentialsManager()
    success = await creds_manager.delete_credentials(credential_id, hard_delete=False)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete credential")

    return {"success": True, "message": "Credential deleted successfully"}


@router.post("/projects/{project_id}/credentials/{credential_id}/test", response_model=CredentialTestResponse)
async def test_project_credential(
    project_id: UUID,
    credential_id: int,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> CredentialTestResponse:
    """
    Test if credentials are valid by calling the provider API.
    """
    await _check_project_access(project_id, current_user)
    db = get_database()

    # Fetch credential
    cred = await db.fetch_one(
        """
        SELECT service_type, provider, encrypted_data
        FROM service_credentials
        WHERE id = :id
          AND entity_type = 'project'
          AND entity_id = :project_id
          AND is_active = TRUE
        """,
        {"id": credential_id, "project_id": str(project_id)},
    )

    if not cred:
        raise HTTPException(
            status_code=404,
            detail="Credential not found or not active",
        )

    # Decrypt credentials
    from app.utils.encryption import decrypt_credentials

    try:
        credentials = decrypt_credentials(cred["encrypted_data"])
    except Exception as e:
        logger.error(f"Failed to decrypt credentials: {e}")
        raise HTTPException(status_code=500, detail="Failed to decrypt credentials")

    # Test connection
    creds_manager = CredentialsManager()
    result = await creds_manager.test_connection(
        service_type=cred["service_type"],
        provider=cred["provider"],
        credentials=credentials,
    )

    return CredentialTestResponse(**result)


@router.post("/credentials/test", response_model=CredentialTestResponse)
async def test_credentials_without_saving(
    request: CredentialTestRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user", "user"])),
) -> CredentialTestResponse:
    """
    Test credentials without saving them.

    Useful for validating credentials before creating a project credential.
    Requires authentication only (no entity access check) since nothing is
    persisted or read - but must not be reachable anonymously, since some
    providers (e.g. crm/generic_webhook) accept an arbitrary target URL.
    """
    creds_manager = CredentialsManager()
    result = await creds_manager.test_connection(
        service_type=request.service_type,
        provider=request.provider,
        credentials=request.data,
    )

    return CredentialTestResponse(**result)


# ===========================================
# Tenant-level credentials (M5)
#
# Same shape as project-level credentials above, but stored with
# entity_type='tenant'. A tenant credential is the default used by all of
# that tenant's projects unless a project sets its own override - see
# CredentialsManager.get_credentials_with_fallback (project -> tenant -> env).
# ===========================================


@router.post("/tenants/{tenant_id}/credentials", response_model=CredentialResponse)
async def create_tenant_credential(
    tenant_id: UUID,
    request: CredentialCreateRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
) -> CredentialResponse:
    """
    Create or update a tenant-level default credential.

    Encrypted before storage. If a credential for the same
    service/provider/key already exists for this tenant, it is updated.
    """
    await _check_tenant_access(tenant_id, current_user)
    db = get_database()

    creds_manager = CredentialsManager()
    try:
        credential_id = await creds_manager.set_credentials(
            entity_type="tenant",
            entity_id=tenant_id,
            service_type=request.service_type,
            provider=request.provider,
            data=request.data,
            credential_key=request.credential_key,
            expires_at=request.expires_at,
        )

        cred = await db.fetch_one(
            """
            SELECT id, service_type, provider, credential_key, is_active,
                   last_used_at, expires_at, created_at
            FROM service_credentials
            WHERE id = :id
            """,
            {"id": credential_id},
        )

        if not cred:
            raise HTTPException(status_code=500, detail="Failed to retrieve saved credential")

        return CredentialResponse(**dict(cred))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save tenant credentials: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save credentials: {str(e)}")


@router.get("/tenants/{tenant_id}/credentials", response_model=CredentialListResponse)
async def list_tenant_credentials(
    tenant_id: UUID,
    service_type: Optional[str] = None,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
) -> CredentialListResponse:
    """List all tenant-level default credentials (metadata only, NO sensitive data)."""
    await _check_tenant_access(tenant_id, current_user)

    creds_manager = CredentialsManager()
    credentials_list = await creds_manager.list_credentials(
        entity_type="tenant",
        entity_id=tenant_id,
        service_type=service_type,
    )

    return CredentialListResponse(
        credentials=[CredentialResponse(**cred) for cred in credentials_list]
    )


@router.delete("/tenants/{tenant_id}/credentials/{credential_id}")
async def delete_tenant_credential(
    tenant_id: UUID,
    credential_id: int,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
) -> Dict[str, Any]:
    """Delete a tenant-level default credential (soft-delete by default)."""
    await _check_tenant_access(tenant_id, current_user)
    db = get_database()

    cred = await db.fetch_one(
        """
        SELECT id FROM service_credentials
        WHERE id = :id
          AND entity_type = 'tenant'
          AND entity_id = :tenant_id
        """,
        {"id": credential_id, "tenant_id": str(tenant_id)},
    )

    if not cred:
        raise HTTPException(
            status_code=404,
            detail="Credential not found or does not belong to this tenant",
        )

    creds_manager = CredentialsManager()
    success = await creds_manager.delete_credentials(credential_id, hard_delete=False)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete credential")

    return {"success": True, "message": "Credential deleted successfully"}


@router.post("/tenants/{tenant_id}/credentials/{credential_id}/test", response_model=CredentialTestResponse)
async def test_tenant_credential(
    tenant_id: UUID,
    credential_id: int,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
) -> CredentialTestResponse:
    """Test a stored tenant-level credential by calling the provider API."""
    await _check_tenant_access(tenant_id, current_user)
    db = get_database()

    cred = await db.fetch_one(
        """
        SELECT service_type, provider, encrypted_data
        FROM service_credentials
        WHERE id = :id
          AND entity_type = 'tenant'
          AND entity_id = :tenant_id
          AND is_active = TRUE
        """,
        {"id": credential_id, "tenant_id": str(tenant_id)},
    )

    if not cred:
        raise HTTPException(status_code=404, detail="Credential not found or not active")

    from app.utils.encryption import decrypt_credentials

    try:
        credentials = decrypt_credentials(cred["encrypted_data"])
    except Exception as e:
        logger.error(f"Failed to decrypt credentials: {e}")
        raise HTTPException(status_code=500, detail="Failed to decrypt credentials")

    creds_manager = CredentialsManager()
    result = await creds_manager.test_connection(
        service_type=cred["service_type"],
        provider=cred["provider"],
        credentials=credentials,
    )

    return CredentialTestResponse(**result)


@router.post("/projects/{project_id}/runtime/provision")
async def provision_project_runtime(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
):
    """
    Generate a standalone runtime instance (config + env + start script +
    systemd unit) for this project's voice engine, sourcing credentials from
    the project/tenant's CredentialsManager. Mirrors earlier-prototype's one-process-
    per-scenario model - does not install the systemd unit (no root from the
    app process); returns the exact commands to run.
    """
    await _check_project_access(project_id, current_user)

    db = get_database()
    project = await db.fetch_one(
        """
        SELECT id, tenant_id, slug, voice_engine, prompt_a, consent_message,
               voice_name, language, output_config
        FROM projects
        WHERE id = :id
        """,
        {"id": str(project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from app.services.runtime_provisioning import (
        RuntimeProvisioningError,
        provision_project_runtime as do_provision,
    )

    try:
        result = await do_provision(dict(project))
    except RuntimeProvisioningError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return result
