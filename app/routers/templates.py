"""
Voxlyne - Templates API Routes (M4+)

Template management for super_admin:
- Create/update/list global templates
- Assign templates to tenants
- Templates are read-only for tenants (copy-on-create pattern)
"""

import json
import logging
from enum import Enum
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.database.db import get_database
from app.middleware.auth_middleware import (
    CurrentUser,
    get_current_user,
    require_roles,
    require_super_admin,
)
from app.models.schemas import (
    ProjectType,
    TemplateAssignment,
    TemplateAssignmentCreate,
    TemplateAssignmentListResponse,
    TemplateCreate,
    TemplateListResponse,
    TemplateResponse,
    TemplateUpdate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/templates", tags=["Templates"])

TEMPLATE_COLUMNS = """
    id, name, slug, type, template_category, description,
    prompt_a, prompt_b, consent_message, voice_name, language,
    is_active, created_at, updated_at, custom_variables_schema, custom_variables
"""


def _serialize_template(row) -> TemplateResponse:
    """
    Shared row->TemplateResponse mapping, used by every endpoint below -
    previously duplicated inline 4 times, each one a place the 20/08
    custom_variables_schema/custom_variables columns could have been
    (and almost were) forgotten in one spot but not another.
    """
    schema = row["custom_variables_schema"]
    if isinstance(schema, str):
        try:
            schema = json.loads(schema)
        except json.JSONDecodeError:
            schema = []
    values = row["custom_variables"]
    if isinstance(values, str):
        try:
            values = json.loads(values)
        except json.JSONDecodeError:
            values = {}
    return TemplateResponse(
        id=row["id"],
        name=row["name"],
        slug=row["slug"],
        type=ProjectType(row["type"]),
        template_category=row["template_category"],
        description=row["description"],
        prompt_a=row["prompt_a"],
        prompt_b=row["prompt_b"],
        consent_message=row["consent_message"],
        voice_name=row["voice_name"],
        language=row["language"],
        is_active=row["is_active"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        custom_variables_schema=schema or [],
        custom_variables=values or {},
    )


@router.get("", response_model=TemplateListResponse)
async def list_templates(
    current_user: CurrentUser = Depends(require_super_admin()),
    category: str = None,
):
    """
    List all global templates (super_admin only).

    Query params:
    - category: Filter by template_category (recruiting, sales, support, survey, other)
    """
    db = get_database()

    query = f"SELECT {TEMPLATE_COLUMNS} FROM projects WHERE is_template = TRUE"
    params = {}

    if category:
        query += " AND template_category = :category"
        params["category"] = category

    query += " ORDER BY created_at DESC"

    rows = await db.fetch_all(query, params)
    templates = [_serialize_template(row) for row in rows]

    return TemplateListResponse(templates=templates, total=len(templates))


@router.post("", response_model=TemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    data: TemplateCreate,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    Create a new global template (super_admin only).

    Templates are projects with:
    - is_template = TRUE
    - tenant_id = NULL (not owned by any tenant)
    - from_template_id = NULL (templates are not created from other templates)
    """
    db = get_database()

    # Check slug uniqueness
    existing = await db.fetch_one(
        "SELECT id FROM projects WHERE slug = :slug",
        {"slug": data.slug}
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"A project or template with slug '{data.slug}' already exists"
        )

    # Insert template
    template_id = await db.execute(
        """
        INSERT INTO projects (
            name, slug, type, template_category, description,
            prompt_a, prompt_b, consent_message, voice_name, language,
            custom_variables_schema, custom_variables,
            is_template, is_active, created_by
        ) VALUES (
            :name, :slug, :type, :template_category, :description,
            :prompt_a, :prompt_b, :consent_message, :voice_name, :language,
            :custom_variables_schema, :custom_variables,
            TRUE, TRUE, :created_by
        ) RETURNING id
        """,
        {
            "name": data.name,
            "slug": data.slug,
            "type": data.type.value,
            "template_category": data.template_category,
            "description": data.description,
            "prompt_a": data.prompt_a,
            "prompt_b": data.prompt_b,
            "consent_message": data.consent_message,
            "voice_name": data.voice_name,
            "language": data.language,
            "custom_variables_schema": json.dumps([f.model_dump() for f in data.custom_variables_schema]),
            "custom_variables": json.dumps(data.custom_variables),
            "created_by": str(current_user.id),
        }
    )

    template = await db.fetch_one(
        f"SELECT {TEMPLATE_COLUMNS} FROM projects WHERE id = :id",
        {"id": str(template_id)}
    )
    return _serialize_template(template)


@router.get("/assigned", response_model=TemplateListResponse)
async def list_assigned_templates(
    current_user: CurrentUser = Depends(require_roles(["admin", "creator"])),
):
    """
    Templates assigned to the current user's tenant - what "Crea da
    Template" (Projects.jsx) actually needs to offer a tenant admin/
    creator a pick-list, as opposed to GET /api/templates above (the
    super_admin-only full catalog, used for authoring templates).

    maintainer, 20/08: "anche crea da template non fa nulla" - it navigated
    straight to the super_admin-only /templates management page, so any
    other role silently bounced back to the Dashboard (ProtectedRoute's
    role check has no error message) - not just missing data, the wrong
    destination entirely: creating a project from a template was never
    supposed to require template-authoring access, just POST /api/
    projects/from-template/{id} (already built, never wired to any UI).
    Must be registered before GET /{template_id} or FastAPI tries to
    parse "assigned" as a UUID path param.
    """
    db = get_database()

    rows = await db.fetch_all(
        """
        SELECT p.id, p.name, p.slug, p.type, p.template_category, p.description,
               p.prompt_a, p.prompt_b, p.consent_message, p.voice_name, p.language,
               p.is_active, p.created_at, p.updated_at, p.custom_variables_schema, p.custom_variables
        FROM projects p
        INNER JOIN template_assignments ta ON p.id = ta.template_id
        WHERE p.is_template = TRUE
          AND ta.tenant_id = :tenant_id
          AND ta.is_active = TRUE
          AND p.is_active = TRUE
        ORDER BY p.name
        """,
        {"tenant_id": str(current_user.tenant_id)},
    )

    templates = [_serialize_template(row) for row in rows]
    return TemplateListResponse(templates=templates, total=len(templates))


@router.get("/{template_id}", response_model=TemplateResponse)
async def get_template(
    template_id: UUID,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """Get single template by ID (super_admin only)."""
    db = get_database()

    template = await db.fetch_one(
        f"SELECT {TEMPLATE_COLUMNS} FROM projects WHERE id = :id AND is_template = TRUE",
        {"id": str(template_id)}
    )

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found"
        )

    return _serialize_template(template)


@router.put("/{template_id}", response_model=TemplateResponse)
async def update_template(
    template_id: UUID,
    data: TemplateUpdate,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """Update a template (super_admin only)."""
    db = get_database()

    # Check template exists
    existing = await db.fetch_one(
        "SELECT id FROM projects WHERE id = :id AND is_template = TRUE",
        {"id": str(template_id)}
    )
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found"
        )

    # Build update query dynamically
    updates = []
    params = {"id": str(template_id)}

    for field, value in data.dict(exclude_unset=True).items():
        if value is None:
            continue
        if field == "custom_variables_schema":
            value = json.dumps(value)
        elif field == "custom_variables":
            value = json.dumps(value)
        elif isinstance(value, Enum):
            value = value.value
        updates.append(f"{field} = :{field}")
        params[field] = value

    if not updates:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No fields to update"
        )

    updates.append("updated_at = NOW()")
    query = f"UPDATE projects SET {', '.join(updates)} WHERE id = :id"

    await db.execute(query, params)

    # Return updated template
    return await get_template(template_id, current_user)


@router.post("/{template_id}/assign", response_model=dict, status_code=status.HTTP_200_OK)
async def assign_template_to_tenants(
    template_id: UUID,
    data: TemplateAssignmentCreate,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    Assign a template to multiple tenants (super_admin only).

    Tenants will be able to see this template and create projects from it.
    Assignments are idempotent (duplicate assignments are ignored).
    """
    db = get_database()

    # Verify template exists
    template = await db.fetch_one(
        "SELECT id FROM projects WHERE id = :id AND is_template = TRUE",
        {"id": str(template_id)}
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found"
        )

    # Verify all tenants exist
    tenant_ids_str = [str(tid) for tid in data.tenant_ids]
    tenants = await db.fetch_all(
        f"SELECT id FROM tenants WHERE id = ANY(:tenant_ids)",
        {"tenant_ids": tenant_ids_str}
    )
    if len(tenants) != len(data.tenant_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="One or more tenant IDs are invalid"
        )

    # Insert assignments (ON CONFLICT DO NOTHING = idempotent)
    assigned_count = 0
    for tenant_id in data.tenant_ids:
        result = await db.execute(
            """
            INSERT INTO template_assignments (template_id, tenant_id, assigned_by)
            VALUES (:template_id, :tenant_id, :assigned_by)
            ON CONFLICT (template_id, tenant_id) DO UPDATE SET is_active = TRUE
            """,
            {
                "template_id": str(template_id),
                "tenant_id": str(tenant_id),
                "assigned_by": str(current_user.id),
            }
        )
        assigned_count += 1

    return {
        "success": True,
        "message": f"Template assigned to {assigned_count} tenant(s)",
        "template_id": str(template_id),
        "tenant_ids": tenant_ids_str,
    }


@router.get("/{template_id}/assignments", response_model=TemplateAssignmentListResponse)
async def get_template_assignments(
    template_id: UUID,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    Get all tenant assignments for a template (super_admin only).

    Returns list of tenants that have access to this template.
    """
    db = get_database()

    # Verify template exists
    template = await db.fetch_one(
        "SELECT id FROM projects WHERE id = :id AND is_template = TRUE",
        {"id": str(template_id)}
    )
    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Template {template_id} not found"
        )

    # Fetch assignments
    rows = await db.fetch_all(
        """
        SELECT id, template_id, tenant_id, is_active, assigned_by, assigned_at
        FROM template_assignments
        WHERE template_id = :template_id
        ORDER BY assigned_at DESC
        """,
        {"template_id": str(template_id)}
    )

    assignments = [
        TemplateAssignment(
            id=row["id"],
            template_id=row["template_id"],
            tenant_id=row["tenant_id"],
            is_active=row["is_active"],
            assigned_by=row["assigned_by"],
            assigned_at=row["assigned_at"],
        )
        for row in rows
    ]

    return TemplateAssignmentListResponse(assignments=assignments, total=len(assignments))


@router.delete("/{template_id}/assignments/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unassign_template_from_tenant(
    template_id: UUID,
    tenant_id: UUID,
    current_user: CurrentUser = Depends(require_super_admin()),
):
    """
    Remove template assignment from a tenant (super_admin only).

    Sets is_active = FALSE (soft delete) so tenant can no longer see/use the template.
    """
    db = get_database()

    result = await db.execute(
        """
        UPDATE template_assignments
        SET is_active = FALSE
        WHERE template_id = :template_id AND tenant_id = :tenant_id
        """,
        {"template_id": str(template_id), "tenant_id": str(tenant_id)}
    )

    if result == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template assignment not found"
        )

    return None
