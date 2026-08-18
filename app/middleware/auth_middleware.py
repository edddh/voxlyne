"""
Ascolta - Authentication Middleware

FastAPI dependencies for JWT authentication and RBAC.
"""

import logging
from dataclasses import dataclass
from functools import wraps
from typing import Callable, List, Optional
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)

# HTTP Bearer scheme for JWT tokens
bearer_scheme = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    """Current authenticated user context."""

    id: UUID
    email: str
    role: str
    tenant_id: Optional[UUID] = None

    @property
    def is_super_admin(self) -> bool:
        """Check if user is super admin."""
        return self.role == "super_admin"

    @property
    def is_admin(self) -> bool:
        """Check if user is admin or higher."""
        return self.role in ("super_admin", "admin")

    @property
    def is_creator(self) -> bool:
        """Check if user can create/edit content."""
        return self.role in ("super_admin", "admin", "creator")

    @property
    def is_power_user(self) -> bool:
        """Check if user has power user access."""
        return self.role in ("super_admin", "admin", "creator", "power_user")

    def can_access_tenant(self, tenant_id: UUID) -> bool:
        """Check if user can access a specific tenant."""
        if self.is_super_admin:
            return True
        return self.tenant_id == tenant_id


class AuthMiddleware:
    """
    Authentication middleware for FastAPI.

    Validates JWT tokens and extracts user context.
    Also supports API key authentication.
    """

    def __init__(self):
        self.auth_service = AuthService()

    async def __call__(
        self,
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    ) -> Optional[CurrentUser]:
        """
        Extract and validate authentication from request.

        Supports:
        - Bearer token (JWT)
        - X-API-Key header (API key)

        Returns:
            CurrentUser if authenticated, None otherwise
        """
        # Try Bearer token first
        if credentials and credentials.scheme.lower() == "bearer":
            user_info = self.auth_service.validate_access_token(credentials.credentials)
            if user_info:
                return CurrentUser(
                    id=user_info["user_id"],
                    email=user_info["email"],
                    role=user_info["role"],
                    tenant_id=user_info.get("tenant_id"),
                )

        # Try API key
        api_key = request.headers.get("X-API-Key")
        if api_key:
            key_info = await self.auth_service.validate_api_key(api_key)
            if key_info:
                return CurrentUser(
                    id=key_info["id"],
                    email=f"api_key:{key_info['name']}",
                    role="api_key",
                    tenant_id=key_info.get("tenant_id"),
                )

        return None


# Singleton instance
_auth_middleware = AuthMiddleware()


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> CurrentUser:
    """
    FastAPI dependency to get the current authenticated user.

    Raises 401 if not authenticated.
    """
    user = await _auth_middleware(request, credentials)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Every non-super-admin role is expected to belong to exactly one
    # tenant. A user with tenant_id = NULL here isn't a valid "sees
    # nothing" state - every tenant-scoped query in the app builds its
    # WHERE clause from str(current_user.tenant_id), and str(None) is the
    # literal string "None", which Postgres rejects as an invalid UUID.
    # Without this check that surfaces as an opaque 500 on whatever screen
    # the user opens first (found live: this is exactly what produced
    # "errore caricamento utenti" on the Users page). Fail clearly here
    # instead, at the one place every authenticated request passes through.
    if not user.is_super_admin and user.tenant_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Questo account non è associato a nessun tenant. Contatta un amministratore.",
        )

    return user


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[CurrentUser]:
    """
    FastAPI dependency to get the current user if authenticated.

    Returns None if not authenticated (doesn't raise).
    """
    return await _auth_middleware(request, credentials)


def require_role(role: str):
    """
    Dependency factory to require a specific role.

    Usage:
        @router.get("/admin")
        async def admin_endpoint(user: CurrentUser = Depends(require_role("admin"))):
            ...
    """

    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.role != role and current_user.role != "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required",
            )
        return current_user

    return role_checker


def require_roles(roles: List[str]):
    """
    Dependency factory to require one of multiple roles.

    Usage:
        @router.get("/content")
        async def content_endpoint(user: CurrentUser = Depends(require_roles(["admin", "creator"]))):
            ...
    """

    async def roles_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.role not in roles and current_user.role != "super_admin":
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of roles {roles} required",
            )
        return current_user

    return roles_checker


def require_admin():
    """Dependency to require admin or super_admin role."""
    return require_roles(["admin", "super_admin"])


def require_creator():
    """Dependency to require creator or higher role."""
    return require_roles(["admin", "super_admin", "creator"])


def require_power_user():
    """Dependency to require power_user or higher role."""
    return require_roles(["admin", "super_admin", "creator", "power_user"])


def require_super_admin():
    """Dependency to require super_admin role."""
    return require_role("super_admin")


class TenantContext:
    """
    Context for tenant-scoped operations.

    Provides tenant isolation for database queries.
    """

    def __init__(self, user: CurrentUser):
        self.user = user

    @property
    def tenant_id(self) -> Optional[UUID]:
        """Get tenant ID for queries."""
        if self.user.is_super_admin:
            return None  # Super admin sees all tenants
        return self.user.tenant_id

    def filter_query(self, base_query: str, table_alias: str = "") -> str:
        """
        Add tenant filter to a SQL query.

        Args:
            base_query: Base SQL query
            table_alias: Table alias (e.g., "p." for projects table)

        Returns:
            Query with tenant filter added
        """
        if self.user.is_super_admin:
            return base_query

        prefix = f"{table_alias}." if table_alias else ""
        return f"{base_query} AND {prefix}tenant_id = :tenant_id"

    @property
    def query_params(self) -> dict:
        """Get query parameters including tenant_id if needed."""
        if self.user.is_super_admin:
            return {}
        return {"tenant_id": str(self.tenant_id)}


async def get_tenant_context(
    current_user: CurrentUser = Depends(get_current_user),
) -> TenantContext:
    """
    FastAPI dependency to get tenant context for the current user.
    """
    return TenantContext(current_user)


def check_tenant_access(user: CurrentUser, resource_tenant_id: Optional[UUID]) -> bool:
    """
    Check if user can access a resource in a specific tenant.

    Args:
        user: Current user
        resource_tenant_id: Tenant ID of the resource

    Returns:
        True if access is allowed
    """
    if user.is_super_admin:
        return True

    if resource_tenant_id is None:
        # Resource has no tenant - only super_admin can access
        return False

    return user.tenant_id == resource_tenant_id


def require_tenant_access(resource_tenant_id: Optional[UUID]):
    """
    Decorator/dependency to check tenant access for a resource.

    Args:
        resource_tenant_id: Tenant ID to check access for

    Raises:
        HTTPException 403 if access denied
    """

    async def checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if not check_tenant_access(current_user, resource_tenant_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied to this tenant's resources",
            )
        return current_user

    return checker
