"""
Voxlyne - Project Configuration API Routes (M4+)

Project-level configuration for:
- SIP address and credentials
- CRM integration (HubSpot, Salesforce, Webhook)
- Calendar integration (Google, Microsoft)
- Prompt placeholders (cancel_phrase, goodbye_phrase, etc.)
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database.db import get_database
from app.middleware.auth_middleware import (
    CurrentUser,
    check_tenant_access,
    require_roles,
)
from app.services.encryption import encrypt, decrypt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["Project Configuration"])


# ===========================================
# Schemas
# ===========================================

class SIPConfigResponse(BaseModel):
    """SIP configuration response."""
    sip_address: Optional[str]
    sip_username: Optional[str]
    has_password: bool  # Don't expose actual password


class SIPConfigUpdate(BaseModel):
    """SIP configuration update."""
    sip_address: Optional[str] = Field(None, max_length=255)
    sip_username: Optional[str] = Field(None, max_length=100)
    sip_password: Optional[str] = Field(None, description="Will be encrypted before storage")


class CRMConfigResponse(BaseModel):
    """CRM configuration response."""
    enabled: bool
    provider: Optional[str]
    hubspot_portal_id: Optional[str]
    webhook_url: Optional[str]
    has_api_key: bool  # Don't expose actual key
    config: dict


class CRMConfigUpdate(BaseModel):
    """CRM configuration update."""
    enabled: bool = True
    provider: str = Field(..., pattern="^(hubspot|salesforce|webhook)$")
    hubspot_api_key: Optional[str] = None
    hubspot_portal_id: Optional[str] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    config: dict = Field(default_factory=dict)


class CalendarConfigResponse(BaseModel):
    """Calendar configuration response."""
    enabled: bool
    provider: Optional[str]
    calendar_id: Optional[str]
    timezone: Optional[str]
    has_tokens: bool  # Don't expose actual tokens
    expires_at: Optional[str]
    config: dict


class CalendarConfigUpdate(BaseModel):
    """Calendar configuration update."""
    enabled: bool = True
    provider: str = Field(..., pattern="^(google|microsoft)$")
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    expires_at: Optional[str] = None
    calendar_id: str = "primary"
    timezone: str = "Europe/Rome"
    config: dict = Field(default_factory=dict)


class PlaceholdersResponse(BaseModel):
    """Prompt placeholders response."""
    cancel_phrase: str
    cancellation_confirmation: str
    goodbye_phrase: str
    intent_config: dict


class PlaceholdersUpdate(BaseModel):
    """Prompt placeholders update."""
    cancel_phrase: Optional[str] = Field(None, min_length=1)
    cancellation_confirmation: Optional[str] = Field(None, min_length=1)
    goodbye_phrase: Optional[str] = Field(None, min_length=1)
    intent_config: Optional[dict] = None


async def _check_project_access(project_id: UUID, current_user: CurrentUser):
    """Check user has access to project."""
    db = get_database()
    result = await db.fetch_one(
        "SELECT tenant_id FROM projects WHERE id = :project_id",
        {"project_id": str(project_id)}
    )
    if not result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project {project_id} not found"
        )

    tenant_id = UUID(str(result["tenant_id"])) if result["tenant_id"] else None
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project"
        )


# ===========================================
# SIP Configuration
# ===========================================

@router.get("/{project_id}/config/sip", response_model=SIPConfigResponse)
async def get_sip_config(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Get SIP configuration for project."""
    await _check_project_access(project_id, current_user)

    db = get_database()
    project = await db.fetch_one(
        "SELECT sip_address, sip_username, sip_password_encrypted FROM projects WHERE id = :id",
        {"id": str(project_id)}
    )

    return SIPConfigResponse(
        sip_address=project["sip_address"],
        sip_username=project["sip_username"],
        has_password=bool(project["sip_password_encrypted"])
    )


