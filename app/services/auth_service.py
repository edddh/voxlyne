"""
Ascolta - Authentication Service

JWT token generation, validation, and password hashing.
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
from uuid import UUID

import bcrypt
import jwt

from app.config import get_settings
from app.database.db import get_database

logger = logging.getLogger(__name__)


class AuthService:
    """
    Authentication service for JWT token management and password hashing.

    Features:
    - JWT access/refresh token generation
    - Password hashing with bcrypt
    - Token validation and refresh
    - Refresh token storage and revocation
    """

    def __init__(self):
        self.settings = get_settings()

    # ===========================================
    # Password Hashing
    # ===========================================

    def hash_password(self, password: str) -> str:
        """
        Hash a password using bcrypt.

        Args:
            password: Plain text password

        Returns:
            Hashed password string
        """
        salt = bcrypt.gensalt(rounds=12)
        return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    def verify_password(self, password: str, hashed: str) -> bool:
        """
        Verify a password against its hash.

        Args:
            password: Plain text password to verify
            hashed: Hashed password from database

        Returns:
            True if password matches
        """
        try:
            return bcrypt.checkpw(
                password.encode("utf-8"),
                hashed.encode("utf-8")
            )
        except Exception as e:
            logger.error(f"Password verification error: {e}")
            return False

    # ===========================================
    # JWT Token Generation
    # ===========================================

    def create_access_token(
        self,
        user_id: UUID,
        email: str,
        role: str,
        tenant_id: Optional[UUID] = None,
        extra_claims: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Create a JWT access token.

        Args:
            user_id: User UUID
            email: User email
            role: User role (super_admin, admin, etc.)
            tenant_id: Tenant UUID (None for super_admin)
            extra_claims: Additional JWT claims

        Returns:
            JWT access token string
        """
        now = datetime.now(timezone.utc)
        expire = now + timedelta(minutes=self.settings.jwt_access_token_expire_minutes)

        payload = {
            "sub": str(user_id),
            "email": email,
            "role": role,
            "tenant_id": str(tenant_id) if tenant_id else None,
            "type": "access",
            "iat": now,
            "exp": expire,
        }

        if extra_claims:
            payload.update(extra_claims)

        return jwt.encode(
            payload,
            self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
        )

    def create_refresh_token(
        self,
        user_id: UUID,
    ) -> tuple[str, datetime]:
        """
        Create a JWT refresh token.

        Args:
            user_id: User UUID

        Returns:
            Tuple of (refresh token string, expiration datetime)
        """
        now = datetime.now(timezone.utc)
        expire = now + timedelta(days=self.settings.jwt_refresh_token_expire_days)

        payload = {
            "sub": str(user_id),
            "type": "refresh",
            "jti": secrets.token_hex(16),  # Unique token ID
            "iat": now,
            "exp": expire,
        }

        token = jwt.encode(
            payload,
            self.settings.jwt_secret,
            algorithm=self.settings.jwt_algorithm,
        )

        return token, expire

    # ===========================================
    # Token Validation
    # ===========================================

    def decode_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Decode and validate a JWT token.

        Args:
            token: JWT token string

        Returns:
            Decoded payload dict or None if invalid
        """
        try:
            payload = jwt.decode(
                token,
                self.settings.jwt_secret,
                algorithms=[self.settings.jwt_algorithm],
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.debug("Token expired")
            return None
        except jwt.InvalidTokenError as e:
            logger.debug(f"Invalid token: {e}")
            return None

    def validate_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Validate an access token and return user info.

        Args:
            token: JWT access token

        Returns:
            User info dict or None if invalid
        """
        payload = self.decode_token(token)
        if not payload:
            return None

        if payload.get("type") != "access":
            logger.debug("Token is not an access token")
            return None

        return {
            "user_id": UUID(payload["sub"]),
            "email": payload["email"],
            "role": payload["role"],
            "tenant_id": UUID(payload["tenant_id"]) if payload.get("tenant_id") else None,
        }

    def validate_refresh_token(self, token: str) -> Optional[UUID]:
        """
        Validate a refresh token and return user ID.

        Args:
            token: JWT refresh token

        Returns:
            User UUID or None if invalid
        """
        payload = self.decode_token(token)
        if not payload:
            return None

        if payload.get("type") != "refresh":
            logger.debug("Token is not a refresh token")
            return None

        return UUID(payload["sub"])

    # ===========================================
    # Refresh Token Storage
    # ===========================================

    async def store_refresh_token(
        self,
        user_id: UUID,
        token: str,
        expires_at: datetime,
        user_agent: Optional[str] = None,
        ip_address: Optional[str] = None,
    ) -> bool:
        """
        Store a refresh token in the database.

        Args:
            user_id: User UUID
            token: Refresh token
            expires_at: Token expiration datetime
            user_agent: Client user agent
            ip_address: Client IP address

        Returns:
            True if stored successfully
        """
        db = get_database()

        # Hash the token for storage
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        try:
            await db.execute(
                """
                INSERT INTO refresh_tokens (user_id, token_hash, expires_at, user_agent, ip_address)
                VALUES (:user_id, :token_hash, :expires_at, :user_agent, :ip_address)
                """,
                {
                    "user_id": str(user_id),
                    "token_hash": token_hash,
                    "expires_at": expires_at,
                    "user_agent": user_agent,
                    "ip_address": ip_address,
                },
            )
            return True
        except Exception as e:
            logger.error(f"Error storing refresh token: {e}")
            return False

    async def verify_refresh_token_stored(self, user_id: UUID, token: str) -> bool:
        """
        Verify a refresh token exists in the database.

        Args:
            user_id: User UUID
            token: Refresh token to verify

        Returns:
            True if token exists and is valid
        """
        db = get_database()

        token_hash = hashlib.sha256(token.encode()).hexdigest()

        result = await db.fetch_one(
            """
            SELECT id FROM refresh_tokens
            WHERE user_id = :user_id
              AND token_hash = :token_hash
              AND expires_at > :now
            """,
            {
                "user_id": str(user_id),
                "token_hash": token_hash,
                "now": datetime.now(timezone.utc),
            },
        )

        return result is not None

    async def revoke_refresh_token(self, token: str) -> bool:
        """
        Revoke a refresh token (delete from database).

        Args:
            token: Refresh token to revoke

        Returns:
            True if revoked successfully
        """
        db = get_database()

        token_hash = hashlib.sha256(token.encode()).hexdigest()

        try:
            await db.execute(
                "DELETE FROM refresh_tokens WHERE token_hash = :token_hash",
                {"token_hash": token_hash},
            )
            return True
        except Exception as e:
            logger.error(f"Error revoking refresh token: {e}")
            return False

    async def revoke_all_user_tokens(self, user_id: UUID) -> bool:
        """
        Revoke all refresh tokens for a user.

        Args:
            user_id: User UUID

        Returns:
            True if revoked successfully
        """
        db = get_database()

        try:
            await db.execute(
                "DELETE FROM refresh_tokens WHERE user_id = :user_id",
                {"user_id": str(user_id)},
            )
            return True
        except Exception as e:
            logger.error(f"Error revoking user tokens: {e}")
            return False

    async def cleanup_expired_tokens(self) -> int:
        """
        Remove expired refresh tokens from database.

        Returns:
            Number of tokens removed
        """
        db = get_database()

        try:
            result = await db.execute(
                "DELETE FROM refresh_tokens WHERE expires_at < :now",
                {"now": datetime.now(timezone.utc)},
            )
            return result if isinstance(result, int) else 0
        except Exception as e:
            logger.error(f"Error cleaning up expired tokens: {e}")
            return 0

    # ===========================================
    # User Authentication
    # ===========================================

    async def authenticate_user(
        self,
        email: str,
        password: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Authenticate a user by email and password.

        Args:
            email: User email
            password: Plain text password

        Returns:
            User dict or None if authentication fails
        """
        db = get_database()

        user = await db.fetch_one(
            """
            SELECT id, tenant_id, email, password_hash, full_name, role, is_active
            FROM users
            WHERE email = :email
            """,
            {"email": email.lower()},
        )

        if not user:
            logger.debug(f"User not found: {email}")
            return None

        if not user["is_active"]:
            logger.debug(f"User inactive: {email}")
            return None

        if not self.verify_password(password, user["password_hash"]):
            logger.debug(f"Invalid password for user: {email}")
            return None

        # Update last login
        await db.execute(
            """
            UPDATE users SET last_login_at = :now WHERE id = :id
            """,
            {"now": datetime.now(timezone.utc), "id": user["id"]},
        )

        return {
            "id": UUID(str(user["id"])),
            "tenant_id": UUID(str(user["tenant_id"])) if user["tenant_id"] else None,
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
        }

    async def get_user_by_id(self, user_id: UUID) -> Optional[Dict[str, Any]]:
        """
        Get user by ID.

        Args:
            user_id: User UUID

        Returns:
            User dict or None if not found
        """
        db = get_database()

        user = await db.fetch_one(
            """
            SELECT u.id, u.tenant_id, u.email, u.full_name, u.role,
                   u.is_active, u.email_verified, u.avatar_url,
                   u.last_login_at, u.created_at,
                   t.name as tenant_name, t.slug as tenant_slug
            FROM users u
            LEFT JOIN tenants t ON u.tenant_id = t.id
            WHERE u.id = :id
            """,
            {"id": str(user_id)},
        )

        if not user:
            return None

        return {
            "id": UUID(str(user["id"])),
            "tenant_id": UUID(str(user["tenant_id"])) if user["tenant_id"] else None,
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "is_active": user["is_active"],
            "email_verified": user["email_verified"],
            "avatar_url": user["avatar_url"],
            "last_login_at": user["last_login_at"],
            "created_at": user["created_at"],
            "tenant_name": user["tenant_name"],
            "tenant_slug": user["tenant_slug"],
        }

    # ===========================================
    # API Key Generation
    # ===========================================

    def generate_api_key(self) -> tuple[str, str, str]:
        """
        Generate a new API key.

        Returns:
            Tuple of (full key, key hash, key prefix)
        """
        # Generate a random key: asc_<random hex>
        random_part = secrets.token_hex(24)
        full_key = f"asc_{random_part}"
        key_hash = bcrypt.hashpw(full_key.encode(), bcrypt.gensalt(rounds=10)).decode()
        key_prefix = full_key[:12]  # asc_12345678

        return full_key, key_hash, key_prefix

    async def validate_api_key(self, api_key: str) -> Optional[Dict[str, Any]]:
        """
        Validate an API key and return associated info.

        Args:
            api_key: Full API key string

        Returns:
            API key info dict or None if invalid
        """
        db = get_database()

        # Get prefix from key
        key_prefix = api_key[:12] if len(api_key) >= 12 else api_key

        # Find candidates by prefix
        keys = await db.fetch_all(
            """
            SELECT id, tenant_id, name, key_hash, scopes, is_active, expires_at
            FROM api_keys
            WHERE key_prefix = :prefix AND is_active = TRUE
            """,
            {"prefix": key_prefix},
        )

        for key in keys:
            # Check expiration
            if key["expires_at"] and key["expires_at"] < datetime.now(timezone.utc):
                continue

            # Verify hash
            if bcrypt.checkpw(api_key.encode(), key["key_hash"].encode()):
                # Update last used
                await db.execute(
                    "UPDATE api_keys SET last_used_at = :now WHERE id = :id",
                    {"now": datetime.now(timezone.utc), "id": key["id"]},
                )

                return {
                    "id": UUID(str(key["id"])),
                    "tenant_id": UUID(str(key["tenant_id"])) if key["tenant_id"] else None,
                    "name": key["name"],
                    "scopes": key["scopes"],
                }

        return None
