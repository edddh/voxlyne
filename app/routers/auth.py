"""
Ascolta - Authentication API Routes

JWT login, token refresh, logout, and user info.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status

from app.config import get_settings
from app.middleware.auth_middleware import CurrentUser, get_current_user_rls_scoped
from app.models.schemas import (
    LoginRequest,
    LoginResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    UserResponse,
    UserRole,
)
from app.services.auth_service import AuthService

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=LoginResponse)
async def login(
    request: Request,
    login_data: LoginRequest,
):
    """
    Authenticate user and return JWT tokens.

    Returns access token (short-lived) and refresh token (long-lived).
    """
    auth_service = AuthService()

    # Authenticate user
    user = await auth_service.authenticate_user(
        email=login_data.email.lower(),
        password=login_data.password,
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    # Check if user can access admin UI (not regular "user" role)
    if user["role"] == "user":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User role cannot access admin panel",
        )

    # Create tokens
    access_token = auth_service.create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        tenant_id=user.get("tenant_id"),
    )

    refresh_token, expires_at = auth_service.create_refresh_token(user_id=user["id"])

    # Store refresh token
    await auth_service.store_refresh_token(
        user_id=user["id"],
        token=refresh_token,
        expires_at=expires_at,
        user_agent=request.headers.get("User-Agent"),
        ip_address=request.client.host if request.client else None,
    )

    # Get full user data for response
    user_data = await auth_service.get_user_by_id(user["id"])

    logger.info(f"User logged in: {user['email']}")

    return LoginResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
        user=UserResponse(
            id=user_data["id"],
            tenant_id=user_data.get("tenant_id"),
            email=user_data["email"],
            full_name=user_data.get("full_name"),
            role=UserRole(user_data["role"]),
            is_active=user_data["is_active"],
            email_verified=user_data.get("email_verified", False),
            avatar_url=user_data.get("avatar_url"),
            last_login_at=user_data.get("last_login_at"),
            created_at=user_data["created_at"],
            tenant_name=user_data.get("tenant_name"),
            tenant_slug=user_data.get("tenant_slug"),
        ),
    )


@router.post("/refresh", response_model=RefreshTokenResponse)
async def refresh_token(data: RefreshTokenRequest):
    """
    Refresh access token using refresh token.

    Returns new access token. Refresh token remains valid.
    """
    auth_service = AuthService()

    # Validate refresh token
    user_id = auth_service.validate_refresh_token(data.refresh_token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    # Verify token is stored (not revoked)
    is_stored = await auth_service.verify_refresh_token_stored(
        user_id=user_id,
        token=data.refresh_token,
    )
    if not is_stored:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token has been revoked",
        )

    # Get user data
    user = await auth_service.get_user_by_id(user_id)
    if not user or not user["is_active"]:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive",
        )

    # Create new access token
    access_token = auth_service.create_access_token(
        user_id=user["id"],
        email=user["email"],
        role=user["role"],
        tenant_id=user.get("tenant_id"),
    )

    logger.debug(f"Token refreshed for user: {user['email']}")

    return RefreshTokenResponse(
        access_token=access_token,
        token_type="bearer",
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )


@router.post("/logout")
async def logout(
    data: RefreshTokenRequest,
    current_user: CurrentUser = Depends(get_current_user_rls_scoped),
):
    """
    Logout user by revoking refresh token.
    """
    auth_service = AuthService()

    # Revoke the refresh token
    await auth_service.revoke_refresh_token(data.refresh_token)

    logger.info(f"User logged out: {current_user.email}")

    return {"success": True, "message": "Logged out successfully"}


@router.post("/logout-all")
async def logout_all(
    current_user: CurrentUser = Depends(get_current_user_rls_scoped),
):
    """
    Logout user from all devices by revoking all refresh tokens.
    """
    auth_service = AuthService()

    await auth_service.revoke_all_user_tokens(current_user.id)

    logger.info(f"User logged out from all devices: {current_user.email}")

    return {"success": True, "message": "Logged out from all devices"}


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(
    current_user: CurrentUser = Depends(get_current_user_rls_scoped),
):
    """
    Get current authenticated user info.
    """
    auth_service = AuthService()

    user = await auth_service.get_user_by_id(current_user.id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return UserResponse(
        id=user["id"],
        tenant_id=user.get("tenant_id"),
        email=user["email"],
        full_name=user.get("full_name"),
        role=UserRole(user["role"]),
        is_active=user["is_active"],
        email_verified=user.get("email_verified", False),
        avatar_url=user.get("avatar_url"),
        last_login_at=user.get("last_login_at"),
        created_at=user["created_at"],
        tenant_name=user.get("tenant_name"),
        tenant_slug=user.get("tenant_slug"),
    )


@router.post("/change-password")
async def change_password(
    current_password: str,
    new_password: str,
    current_user: CurrentUser = Depends(get_current_user_rls_scoped),
):
    """
    Change current user's password.
    """
    from app.database.db import get_database

    auth_service = AuthService()
    db = get_database()

    # Get user with password hash
    user = await db.fetch_one(
        "SELECT password_hash FROM users WHERE id = :id",
        {"id": str(current_user.id)},
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    # Verify current password
    if not auth_service.verify_password(current_password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current password is incorrect",
        )

    # Validate new password
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="New password must be at least 8 characters",
        )

    # Update password
    new_hash = auth_service.hash_password(new_password)
    await db.execute(
        "UPDATE users SET password_hash = :hash, updated_at = NOW() WHERE id = :id",
        {"hash": new_hash, "id": str(current_user.id)},
    )

    # Revoke all refresh tokens (force re-login)
    await auth_service.revoke_all_user_tokens(current_user.id)

    logger.info(f"Password changed for user: {current_user.email}")

    return {"success": True, "message": "Password changed. Please log in again."}