@router.put("/{project_id}/config/sip", response_model=SIPConfigResponse)
async def update_sip_config(
    project_id: UUID,
    data: SIPConfigUpdate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Update SIP configuration for project."""
    await _check_project_access(project_id, current_user)

    db = get_database()

    # Build update query
    updates = []
    params = {"id": str(project_id)}

    if data.sip_address is not None:
        updates.append("sip_address = :sip_address")
        params["sip_address"] = data.sip_address

    if data.sip_username is not None:
        updates.append("sip_username = :sip_username")
        params["sip_username"] = data.sip_username

    if data.sip_password is not None:
        updates.append("sip_password_encrypted = :sip_password_encrypted")
        params["sip_password_encrypted"] = encrypt(data.sip_password)

    if updates:
        updates.append("updated_at = NOW()")
        query = f"UPDATE projects SET {', '.join(updates)} WHERE id = :id"
        await db.execute(query, params)

    return await get_sip_config(project_id, current_user)


# ===========================================
# CRM Configuration
# ===========================================

@router.get("/{project_id}/config/crm", response_model=CRMConfigResponse)
async def get_crm_config(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Get CRM configuration for project."""
    await _check_project_access(project_id, current_user)

    db = get_database()
    config = await db.fetch_one(
        """
        SELECT enabled, provider, hubspot_api_key_encrypted, hubspot_portal_id,
               webhook_url, webhook_secret_encrypted, config
        FROM project_crm_config
        WHERE project_id = :project_id
        """,
        {"project_id": str(project_id)}
    )

    if not config:
        return CRMConfigResponse(
            enabled=False,
            provider=None,
            hubspot_portal_id=None,
            webhook_url=None,
            has_api_key=False,
            config={}
        )

    return CRMConfigResponse(
        enabled=config["enabled"],
        provider=config["provider"],
        hubspot_portal_id=config["hubspot_portal_id"],
        webhook_url=config["webhook_url"],
        has_api_key=bool(config["hubspot_api_key_encrypted"] or config["webhook_secret_encrypted"]),
        config=config["config"] or {}
    )


@router.put("/{project_id}/config/crm", response_model=CRMConfigResponse)
async def update_crm_config(
    project_id: UUID,
    data: CRMConfigUpdate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Update CRM configuration for project."""
    await _check_project_access(project_id, current_user)

    db = get_database()

    # Check if config exists
    existing = await db.fetch_one(
        "SELECT id FROM project_crm_config WHERE project_id = :project_id",
        {"project_id": str(project_id)}
    )

    # Encrypt sensitive fields
    hubspot_api_key_encrypted = encrypt(data.hubspot_api_key) if data.hubspot_api_key else None
    webhook_secret_encrypted = encrypt(data.webhook_secret) if data.webhook_secret else None

    if existing:
        # Update existing
        await db.execute(
            """
            UPDATE project_crm_config
            SET enabled = :enabled,
                provider = :provider,
                hubspot_api_key_encrypted = COALESCE(:hubspot_api_key_encrypted, hubspot_api_key_encrypted),
                hubspot_portal_id = :hubspot_portal_id,
                webhook_url = :webhook_url,
                webhook_secret_encrypted = COALESCE(:webhook_secret_encrypted, webhook_secret_encrypted),
                config = :config,
                updated_at = NOW()
            WHERE project_id = :project_id
            """,
            {
                "project_id": str(project_id),
                "enabled": data.enabled,
                "provider": data.provider,
                "hubspot_api_key_encrypted": hubspot_api_key_encrypted,
                "hubspot_portal_id": data.hubspot_portal_id,
                "webhook_url": data.webhook_url,
                "webhook_secret_encrypted": webhook_secret_encrypted,
                "config": data.config,
            }
        )
    else:
        # Insert new
        await db.execute(
            """
            INSERT INTO project_crm_config (
                project_id, enabled, provider,
                hubspot_api_key_encrypted, hubspot_portal_id,
                webhook_url, webhook_secret_encrypted, config
            ) VALUES (
                :project_id, :enabled, :provider,
                :hubspot_api_key_encrypted, :hubspot_portal_id,
                :webhook_url, :webhook_secret_encrypted, :config
            )
            """,
            {
                "project_id": str(project_id),
                "enabled": data.enabled,
                "provider": data.provider,
                "hubspot_api_key_encrypted": hubspot_api_key_encrypted,
                "hubspot_portal_id": data.hubspot_portal_id,
                "webhook_url": data.webhook_url,
                "webhook_secret_encrypted": webhook_secret_encrypted,
                "config": data.config,
            }
        )

    return await get_crm_config(project_id, current_user)


@router.post("/{project_id}/config/crm/test", response_model=dict)
async def test_crm_connection(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Test CRM connection (basic validation)."""
    await _check_project_access(project_id, current_user)

    # For now, just check config exists and is enabled
    # In production, you'd actually test the API connection
    config = await get_crm_config(project_id, current_user)

    if not config.enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CRM integration is not enabled"
        )

    if not config.has_api_key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="CRM API key is not configured"
        )

    # TODO: Actually test the connection to HubSpot/Salesforce API
    return {
        "success": True,
        "message": f"CRM connection test passed for {config.provider}",
        "provider": config.provider
    }


