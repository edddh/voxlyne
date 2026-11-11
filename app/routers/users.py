"""
Voxlyne - Users API Routes

CRUD operations for user management.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.database.db import get_database
from app.middleware.auth_middleware import (
    CurrentUser,
    TenantContext,
    get_current_user,
    get_tenant_context,
    require_roles,
)
from app.models.schemas import (
    PasswordResetRequest,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserRole,
    UserUpdate,
)
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["Users"])


@router.get("", response_model=UserListResponse)
async def list_users(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: Optional[str] = None,
    role: Optional[UserRole] = None,
    is_active: Optional[bool] = None,
    tenant_id: Optional[UUID] = None,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    List users with optional filters.

    - Super admin can see all users and filter by tenant
    - Admin can only see users in their tenant
    """
    db = get_database()

    # Build query
    base_query = """
        SELECT u.id, u.tenant_id, u.email, u.full_name, u.role,
               u.is_active, u.email_verified, u.avatar_url,
               u.last_login_at, u.created_at,
               t.name as tenant_name, t.slug as tenant_slug
        FROM users u
        LEFT JOIN tenants t ON u.tenant_id = t.id
        WHERE 1=1
    """
    count_query = "SELECT COUNT(*) FROM users u WHERE 1=1"

    params = {}

    # Tenant filter
    if current_user.is_super_admin:
        if tenant_id:
            base_query += " AND u.tenant_id = :filter_tenant_id"
            count_query += " AND u.tenant_id = :filter_tenant_id"
            params["filter_tenant_id"] = str(tenant_id)
    else:
        # Non-super-admin can only see their tenant
        base_query += " AND u.tenant_id = :tenant_id"
        count_query += " AND u.tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    # Search filter
    if search:
        base_query += " AND (u.email ILIKE :search OR u.full_name ILIKE :search)"
        count_query += " AND (u.email ILIKE :search OR u.full_name ILIKE :search)"
        params["search"] = f"%{search}%"

    # Role filter
    if role:
        base_query += " AND u.role = :role"
        count_query += " AND u.role = :role"
        params["role"] = role.value

    # Active filter
    if is_active is not None:
        base_query += " AND u.is_active = :is_active"
        count_query += " AND u.is_active = :is_active"
        params["is_active"] = is_active

    # Pagination
    offset = (page - 1) * page_size
    base_query += " ORDER BY u.created_at DESC LIMIT :limit OFFSET :offset"
    params["limit"] = page_size
    params["offset"] = offset

    # Execute queries
    users = await db.fetch_all(base_query, params)
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    total_result = await db.fetch_one(count_query, count_params)
    total = total_result[0] if total_result else 0

    return UserListResponse(
        users=[
            UserResponse(
                id=UUID(str(u["id"])),
                tenant_id=UUID(str(u["tenant_id"])) if u["tenant_id"] else None,
                email=u["email"],
                full_name=u["full_name"],
                role=UserRole(u["role"]),
                is_active=u["is_active"],
                email_verified=u["email_verified"],
                avatar_url=u["avatar_url"],
                last_login_at=u["last_login_at"],
                created_at=u["created_at"],
                tenant_name=u["tenant_name"],
                tenant_slug=u["tenant_slug"],
            )
            for u in users
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    user_data: UserCreate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
):
    """
    Create a new user.

    - Super admin can create users in any tenant
    - Admin can only create users in their own tenant
    """
    db = get_database()
    auth_service = AuthService()

    # Validate tenant access
    target_tenant_id = user_data.tenant_id

    if not current_user.is_super_admin:
        # Admin must create users in their own tenant
        target_tenant_id = current_user.tenant_id

    # Check if email already exists
    existing = await db.fetch_one(
        "SELECT id FROM users WHERE email = :email",
        {"email": user_data.email.lower()},
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User with this email already exists",
        )

    # Only super_admin can create super_admin users
    if user_data.role == UserRole.SUPER_ADMIN and not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admin can create super admin users",
        )

    # Hash password
    password_hash = auth_service.hash_password(user_data.password)

    # Insert user
    result = await db.fetch_one(
        """
        INSERT INTO users (tenant_id, email, password_hash, full_name, role, is_active)
        VALUES (:tenant_id, :email, :password_hash, :full_name, :role, TRUE)
        RETURNING id, created_at
        """,
        {
            "tenant_id": str(target_tenant_id) if target_tenant_id else None,
            "email": user_data.email.lower(),
            "password_hash": password_hash,
            "full_name": user_data.full_name,
            "role": user_data.role.value,
        },
    )

    # Get tenant info
    tenant_info = None
    if target_tenant_id:
        tenant_info = await db.fetch_one(
            "SELECT name, slug FROM tenants WHERE id = :id",
            {"id": str(target_tenant_id)},
        )

    logger.info(f"User created: {user_data.email} by {current_user.email}")

    return UserResponse(
        id=UUID(str(result["id"])),
        tenant_id=target_tenant_id,
        email=user_data.email.lower(),
        full_name=user_data.full_name,
        role=user_data.role,
        is_active=True,
        email_verified=False,
        created_at=result["created_at"],
        tenant_name=tenant_info["name"] if tenant_info else None,
        tenant_slug=tenant_info["slug"] if tenant_info else None,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
):
    """
    Get user by ID.
    """
    db = get_database()

    query = """
        SELECT u.id, u.tenant_id, u.email, u.full_name, u.role,
               u.is_active, u.email_verified, u.avatar_url,
               u.last_login_at, u.created_at,
               t.name as tenant_name, t.slug as tenant_slug
        FROM users u
        LEFT JOIN tenants t ON u.tenant_id = t.id
        WHERE u.id = :user_id
    """
    params = {"user_id": str(user_id)}

    # Non-super-admin can only see users in their tenant
    if not current_user.is_super_admin:
        query += " AND u.tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    user = await db.fetch_one(query, params)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(
        id=UUID(str(user["id"])),
        tenant_id=UUID(str(user["tenant_id"])) if user["tenant_id"] else None,
        email=user["email"],
        full_name=user["full_name"],
        role=UserRole(user["role"]),
        is_active=user["is_active"],
        email_verified=user["email_verified"],
        avatar_url=user["avatar_url"],
        last_login_at=user["last_login_at"],
        created_at=user["created_at"],
        tenant_name=user["tenant_name"],
        tenant_slug=user["tenant_slug"],
    )


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    user_data: UserUpdate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
):
    """
    Update a user.
    """
    db = get_database()
    auth_service = AuthService()

    # Check user exists and get current data
    query = "SELECT * FROM users WHERE id = :user_id"
    params = {"user_id": str(user_id)}

    if not current_user.is_super_admin:
        query += " AND tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    user = await db.fetch_one(query, params)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Prevent demoting yourself
    if user_id == current_user.id and user_data.role and user_data.role.value != user["role"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot change your own role",
        )

    # Only super_admin can promote to super_admin
    if user_data.role == UserRole.SUPER_ADMIN and not current_user.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super admin can promote to super admin",
        )

    # Build update
    update_fields = []
    update_params = {"user_id": str(user_id)}

    if user_data.email is not None:
        # Check email uniqueness
        existing = await db.fetch_one(
            "SELECT id FROM users WHERE email = :email AND id != :user_id",
            {"email": user_data.email.lower(), "user_id": str(user_id)},
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already in use",
            )
        update_fields.append("email = :email")
        update_params["email"] = user_data.email.lower()

    if user_data.full_name is not None:
        update_fields.append("full_name = :full_name")
        update_params["full_name"] = user_data.full_name

    if user_data.role is not None:
        update_fields.append("role = :role")
        update_params["role"] = user_data.role.value

    if user_data.is_active is not None:
        update_fields.append("is_active = :is_active")
        update_params["is_active"] = user_data.is_active

    if user_data.password is not None:
        update_fields.append("password_hash = :password_hash")
        update_params["password_hash"] = auth_service.hash_password(user_data.password)

    if not update_fields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update",
        )

    update_fields.append("updated_at = :updated_at")
    update_params["updated_at"] = datetime.now(timezone.utc)

    await db.execute(
        f"UPDATE users SET {', '.join(update_fields)} WHERE id = :user_id",
        update_params,
    )

    logger.info(f"User updated: {user_id} by {current_user.email}")

    # Return updated user
    return await get_user(user_id, current_user)


