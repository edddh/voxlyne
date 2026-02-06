"""
Ascolta - Tenants API Routes

CRUD operations for tenant management (super_admin only).
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database.db import get_database
from app.middleware.auth_middleware import (
    CurrentUser,
    require_super_admin,
)
from app.models.schemas import (
    TenantCreate,
    TenantListResponse,
    TenantResponse,
    TenantUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/tenants", tags=["Tenants"])


@router.get("", response_model=TenantListResponse)
async def list_tenants(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    is_active: Optional[bool] = None,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    List all tenants (super_admin only).
    """
    db = get_database()

    # Build query
    base_query = """
        SELECT t.*,
               (SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.id) as user_count,
               (SELECT COUNT(*) FROM projects p WHERE p.tenant_id = t.id) as project_count
        FROM tenants t
        WHERE 1=1
    """
    count_query = "SELECT COUNT(*) FROM tenants WHERE 1=1"

    params = {}

    # Search filter
    if search:
        base_query += " AND (t.name ILIKE :search OR t.slug ILIKE :search)"
        count_query += " AND (name ILIKE :search OR slug ILIKE :search)"
        params["search"] = f"%{search}%"

    # Active filter
    if is_active is not None:
        base_query += " AND t.is_active = :is_active"
        count_query += " AND is_active = :is_active"
        params["is_active"] = is_active

    # Pagination
    offset = (page - 1) * page_size
    base_query += " ORDER BY t.created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = page_size
    params["offset"] = offset

    # Execute queries
    tenants = await db.fetch_all(base_query, params)
    total_result = await db.fetch_one(count_query, params)
    total = total_result[0] if total_result else 0

    return TenantListResponse(
        tenants=[
            TenantResponse(
                id=UUID(str(t["id"])),
                name=t["name"],
                slug=t["slug"],
                is_active=t["is_active"],
                settings=t["settings"] or {},
                created_at=t["created_at"],
                updated_at=t["updated_at"],
                user_count=t["user_count"],
                project_count=t["project_count"],
            )
            for t in tenants
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=TenantResponse, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    tenant_data: TenantCreate,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    Create a new tenant (super_admin only).
    """
    db = get_database()

    # Check if slug already exists
    existing = await db.fetch_one(
        "SELECT id FROM tenants WHERE slug = :slug",
        {"slug": tenant_data.slug},
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Tenant with this slug already exists",
        )

    # Insert tenant
    result = await db.fetch_one(
        """
        INSERT INTO tenants (name, slug, settings, is_active)
        VALUES (:name, :slug, :settings, TRUE)
        RETURNING id, created_at, updated_at
        """,
        {
            "name": tenant_data.name,
            "slug": tenant_data.slug,
            "settings": tenant_data.settings,
        },
    )

    logger.info(f"Tenant created: {tenant_data.slug} by {current_user.email}")

    return TenantResponse(
        id=UUID(str(result["id"])),
        name=tenant_data.name,
        slug=tenant_data.slug,
        is_active=True,
        settings=tenant_data.settings,
        created_at=result["created_at"],
        updated_at=result["updated_at"],
        user_count=0,
        project_count=0,
    )


@router.get("/{tenant_id}", response_model=TenantResponse)
async def get_tenant(
    tenant_id: UUID,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    Get tenant by ID (super_admin only).
    """
    db = get_database()

    tenant = await db.fetch_one(
        """
        SELECT t.*,
               (SELECT COUNT(*) FROM users u WHERE u.tenant_id = t.id) as user_count,
               (SELECT COUNT(*) FROM projects p WHERE p.tenant_id = t.id) as project_count
        FROM tenants t
        WHERE t.id = :tenant_id
        """,
        {"tenant_id": str(tenant_id)},
    )

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    return TenantResponse(
        id=UUID(str(tenant["id"])),
        name=tenant["name"],
        slug=tenant["slug"],
        is_active=tenant["is_active"],
        settings=tenant["settings"] or {},
        created_at=tenant["created_at"],
        updated_at=tenant["updated_at"],
        user_count=tenant["user_count"],
        project_count=tenant["project_count"],
    )


@router.patch("/{tenant_id}", response_model=TenantResponse)
async def update_tenant(
    tenant_id: UUID,
    tenant_data: TenantUpdate,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    Update a tenant (super_admin only).
    """
    db = get_database()

    # Check tenant exists
    tenant = await db.fetch_one(
        "SELECT * FROM tenants WHERE id = :tenant_id",
        {"tenant_id": str(tenant_id)},
    )

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    # Build update
    update_fields = []
    update_params = {"tenant_id": str(tenant_id)}

    if tenant_data.name is not None:
        update_fields.append("name = :name")
        update_params["name"] = tenant_data.name

    if tenant_data.is_active is not None:
        update_fields.append("is_active = :is_active")
        update_params["is_active"] = tenant_data.is_active

    if tenant_data.settings is not None:
        update_fields.append("settings = :settings")
        update_params["settings"] = tenant_data.settings

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    update_fields.append("updated_at = :updated_at")
    update_params["updated_at"] = datetime.now(timezone.utc)

    await db.execute(
        f"UPDATE tenants SET {', '.join(update_fields)} WHERE id = :tenant_id",
        update_params,
    )

    logger.info(f"Tenant updated: {tenant_id} by {current_user.email}")

    # Return updated tenant
    return await get_tenant(tenant_id, current_user)


@router.delete("/{tenant_id}")
async def delete_tenant(
    tenant_id: UUID,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    Deactivate a tenant (soft delete, super_admin only).

    This will also deactivate all users in the tenant.
    """
    db = get_database()

    # Check tenant exists
    tenant = await db.fetch_one(
        "SELECT id, slug FROM tenants WHERE id = :tenant_id",
        {"tenant_id": str(tenant_id)},
    )

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    # Prevent deleting the default tenant
    if tenant["slug"] == "default":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete the default tenant",
        )

    now = datetime.now(timezone.utc)

    # Soft delete tenant
    await db.execute(
        "UPDATE tenants SET is_active = FALSE, updated_at = :updated_at WHERE id = :tenant_id",
        {"updated_at": now, "tenant_id": str(tenant_id)},
    )

    # Deactivate all users in tenant
    await db.execute(
        "UPDATE users SET is_active = FALSE, updated_at = :updated_at WHERE tenant_id = :tenant_id",
        {"updated_at": now, "tenant_id": str(tenant_id)},
    )

    # Deactivate all projects in tenant
    await db.execute(
        "UPDATE projects SET is_active = FALSE, updated_at = :updated_at WHERE tenant_id = :tenant_id",
        {"updated_at": now, "tenant_id": str(tenant_id)},
    )

    logger.info(f"Tenant deactivated: {tenant_id} by {current_user.email}")

    return {"success": True, "message": "Tenant and all associated resources deactivated"}


@router.get("/{tenant_id}/users")
async def list_tenant_users(
    tenant_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    List users in a specific tenant (super_admin only).
    """
    db = get_database()

    # Check tenant exists
    tenant = await db.fetch_one(
        "SELECT id FROM tenants WHERE id = :tenant_id",
        {"tenant_id": str(tenant_id)},
    )

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    offset = (page - 1) * page_size

    users = await db.fetch_all(
        """
        SELECT id, email, full_name, role, is_active, created_at
        FROM users
        WHERE tenant_id = :tenant_id
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        {"tenant_id": str(tenant_id), "limit": page_size, "offset": offset},
    )

    total_result = await db.fetch_one(
        "SELECT COUNT(*) FROM users WHERE tenant_id = :tenant_id",
        {"tenant_id": str(tenant_id)},
    )
    total = total_result[0] if total_result else 0

    return {
        "users": [
            {
                "id": str(u["id"]),
                "email": u["email"],
                "full_name": u["full_name"],
                "role": u["role"],
                "is_active": u["is_active"],
                "created_at": u["created_at"],
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{tenant_id}/projects")
async def list_tenant_projects(
    tenant_id: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    List projects in a specific tenant (super_admin only).
    """
    db = get_database()

    # Check tenant exists
    tenant = await db.fetch_one(
        "SELECT id FROM tenants WHERE id = :tenant_id",
        {"tenant_id": str(tenant_id)},
    )

    if not tenant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Tenant not found",
        )

    offset = (page - 1) * page_size

    projects = await db.fetch_all(
        """
        SELECT id, name, slug, type, is_active, created_at
        FROM projects
        WHERE tenant_id = :tenant_id
        ORDER BY created_at DESC
        LIMIT :limit OFFSET :offset
        """,
        {"tenant_id": str(tenant_id), "limit": page_size, "offset": offset},
    )

    total_result = await db.fetch_one(
        "SELECT COUNT(*) FROM projects WHERE tenant_id = :tenant_id",
        {"tenant_id": str(tenant_id)},
    )
    total = total_result[0] if total_result else 0

    return {
        "projects": [
            {
                "id": str(p["id"]),
                "name": p["name"],
                "slug": p["slug"],
                "type": p["type"],
                "is_active": p["is_active"],
                "created_at": p["created_at"],
            }
            for p in projects
        ],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