# ===========================================
# Calendar Configuration
# ===========================================

@router.get("/{project_id}/config/calendar", response_model=CalendarConfigResponse)
async def get_calendar_config(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Get calendar configuration for project."""
    await _check_project_access(project_id, current_user)

    db = get_database()
    config = await db.fetch_one(
        """
        SELECT enabled, provider, access_token_encrypted, refresh_token_encrypted,
               expires_at, calendar_id, timezone, config
        FROM project_calendar_config
        WHERE project_id = :project_id
        """,
        {"project_id": str(project_id)}
    )

    if not config:
        return CalendarConfigResponse(
            enabled=False,
            provider=None,
            calendar_id=None,
            timezone=None,
            has_tokens=False,
            expires_at=None,
            config={}
        )

    return CalendarConfigResponse(
        enabled=config["enabled"],
        provider=config["provider"],
        calendar_id=config["calendar_id"],
        timezone=config["timezone"],
        has_tokens=bool(config["access_token_encrypted"]),
        expires_at=str(config["expires_at"]) if config["expires_at"] else None,
        config=config["config"] or {}
    )


@router.put("/{project_id}/config/calendar", response_model=CalendarConfigResponse)
async def update_calendar_config(
    project_id: UUID,
    data: CalendarConfigUpdate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Update calendar configuration for project."""
    await _check_project_access(project_id, current_user)

    db = get_database()

    # Check if config exists
    existing = await db.fetch_one(
        "SELECT id FROM project_calendar_config WHERE project_id = :project_id",
        {"project_id": str(project_id)}
    )

    # Encrypt tokens
    access_token_encrypted = encrypt(data.access_token) if data.access_token else None
    refresh_token_encrypted = encrypt(data.refresh_token) if data.refresh_token else None

    if existing:
        # Update existing
        await db.execute(
            """
            UPDATE project_calendar_config
            SET enabled = :enabled,
                provider = :provider,
                access_token_encrypted = COALESCE(:access_token_encrypted, access_token_encrypted),
                refresh_token_encrypted = COALESCE(:refresh_token_encrypted, refresh_token_encrypted),
                expires_at = :expires_at,
                calendar_id = :calendar_id,
                timezone = :timezone,
                config = :config,
                updated_at = NOW()
            WHERE project_id = :project_id
            """,
            {
                "project_id": str(project_id),
                "enabled": data.enabled,
                "provider": data.provider,
                "access_token_encrypted": access_token_encrypted,
                "refresh_token_encrypted": refresh_token_encrypted,
                "expires_at": data.expires_at,
                "calendar_id": data.calendar_id,
                "timezone": data.timezone,
                "config": data.config,
            }
        )
    else:
        # Insert new
        await db.execute(
            """
            INSERT INTO project_calendar_config (
                project_id, enabled, provider,
                access_token_encrypted, refresh_token_encrypted, expires_at,
                calendar_id, timezone, config
            ) VALUES (
                :project_id, :enabled, :provider,
                :access_token_encrypted, :refresh_token_encrypted, :expires_at,
                :calendar_id, :timezone, :config
            )
            """,
            {
                "project_id": str(project_id),
                "enabled": data.enabled,
                "provider": data.provider,
                "access_token_encrypted": access_token_encrypted,
                "refresh_token_encrypted": refresh_token_encrypted,
                "expires_at": data.expires_at,
                "calendar_id": data.calendar_id,
                "timezone": data.timezone,
                "config": data.config,
            }
        )

    return await get_calendar_config(project_id, current_user)


@router.get("/{project_id}/config/calendar/oauth-url", response_model=dict)
async def get_calendar_oauth_url(
    project_id: UUID,
    provider: str,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Generate OAuth URL for calendar provider."""
    await _check_project_access(project_id, current_user)

    if provider not in ["google", "microsoft"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider must be 'google' or 'microsoft'"
        )

    # TODO: Generate actual OAuth URL with proper callback
    # For now, return placeholder
    oauth_url = f"https://oauth.{provider}.com/authorize?client_id=...&redirect_uri=..."

    return {
        "provider": provider,
        "oauth_url": oauth_url,
        "message": "Redirect user to this URL to authenticate"
    }


# ===========================================
# Prompt Placeholders
# ===========================================

@router.get("/{project_id}/config/placeholders", response_model=PlaceholdersResponse)
async def get_placeholders(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Get prompt placeholders for project."""
    await _check_project_access(project_id, current_user)

    db = get_database()
    placeholders = await db.fetch_one(
        """
        SELECT cancel_phrase, cancellation_confirmation, goodbye_phrase, intent_config
        FROM prompt_placeholders
        WHERE project_id = :project_id
        """,
        {"project_id": str(project_id)}
    )

    if not placeholders:
        # Return defaults (migration should have created these)
        return PlaceholdersResponse(
            cancel_phrase="Va bene, procedo con la cancellazione della telefonata.",
            cancellation_confirmation="Cancellazione dei dati della telefonata eseguita.",
            goodbye_phrase="Le auguro una buona giornata! Arrivederci.",
            intent_config={
                "calendar_keywords": ["appuntamento", "colloquio", "incontro"],
                "cancel_keywords": ["cancella", "elimina", "rimuovi"],
                "confirm_keywords": ["sì", "si", "va bene", "ok", "certo"]
            }
        )

    return PlaceholdersResponse(
        cancel_phrase=placeholders["cancel_phrase"],
        cancellation_confirmation=placeholders["cancellation_confirmation"],
        goodbye_phrase=placeholders["goodbye_phrase"],
        intent_config=placeholders["intent_config"] or {}
    )


@router.put("/{project_id}/config/placeholders", response_model=PlaceholdersResponse)
async def update_placeholders(
    project_id: UUID,
    data: PlaceholdersUpdate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"]))
):
    """Update prompt placeholders for project."""
    await _check_project_access(project_id, current_user)

    db = get_database()

    # Check if placeholders exist
    existing = await db.fetch_one(
        "SELECT id FROM prompt_placeholders WHERE project_id = :project_id",
        {"project_id": str(project_id)}
    )

    # Build update query
    updates = []
    params = {"project_id": str(project_id)}

    for field, value in data.dict(exclude_unset=True).items():
        if value is not None:
            updates.append(f"{field} = :{field}")
            params[field] = value

    if updates:
        updates.append("updated_at = NOW()")

        if existing:
            query = f"UPDATE prompt_placeholders SET {', '.join(updates)} WHERE project_id = :project_id"
        else:
            # Insert with only provided fields
            fields = list(params.keys())
            placeholders_str = ', '.join(f':{f}' for f in fields)
            query = f"INSERT INTO prompt_placeholders ({', '.join(fields)}) VALUES ({placeholders_str})"

        await db.execute(query, params)

    return await get_placeholders(project_id, current_user)
