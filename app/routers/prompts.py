"""
Voxlyne - Prompts API Routes

Prompt versioning, activation, rollback, and diff.
"""

import logging
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.database.db import get_database
from app.middleware.auth_middleware import (
    CurrentUser,
    check_tenant_access,
    get_current_user,
    require_roles,
)
from app.models.schemas import (
    PromptActivateResponse,
    PromptDiffResponse,
    PromptType,
    PromptVersionCreate,
    PromptVersionListResponse,
    PromptVersionResponse,
)
from app.services.prompt_service import get_prompt_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Prompts"])


async def _get_project_tenant_id(project_id: UUID) -> Optional[UUID]:
    """Get tenant_id for a project."""
    db = get_database()
    result = await db.fetch_one(
        "SELECT tenant_id FROM projects WHERE id = :project_id",
        {"project_id": str(project_id)},
    )
    return UUID(str(result["tenant_id"])) if result and result["tenant_id"] else None


@router.get("/projects/{project_id}/prompts/{prompt_type}/versions", response_model=PromptVersionListResponse)
async def list_prompt_versions(
    project_id: UUID,
    prompt_type: PromptType,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    List all versions for a project's prompt (A or B).
    """
    # Check tenant access
    tenant_id = await _get_project_tenant_id(project_id)
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    prompt_service = get_prompt_service()

    versions = await prompt_service.get_versions(project_id, prompt_type.value)

    # Find active version
    active_version = None
    for v in versions:
        if v["is_active"]:
            active_version = v["version"]
            break

    return PromptVersionListResponse(
        versions=[
            PromptVersionResponse(
                id=UUID(str(v["id"])),
                project_id=UUID(str(v["project_id"])),
                prompt_type=PromptType(v["prompt_type"]),
                version=v["version"],
                content=v["content"],
                is_active=v["is_active"],
                created_by=UUID(str(v["created_by"])) if v["created_by"] else None,
                created_at=v["created_at"],
                creator_name=v.get("creator_name"),
            )
            for v in versions
        ],
        active_version=active_version,
        total=len(versions),
    )


@router.post("/projects/{project_id}/prompts/{prompt_type}/versions", response_model=PromptVersionResponse, status_code=status.HTTP_201_CREATED)
async def create_prompt_version(
    project_id: UUID,
    prompt_type: PromptType,
    version_data: PromptVersionCreate,
    activate: bool = False,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Create a new prompt version.

    Optionally activate it immediately.
    """
    # Check tenant access
    tenant_id = await _get_project_tenant_id(project_id)
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    prompt_service = get_prompt_service()

    version = await prompt_service.create_version(
        project_id=project_id,
        prompt_type=prompt_type.value,
        content=version_data.content,
        created_by=current_user.id,
        activate=activate,
    )

    logger.info(f"Created prompt version {version['version']} for project {project_id} by {current_user.email}")

    return PromptVersionResponse(
        id=UUID(str(version["id"])),
        project_id=UUID(str(version["project_id"])),
        prompt_type=PromptType(version["prompt_type"]),
        version=version["version"],
        content=version["content"],
        is_active=version["is_active"],
        created_by=UUID(str(version["created_by"])) if version["created_by"] else None,
        created_at=version["created_at"],
    )


@router.get("/prompts/versions/{version_id}", response_model=PromptVersionResponse)
async def get_prompt_version(
    version_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    Get a specific prompt version.
    """
    prompt_service = get_prompt_service()

    version = await prompt_service.get_version(version_id)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    # Check tenant access
    tenant_id = await _get_project_tenant_id(UUID(str(version["project_id"])))
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    return PromptVersionResponse(
        id=UUID(str(version["id"])),
        project_id=UUID(str(version["project_id"])),
        prompt_type=PromptType(version["prompt_type"]),
        version=version["version"],
        content=version["content"],
        is_active=version["is_active"],
        created_by=UUID(str(version["created_by"])) if version["created_by"] else None,
        created_at=version["created_at"],
        creator_name=version.get("creator_name"),
    )


@router.post("/prompts/versions/{version_id}/activate", response_model=PromptActivateResponse)
async def activate_prompt_version(
    version_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Activate a prompt version.

    Deactivates any currently active version of the same type.
    """
    prompt_service = get_prompt_service()

    # Get version to check access
    version = await prompt_service.get_version(version_id)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    # Check tenant access
    tenant_id = await _get_project_tenant_id(UUID(str(version["project_id"])))
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    success = await prompt_service.activate_version(version_id, current_user.id)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to activate version",
        )

    logger.info(f"Activated prompt version {version_id} by {current_user.email}")

    return PromptActivateResponse(
        success=True,
        message=f"Version {version['version']} activated",
        version_id=version_id,
        version=version["version"],
        prompt_type=PromptType(version["prompt_type"]),
    )


@router.post("/prompts/versions/{version_id}/rollback", response_model=PromptVersionResponse)
async def rollback_to_version(
    version_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Rollback to a specific version.

    Creates a new version with the same content and activates it.
    """
    prompt_service = get_prompt_service()

    # Get version to check access
    version = await prompt_service.get_version(version_id)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    # Check tenant access
    tenant_id = await _get_project_tenant_id(UUID(str(version["project_id"])))
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    new_version = await prompt_service.rollback_to_version(version_id, current_user.id)

    if not new_version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to rollback",
        )

    logger.info(f"Rolled back to version {version_id}, created version {new_version['version']} by {current_user.email}")

    return PromptVersionResponse(
        id=UUID(str(new_version["id"])),
        project_id=UUID(str(new_version["project_id"])),
        prompt_type=PromptType(new_version["prompt_type"]),
        version=new_version["version"],
        content=new_version["content"],
        is_active=new_version["is_active"],
        created_by=UUID(str(new_version["created_by"])) if new_version["created_by"] else None,
        created_at=new_version["created_at"],
    )


@router.get("/prompts/versions/{version_a}/diff/{version_b}", response_model=PromptDiffResponse)
async def get_prompt_diff(
    version_a: UUID,
    version_b: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    Get diff between two prompt versions.

    Version A should be the older version, B the newer.
    """
    prompt_service = get_prompt_service()

    # Get versions to check access
    va = await prompt_service.get_version(version_a)
    vb = await prompt_service.get_version(version_b)

    if not va or not vb:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="One or both versions not found",
        )

    # Must be same project and type
    if va["project_id"] != vb["project_id"] or va["prompt_type"] != vb["prompt_type"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Versions must be from the same project and prompt type",
        )

    # Check tenant access
    tenant_id = await _get_project_tenant_id(UUID(str(va["project_id"])))
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    try:
        diff_result = await prompt_service.get_diff(version_a, version_b)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )

    return PromptDiffResponse(
        version_a=PromptVersionResponse(
            id=UUID(str(diff_result["version_a"]["id"])),
            project_id=UUID(str(diff_result["version_a"]["project_id"])),
            prompt_type=PromptType(diff_result["version_a"]["prompt_type"]),
            version=diff_result["version_a"]["version"],
            content=diff_result["version_a"]["content"],
            is_active=diff_result["version_a"]["is_active"],
            created_by=UUID(str(diff_result["version_a"]["created_by"])) if diff_result["version_a"]["created_by"] else None,
            created_at=diff_result["version_a"]["created_at"],
        ),
        version_b=PromptVersionResponse(
            id=UUID(str(diff_result["version_b"]["id"])),
            project_id=UUID(str(diff_result["version_b"]["project_id"])),
            prompt_type=PromptType(diff_result["version_b"]["prompt_type"]),
            version=diff_result["version_b"]["version"],
            content=diff_result["version_b"]["content"],
            is_active=diff_result["version_b"]["is_active"],
            created_by=UUID(str(diff_result["version_b"]["created_by"])) if diff_result["version_b"]["created_by"] else None,
            created_at=diff_result["version_b"]["created_at"],
        ),
        diff=diff_result["diff"],
        additions=diff_result["additions"],
        deletions=diff_result["deletions"],
    )


@router.get("/prompts/versions/{version_id}/history")
async def get_version_history(
    version_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    Get history for a specific version.
    """
    prompt_service = get_prompt_service()

    # Get version to check access
    version = await prompt_service.get_version(version_id)
    if not version:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Version not found",
        )

    # Check tenant access
    tenant_id = await _get_project_tenant_id(UUID(str(version["project_id"])))
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    history = await prompt_service.get_history(version_id)

    return {
        "version_id": str(version_id),
        "history": [
            {
                "id": str(h["id"]),
                "action": h["action"],
                "performed_by": str(h["performed_by"]) if h["performed_by"] else None,
                "performer_name": h.get("performer_name"),
                "performer_email": h.get("performer_email"),
                "metadata": h.get("metadata", {}),
                "created_at": h["created_at"],
            }
            for h in history
        ],
    }
