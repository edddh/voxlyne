"""
Ascolta - Credentials Management Router
M5.5: API endpoints for managing project-level service credentials
"""

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.database.db import get_database
from app.services.credentials.manager import CredentialsManager

logger = logging.getLogger(__name__)
router = APIRouter()


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
) -> CredentialResponse:
    """
    Create or update credentials for a project.

    The credentials are encrypted before storage.
    If credentials for the same service/provider/key exist, they will be updated.
    """
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
) -> CredentialListResponse:
    """
    List all credentials for a project (metadata only, NO sensitive data).

    Optionally filter by service_type.
    """
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
) -> Dict[str, Any]:
    """
    Delete credentials for a project (soft-delete by default).
    """
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
) -> CredentialTestResponse:
    """
    Test if credentials are valid by calling the provider API.
    """
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
) -> CredentialTestResponse:
    """
    Test credentials without saving them.

    Useful for validating credentials before creating a project credential.
    """
    creds_manager = CredentialsManager()
    result = await creds_manager.test_connection(
        service_type=request.service_type,
        provider=request.provider,
        credentials=request.data,
    )

    return CredentialTestResponse(**result)
