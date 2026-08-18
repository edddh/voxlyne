"""
Ascolta - Prompt Blocks API Routes (M4+)

Building blocks for prompt composer:
- Global blocks (super_admin, is_public=TRUE)
- Tenant-specific blocks (admin/creator)
- Categories: personality, rules, domain, custom
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.database.db import get_database
from app.middleware.auth_middleware import (
    CurrentUser,
    get_current_user_rls_scoped,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/prompt-blocks", tags=["Prompt Blocks"])


# ===========================================
# Schemas
# ===========================================

class BlockCreate(BaseModel):
    """Schema for creating a prompt block."""
    name: str = Field(..., min_length=1, max_length=255)
    category: str = Field(..., pattern="^(personality|rules|domain|custom)$")
    content: str = Field(..., min_length=1)
    is_public: bool = False  # Only super_admin can set to TRUE


class BlockUpdate(BaseModel):
    """Schema for updating a prompt block."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    category: Optional[str] = Field(None, pattern="^(personality|rules|domain|custom)$")
    content: Optional[str] = Field(None, min_length=1)


class BlockResponse(BaseModel):
    """Prompt block response."""
    id: UUID
    tenant_id: Optional[UUID]
    name: str
    category: str
    content: str
    is_public: bool
    created_by: Optional[UUID]
    created_at: str
    updated_at: str


class BlockListResponse(BaseModel):
    """List of prompt blocks."""
    blocks: List[BlockResponse]
    total: int


# ===========================================
# Endpoints
# ===========================================

@router.get("", response_model=BlockListResponse)
async def list_blocks(
    category: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user_rls_scoped)
):
    """
    List prompt blocks visible to current user.

    Returns:
    - Global public blocks (is_public=TRUE, tenant_id=NULL)
    - Tenant-owned blocks (tenant_id=current_user.tenant_id)

    Query params:
    - category: Filter by category (personality, rules, domain, custom)
    """
    db = get_database()

    query = """
        SELECT id, tenant_id, name, category, content, is_public,
               created_by, created_at, updated_at
        FROM prompt_blocks
        WHERE (is_public = TRUE AND tenant_id IS NULL)
    """
    params = {}

    # Add tenant-specific blocks
    if current_user.tenant_id:
        query += " OR tenant_id = :tenant_id"
        params["tenant_id"] = str(current_user.tenant_id)

    # Category filter
    if category:
        if category not in ["personality", "rules", "domain", "custom"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category must be personality, rules, domain, or custom"
            )
        query += " AND category = :category" if "WHERE" in query else " WHERE category = :category"
        params["category"] = category

    query += " ORDER BY category, name"

    rows = await db.fetch_all(query, params)

    blocks = [
        BlockResponse(
            id=row["id"],
            tenant_id=UUID(str(row["tenant_id"])) if row["tenant_id"] else None,
            name=row["name"],
            category=row["category"],
            content=row["content"],
            is_public=row["is_public"],
            created_by=UUID(str(row["created_by"])) if row["created_by"] else None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        for row in rows
    ]

    return BlockListResponse(blocks=blocks, total=len(blocks))


@router.post("", response_model=BlockResponse, status_code=status.HTTP_201_CREATED)
async def create_block(
    data: BlockCreate,
    current_user: CurrentUser = Depends(get_current_user_rls_scoped)
):
    """
    Create a new prompt block.

    - Super admin can create global public blocks (is_public=TRUE, tenant_id=NULL)
    - Admin/Creator create tenant-specific blocks (is_public=FALSE, tenant_id=current_user.tenant_id)
    """
    db = get_database()

    # Only super_admin can create public blocks
    if data.is_public and current_user.role != "super_admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only super_admin can create public blocks"
        )

    # Determine tenant_id
    tenant_id = None if data.is_public else current_user.tenant_id

    # Insert block
    block_id = await db.execute(
        """
        INSERT INTO prompt_blocks (tenant_id, name, category, content, is_public, created_by)
        VALUES (:tenant_id, :name, :category, :content, :is_public, :created_by)
        RETURNING id
        """,
        {
            "tenant_id": str(tenant_id) if tenant_id else None,
            "name": data.name,
            "category": data.category,
            "content": data.content,
            "is_public": data.is_public,
            "created_by": str(current_user.id),
        }
    )

    # Return created block
    block = await db.fetch_one(
        """
        SELECT id, tenant_id, name, category, content, is_public,
               created_by, created_at, updated_at
        FROM prompt_blocks
        WHERE id = :id
        """,
        {"id": str(block_id)}
    )

    return BlockResponse(
        id=block["id"],
        tenant_id=UUID(str(block["tenant_id"])) if block["tenant_id"] else None,
        name=block["name"],
        category=block["category"],
        content=block["content"],
        is_public=block["is_public"],
        created_by=UUID(str(block["created_by"])) if block["created_by"] else None,
        created_at=str(block["created_at"]),
        updated_at=str(block["updated_at"]),
    )