@router.delete("/{user_id}")
async def delete_user(
    user_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
):
    """
    Deactivate a user (soft delete).
    """
    db = get_database()

    # Cannot delete yourself
    if user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete yourself",
        )

    # Check user exists
    query = "SELECT id, tenant_id FROM users WHERE id = :user_id"
    params = {"user_id": str(user_id)}

    if not current_user.is_super_admin:
        query += " AND tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    user = await db.fetch_one(query, params)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Soft delete (deactivate)
    await db.execute(
        "UPDATE users SET is_active = FALSE, updated_at = :updated_at WHERE id = :user_id",
        {"updated_at": datetime.now(timezone.utc), "user_id": str(user_id)},
    )

    # Revoke all tokens
    auth_service = AuthService()
    await auth_service.revoke_all_user_tokens(user_id)

    logger.info(f"User deactivated: {user_id} by {current_user.email}")

    return {"success": True, "message": "User deactivated"}


@router.post("/{user_id}/reset-password")
async def reset_user_password(
    user_id: UUID,
    password_data: PasswordResetRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin"])),
):
    """
    Reset a user's password (admin action).
    """
    db = get_database()
    auth_service = AuthService()

    # Check user exists
    query = "SELECT id, email, tenant_id FROM users WHERE id = :user_id"
    params = {"user_id": str(user_id)}

    if not current_user.is_super_admin:
        query += " AND tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    user = await db.fetch_one(query, params)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Hash new password
    password_hash = auth_service.hash_password(password_data.new_password)

    # Update password
    await db.execute(
        "UPDATE users SET password_hash = :hash, updated_at = :updated_at WHERE id = :user_id",
        {
            "hash": password_hash,
            "updated_at": datetime.now(timezone.utc),
            "user_id": str(user_id),
        },
    )

    # Revoke all tokens
    await auth_service.revoke_all_user_tokens(user_id)

    logger.info(f"Password reset for user {user_id} by {current_user.email}")

    return {"success": True, "message": "Password reset successfully"}