@router.get("/{block_id}", response_model=BlockResponse)
async def get_block(
    block_id: UUID,
    current_user: CurrentUser = Depends(get_current_user_rls_scoped)
):
    """Get single block by ID (if accessible)."""
    db = get_database()

    block = await db.fetch_one(
        """
        SELECT id, tenant_id, name, category, content, is_public,
               created_by, created_at, updated_at
        FROM prompt_blocks
        WHERE id = :id
        """,
        {"id": str(block_id)}
    )

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_id} not found"
        )

    # Check access
    block_tenant_id = UUID(str(block["tenant_id"])) if block["tenant_id"] else None
    is_accessible = (
        block["is_public"] or
        block_tenant_id == current_user.tenant_id or
        current_user.role == "super_admin"
    )

    if not is_accessible:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this block"
        )

    return BlockResponse(
        id=block["id"],
        tenant_id=block_tenant_id,
        name=block["name"],
        category=block["category"],
        content=block["content"],
        is_public=block["is_public"],
        created_by=UUID(str(block["created_by"])) if block["created_by"] else None,
        created_at=str(block["created_at"]),
        updated_at=str(block["updated_at"]),
    )


@router.put("/{block_id}", response_model=BlockResponse)
async def update_block(
    block_id: UUID,
    data: BlockUpdate,
    current_user: CurrentUser = Depends(get_current_user_rls_scoped)
):
    """
    Update a prompt block.

    Only owner (created_by) or super_admin can update.
    """
    db = get_database()

    # Check block exists and ownership
    block = await db.fetch_one(
        "SELECT tenant_id, created_by, is_public FROM prompt_blocks WHERE id = :id",
        {"id": str(block_id)}
    )

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_id} not found"
        )

    # Check permission
    is_owner = str(block["created_by"]) == str(current_user.id)
    is_super_admin = current_user.role == "super_admin"

    if not (is_owner or is_super_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only block owner or super_admin can update"
        )

    # Build update query
    updates = []
    params = {"id": str(block_id)}

    for field, value in data.dict(exclude_unset=True).items():
        if value is not None:
            updates.append(f"{field} = :{field}")
            params[field] = value

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )

    updates.append("updated_at = NOW()")
    query = f"UPDATE prompt_blocks SET {', '.join(updates)} WHERE id = :id"

    await db.execute(query, params)

    # Return updated block
    return await get_block(block_id, current_user)


@router.delete("/{block_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_block(
    block_id: UUID,
    current_user: CurrentUser = Depends(get_current_user_rls_scoped)
):
    """
    Delete a prompt block.

    Only owner (created_by) or super_admin can delete.
    """
    db = get_database()

    # Check block exists and ownership
    block = await db.fetch_one(
        "SELECT created_by, is_public FROM prompt_blocks WHERE id = :id",
        {"id": str(block_id)}
    )

    if not block:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Block {block_id} not found"
        )

    # Check permission
    is_owner = str(block["created_by"]) == str(current_user.id)
    is_super_admin = current_user.role == "super_admin"

    if not (is_owner or is_super_admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only block owner or super_admin can delete"
        )

    await db.execute("DELETE FROM prompt_blocks WHERE id = :id", {"id": str(block_id)})

    return None
