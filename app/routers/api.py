"""
Ascolta - API Routes (M2)
Project-aware RESTful API for call data and PDF access
"""

import logging
from datetime import datetime, timezone
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from asyncpg.exceptions import UniqueViolationError

import json

from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.models.schemas import (
    Call,
    CallComplete,
    Project,
    ProjectCreate,
    ProjectUpdate,
    Record,
    RecordWithCall,
)
from app.services.pdf_generator import PDFGenerator, PDFGeneratorError
from app.services.openai_realtime_config import validate_openai_realtime_model
from app.services.post_processor import PostProcessor, PostProcessingError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])


async def _assert_call_access(call_id: UUID, current_user: CurrentUser) -> None:
    """Same contract as the identical helper in calendar.py/crm.py: 404 on
    both "not found" and "not yours". A call with tenant_id = NULL (every
    inbound call today, pending the Fase 2 resolver) is super_admin-only."""
    db = get_database()
    call = await db.fetch_one(
        "SELECT tenant_id FROM calls WHERE id = :call_id",
        {"call_id": str(call_id)},
    )
    if not call or not check_tenant_access(current_user, call["tenant_id"]):
        raise HTTPException(status_code=404, detail="Call not found")


def _serialize_project(project_row) -> dict:
    """Normalize project row for API output."""
    item = dict(project_row)
    output_config = item.get("output_config")
    if isinstance(output_config, str):
        try:
            item["output_config"] = json.loads(output_config)
        except json.JSONDecodeError:
            item["output_config"] = {}
    # Stessa gestione difensiva di output_config sopra - il driver a
    # volte restituisce le colonne JSONB come stringa non ancora
    # deserializzata (20/08, custom_variables_schema/custom_variables).
    schema = item.get("custom_variables_schema")
    if isinstance(schema, str):
        try:
            item["custom_variables_schema"] = json.loads(schema)
        except json.JSONDecodeError:
            item["custom_variables_schema"] = []
    values = item.get("custom_variables")
    if isinstance(values, str):
        try:
            item["custom_variables"] = json.loads(values)
        except json.JSONDecodeError:
            item["custom_variables"] = {}
    provider_config = item.get("voice_provider_config")
    if isinstance(provider_config, str):
        try:
            item["voice_provider_config"] = json.loads(provider_config)
        except json.JSONDecodeError:
            item["voice_provider_config"] = {}
    return item


# ===========================================
# Projects
# ===========================================

@router.get("/projects/templates", response_model=List[Project])
async def list_assigned_templates(
    current_user: CurrentUser = Depends(require_roles(["admin", "creator"]))
):
    """
    List templates assigned to current user's tenant.

    Returns templates that can be used to create new projects.
    """
    db = get_database()

    query = """
        SELECT p.* FROM projects p
        INNER JOIN template_assignments ta ON p.id = ta.template_id
        WHERE p.is_template = TRUE
          AND ta.tenant_id = :tenant_id
          AND ta.is_active = TRUE
          AND p.is_active = TRUE
        ORDER BY p.created_at DESC
    """

    templates = await db.fetch_all(query, {"tenant_id": str(current_user.tenant_id)})

    return [_serialize_project(t) for t in templates]


@router.get("/projects", response_model=List[Project])
async def list_projects(
    active_only: Optional[bool] = Query(None, description="True=solo attivi, False=solo inattivi, null=tutti"),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user", "user"])),
):
    """
    List projects visible to the current user's tenant (all tenants for super_admin).

    Args:
        active_only: Filter to active projects only (default: True)

    Returns:
        List of projects
    """
    db = get_database()

    # Templates (is_template=TRUE, tenant_id=NULL) live in this same
    # `projects` table but are not real projects - excluded unconditionally,
    # not just for non-super-admin. Found live (20/08): for a regular tenant
    # user the "tenant_id = :tenant_id" filter below already excluded them
    # incidentally (a template's tenant_id is never a real tenant's), but
    # super_admin skips that filter and saw templates mixed into the
    # Projects table - one of them got clicked in "Genera servizio runtime",
    # which then crashed (ValueError: badly formed hexadecimal UUID string)
    # trying to parse its NULL tenant_id, see runtime_provisioning.py.
    conditions = ["is_template = FALSE"]
    params: dict = {}

    if active_only is True:
        conditions.append("is_active = TRUE")
    elif active_only is False:
        conditions.append("is_active = FALSE")

    if not current_user.is_super_admin:
        conditions.append("tenant_id = :tenant_id")
        params["tenant_id"] = str(current_user.tenant_id)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"SELECT * FROM projects {where_clause} ORDER BY created_at DESC"

    projects = await db.fetch_all(query, params)

    return [_serialize_project(p) for p in projects]


@router.post("/projects/from-template/{template_id}", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project_from_template(
    template_id: UUID,
    name: str = Query(..., min_length=1),
    slug: str = Query(..., pattern="^[a-z0-9-]+$"),
    description: str = Query(None),
    custom_variables: str = Query(
        None,
        description="JSON object of {{key}} values for this project (filled in at import time) - "
                    "falls back to the template's own default values for any key not provided.",
    ),
    current_user: CurrentUser = Depends(require_roles(["admin", "creator"]))
):
    """
    Create a new project from a template.

    Copies the template's "personality" (prompt_a, prompt_b, consent
    message, voice, language, voice engine, output_config incl. PDF/email
    settings) - NOT instance-specific fields that would make two projects
    collide on the same external resource if copied verbatim (sip_number,
    vapi_assistant_id, twilio_phone_number, vapi_phone_number_id,
    elevenlabs_agent_id, livekit_agent_name - each new project gets its
    own via Telefonia/Credenziali, not inherited).

    Fixed 18/08 (found while checking on maintainer's "il meccanismo dei
    template e' completo?"): this used to (a) run as two separate
    statements with no transaction - a crash between them left an
    orphaned project with no prompt_placeholders row, (b) not copy
    voice_engine/output_config at all - cloning a Grok-based template
    silently produced an openai_realtime project instead, (c) claim in
    its docstring to also create CRM/calendar config rows it never
    actually created - removed that claim rather than adding dead rows
    those integrations' own save endpoints already upsert on first use.
    """
    db = get_database()

    # Verify template exists and is assigned to tenant
    template = await db.fetch_one(
        """
        SELECT p.* FROM projects p
        INNER JOIN template_assignments ta ON p.id = ta.template_id
        WHERE p.id = :template_id
          AND p.is_template = TRUE
          AND ta.tenant_id = :tenant_id
          AND ta.is_active = TRUE
        """,
        {"template_id": str(template_id), "tenant_id": str(current_user.tenant_id)}
    )

    if not template:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Template not found or not assigned to your tenant"
        )

    # Check slug uniqueness
    existing = await db.fetch_one(
        "SELECT id FROM projects WHERE slug = :slug",
        {"slug": slug}
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Project with slug '{slug}' already exists"
        )

    template_output_config = template["output_config"]
    if isinstance(template_output_config, str):
        try:
            template_output_config = json.loads(template_output_config)
        except (json.JSONDecodeError, TypeError):
            template_output_config = {}

    # {{key}} custom variables (20/08, maintainer: "il template dovrebbe
    # avere dei campi custom che chiede di riempire quando si effettua
    # l'importazione") - the schema (which fields exist) always comes
    # from the template unchanged; the values start as the template's
    # own defaults, overridden by whatever the caller filled in at
    # import time.
    template_schema = template["custom_variables_schema"]
    if isinstance(template_schema, str):
        try:
            template_schema = json.loads(template_schema)
        except (json.JSONDecodeError, TypeError):
            template_schema = []
    template_values = template["custom_variables"]
    if isinstance(template_values, str):
        try:
            template_values = json.loads(template_values)
        except (json.JSONDecodeError, TypeError):
            template_values = {}
    new_values = dict(template_values or {})
    if custom_variables:
        try:
            provided = json.loads(custom_variables)
        except json.JSONDecodeError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="custom_variables must be valid JSON")
        if not isinstance(provided, dict):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="custom_variables must be a JSON object")
        new_values.update(provided)

    async with db.transaction():
        project_id = await db.fetch_val(
            """
            INSERT INTO projects (
                tenant_id, name, slug, type, description,
                prompt_a, prompt_b, consent_message, voice_name, language,
                voice_engine, ai_provider, output_config, voice_provider_config,
                custom_variables_schema, custom_variables,
                is_template, from_template_id, created_by
            ) VALUES (
                :tenant_id, :name, :slug, :type, :description,
                :prompt_a, :prompt_b, :consent_message, :voice_name, :language,
                :voice_engine, :ai_provider, :output_config, :voice_provider_config,
                :custom_variables_schema, :custom_variables,
                FALSE, :template_id, :created_by
            ) RETURNING id
            """,
            {
                "tenant_id": str(current_user.tenant_id),
                "name": name,
                "slug": slug,
                "type": template["type"],
                "description": description or template["description"],
                "prompt_a": template["prompt_a"],
                "prompt_b": template["prompt_b"],
                "consent_message": template["consent_message"],
                "voice_name": template["voice_name"],
                "language": template["language"],
                "voice_engine": template["voice_engine"],
                "ai_provider": template["ai_provider"],
                "output_config": json.dumps(template_output_config or {}),
                "voice_provider_config": json.dumps(template["voice_provider_config"] or {})
                    if not isinstance(template["voice_provider_config"], str)
                    else template["voice_provider_config"],
                "custom_variables_schema": json.dumps(template_schema or []),
                "custom_variables": json.dumps(new_values),
                "template_id": str(template_id),
                "created_by": str(current_user.id),
            }
        )

        # Default prompt placeholders - the one bootstrap row a new
        # project actually needs up front (CRM/calendar config rows are
        # upserted lazily by their own save endpoints, no need to
        # pre-create empty ones here).
        await db.execute(
            "INSERT INTO prompt_placeholders (project_id) VALUES (:project_id) ON CONFLICT DO NOTHING",
            {"project_id": str(project_id)}
        )

    # Return created project
    project = await db.fetch_one("SELECT * FROM projects WHERE id = :id", {"id": str(project_id)})
    return _serialize_project(project)


@router.get("/projects/{project_identifier}", response_model=Project)
async def get_project(
    project_identifier: str,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user", "user"])),
):
    """
    Get project by ID (UUID) or slug.

    Args:
        project_identifier: Project UUID or slug

    Returns:
        Project details

    Raises:
        404: Project not found (also returned if it belongs to another tenant)
    """
    db = get_database()

    # Try to parse as UUID first
    try:
        from uuid import UUID
        project_uuid = UUID(project_identifier)
        project = await db.fetch_one(
            "SELECT * FROM projects WHERE id = :id",
            {"id": str(project_uuid)}
        )
    except (ValueError, AttributeError):
        # Not a UUID, treat as slug
        project = await db.fetch_one(
            "SELECT * FROM projects WHERE slug = :slug",
            {"slug": project_identifier}
        )

    if not project or not check_tenant_access(current_user, project["tenant_id"]):
        raise HTTPException(status_code=404, detail=f"Project not found: {project_identifier}")

    return _serialize_project(project)


@router.post("/projects", response_model=Project, status_code=status.HTTP_201_CREATED)
async def create_project(
    project_data: ProjectCreate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Create a new project.
    """
    db = get_database()

    # Validate slug uniqueness
    existing = await db.fetch_one(
        "SELECT id FROM projects WHERE slug = :slug",
        {"slug": project_data.slug},
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Project slug already exists: {project_data.slug}",
        )

    now = datetime.now(timezone.utc)
    try:
        validate_openai_realtime_model(project_data.voice_provider_config)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    output_config_value = project_data.output_config
    output_config_json = json.dumps(output_config_value) if output_config_value is not None else "{}"

    # Create project
    try:
        created = await db.fetch_one(
            """
        INSERT INTO projects (
            name, slug, type, description, is_active,
            prompt_a, prompt_b, consent_message,
            voice_name, language, output_config,
            sip_number, openai_project_id,
            voice_engine, call_direction, vapi_assistant_id,
            twilio_phone_number, vapi_phone_number_id, elevenlabs_voice_id,
            voice_provider_config,
            tenant_id, created_by, created_at, updated_at
        )
        VALUES (
            :name, :slug, :type, :description, :is_active,
            :prompt_a, :prompt_b, :consent_message,
            :voice_name, :language, :output_config,
            :sip_number, :openai_project_id,
            :voice_engine, :call_direction, :vapi_assistant_id,
            :twilio_phone_number, :vapi_phone_number_id, :elevenlabs_voice_id,
            :voice_provider_config,
            :tenant_id, :created_by, :created_at, :updated_at
        )
        RETURNING *
            """,
            {
            "name": project_data.name,
            "slug": project_data.slug,
            "type": project_data.type.value,
            "description": project_data.description,
            "is_active": project_data.is_active,
            "prompt_a": project_data.prompt_a,
            "prompt_b": project_data.prompt_b,
            "consent_message": project_data.consent_message,
            "voice_name": project_data.voice_name,
            "language": project_data.language,
            "output_config": output_config_json,
            "sip_number": project_data.sip_number,
            "openai_project_id": project_data.openai_project_id,
            "voice_engine": project_data.voice_engine.value,
            "call_direction": project_data.call_direction.value,
            "vapi_assistant_id": project_data.vapi_assistant_id,
            "twilio_phone_number": project_data.twilio_phone_number,
            "vapi_phone_number_id": project_data.vapi_phone_number_id,
            "elevenlabs_voice_id": project_data.elevenlabs_voice_id,
            "voice_provider_config": json.dumps(project_data.voice_provider_config or {}),
            "tenant_id": str(current_user.tenant_id) if current_user.tenant_id else None,
            "created_by": str(current_user.id),
            "created_at": now,
            "updated_at": now,
            },
        )
    except UniqueViolationError as exc:
        if "projects_slug_key" in str(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Lo slug '{project_data.slug}' è già utilizzato. Scegline uno diverso.",
            ) from exc
        raise

    # Seed prompt version 1 for A and B as active (required by prompt history UI)
    await db.execute(
        """
        INSERT INTO prompt_versions (project_id, prompt_type, version, content, is_active, created_by, created_at)
        VALUES (:project_id, 'A', 1, :content, TRUE, :created_by, :created_at)
        ON CONFLICT (project_id, prompt_type, version) DO NOTHING
        """,
        {
            "project_id": str(created["id"]),
            "content": project_data.prompt_a,
            "created_by": str(current_user.id),
            "created_at": now,
        },
    )
    await db.execute(
        """
        INSERT INTO prompt_versions (project_id, prompt_type, version, content, is_active, created_by, created_at)
        VALUES (:project_id, 'B', 1, :content, TRUE, :created_by, :created_at)
        ON CONFLICT (project_id, prompt_type, version) DO NOTHING
        """,
        {
            "project_id": str(created["id"]),
            "content": project_data.prompt_b,
            "created_by": str(current_user.id),
            "created_at": now,
        },
    )

    logger.info(f"Project created: {created['id']} by {current_user.email}")
    return _serialize_project(created)


@router.patch("/projects/{project_id}", response_model=Project)
async def update_project(
    project_id: UUID,
    project_data: ProjectUpdate,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Update an existing project.
    """
    db = get_database()

    existing = await db.fetch_one(
        "SELECT id, tenant_id FROM projects WHERE id = :project_id",
        {"project_id": str(project_id)},
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    tenant_id = UUID(str(existing["tenant_id"])) if existing["tenant_id"] else None
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    update_data = project_data.model_dump(exclude_unset=True)
    if not update_data:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

    if "voice_engine" in update_data and update_data["voice_engine"] is not None:
        update_data["voice_engine"] = update_data["voice_engine"].value
    if "call_direction" in update_data and update_data["call_direction"] is not None:
        update_data["call_direction"] = update_data["call_direction"].value
    if "output_config" in update_data and update_data["output_config"] is not None:
        update_data["output_config"] = json.dumps(update_data["output_config"])
    if "custom_variables_schema" in update_data and update_data["custom_variables_schema"] is not None:
        update_data["custom_variables_schema"] = json.dumps(update_data["custom_variables_schema"])
    if "custom_variables" in update_data and update_data["custom_variables"] is not None:
        update_data["custom_variables"] = json.dumps(update_data["custom_variables"])
    if "voice_provider_config" in update_data and update_data["voice_provider_config"] is not None:
        try:
            validate_openai_realtime_model(update_data["voice_provider_config"])
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        update_data["voice_provider_config"] = json.dumps(update_data["voice_provider_config"])

    set_clauses = []
    params = {"project_id": str(project_id), "updated_at": datetime.now(timezone.utc)}
    for field, value in update_data.items():
        set_clauses.append(f"{field} = :{field}")
        params[field] = value
    set_clauses.append("updated_at = :updated_at")

    updated = await db.fetch_one(
        f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = :project_id RETURNING *",
        params,
    )

    logger.info(f"Project updated: {project_id} by {current_user.email}")
    return _serialize_project(updated)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Soft-delete a project by setting is_active to FALSE.
    """
    db = get_database()

    existing = await db.fetch_one(
        "SELECT id, slug, tenant_id FROM projects WHERE id = :project_id",
        {"project_id": str(project_id)},
    )
    if not existing:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    if existing["slug"] == "default":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Default project cannot be deactivated",
        )

    tenant_id = UUID(str(existing["tenant_id"])) if existing["tenant_id"] else None
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied to this project",
        )

    await db.execute(
        "UPDATE projects SET is_active = FALSE, updated_at = :updated_at WHERE id = :project_id",
        {"updated_at": datetime.now(timezone.utc), "project_id": str(project_id)},
    )

    logger.info(f"Project deactivated: {project_id} by {current_user.email}")
    return {"success": True, "message": "Project deactivated"}


# ===========================================
# Calls
# ===========================================

@router.get("/projects/{slug}/calls", response_model=List[Call])
async def list_project_calls(
    slug: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    List calls for a specific project.

    Args:
        slug: Project slug
        status: Optional status filter
        limit: Max results (default: 50, max: 500)
        offset: Pagination offset (default: 0)

    Returns:
        List of calls for the project
    """
    db = get_database()

    # Get project ID
    project = await db.fetch_one(
        "SELECT id, tenant_id FROM projects WHERE slug = :slug",
        {"slug": slug}
    )

    if not project or not check_tenant_access(current_user, project["tenant_id"]):
        raise HTTPException(status_code=404, detail=f"Project not found: {slug}")

    # Build query
    query = """
        SELECT *
        FROM calls
        WHERE project_id = :project_id
    """
    params = {"project_id": str(project["id"]), "limit": limit, "offset": offset}

    if status:
        query += " AND status = :status"
        params["status"] = status

    query += " ORDER BY started_at DESC LIMIT :limit OFFSET :offset"

    calls = await db.fetch_all(query, params)

    return [dict(c) for c in calls]


@router.get("/calls", response_model=List[Call])
async def list_all_calls(
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    List calls (across all projects in the current user's tenant; every
    tenant for super_admin).

    Args:
        status: Optional status filter
        limit: Max results (default: 50, max: 500)
        offset: Pagination offset (default: 0)

    Returns:
        List of calls
    """
    db = get_database()

    conditions = []
    params = {"limit": limit, "offset": offset}

    if status:
        conditions.append("status = :status")
        params["status"] = status

    if not current_user.is_super_admin:
        conditions.append("tenant_id = :tenant_id")
        params["tenant_id"] = str(current_user.tenant_id)

    where_clause = "WHERE " + " AND ".join(conditions) if conditions else ""
    query = f"SELECT * FROM calls {where_clause} ORDER BY started_at DESC LIMIT :limit OFFSET :offset"

    calls = await db.fetch_all(query, params)

    return [dict(c) for c in calls]


@router.get("/calls/{call_id}", response_model=CallComplete)
async def get_call(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    Get detailed call information.

    Includes:
    - Call metadata
    - Full transcript
    - Project info
    - Extracted JSON (if processed)

    Args:
        call_id: Call UUID

    Returns:
        Complete call details

    Raises:
        404: Call not found (also returned if it belongs to another tenant)
    """
    db = get_database()

    # Fetch call
    call = await db.fetch_one(
        "SELECT * FROM calls WHERE id = :id",
        {"id": str(call_id)}
    )

    if not call or not check_tenant_access(current_user, call["tenant_id"]):
        raise HTTPException(status_code=404, detail="Call not found")

    call_dict = dict(call)

    # Fetch project (if linked)
    project = None
    if call_dict.get("project_id"):
        project_row = await db.fetch_one(
            "SELECT * FROM projects WHERE id = :id",
            {"id": str(call_dict["project_id"])}
        )
        if project_row:
            project = dict(project_row)

    # Fetch transcripts
    transcripts = await db.fetch_all(
        """
        SELECT * FROM transcripts
        WHERE call_id = :call_id
        ORDER BY timestamp ASC
        """,
        {"call_id": str(call_id)}
    )

    # Fetch record (if exists)
    record = None
    record_row = await db.fetch_one(
        "SELECT * FROM records WHERE call_id = :call_id",
        {"call_id": str(call_id)}
    )
    if record_row:
        record = dict(record_row)

    return {
        **call_dict,
        "project": project,
        "transcripts": [dict(t) for t in transcripts],
        "record": record
    }


# ===========================================
# Records & PDFs
# ===========================================

@router.get("/calls/{call_id}/record", response_model=Record)
async def get_call_record(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    Get extracted JSON record for a call.

    Args:
        call_id: Call UUID

    Returns:
        Record with JSON data

    Raises:
        404: Record not found
    """
    await _assert_call_access(call_id, current_user)
    db = get_database()

    record = await db.fetch_one(
        "SELECT * FROM records WHERE call_id = :call_id",
        {"call_id": str(call_id)}
    )

    if not record:
        raise HTTPException(
            status_code=404,
            detail="No record found for this call. Call may not be processed yet."
        )

    return dict(record)


@router.get("/calls/{call_id}/pdf")
async def download_pdf(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    Download PDF report for a call.

    Args:
        call_id: Call UUID

    Returns:
        PDF file as streaming response

    Raises:
        404: PDF not found
        500: Download failed
    """
    await _assert_call_access(call_id, current_user)
    pdf_generator = PDFGenerator()

    try:
        pdf_bytes = await pdf_generator.download_pdf(call_id)

        return StreamingResponse(
            iter([pdf_bytes]),
            media_type="application/pdf",
            headers={
                "Content-Disposition": f"attachment; filename=candidate_{call_id}.pdf"
            }
        )

    except PDFGeneratorError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=str(e))


@router.post("/calls/{call_id}/reprocess")
async def reprocess_call(
    call_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
):
    """
    Regenerate JSON extraction and PDF for a call.

    Useful for:
    - Fixing extraction errors
    - Testing new Prompt B versions
    - Updating data after manual edits

    Args:
        call_id: Call UUID

    Returns:
        Success message with new record ID

    Raises:
        404: Call not found
        500: Processing failed
    """
    await _assert_call_access(call_id, current_user)
    logger.info(f"Manual reprocess requested for call {call_id} by {current_user.email}")

    try:
        # 1. Reprocess JSON
        post_processor = PostProcessor()
        json_data = await post_processor.reprocess_call(call_id)

        # 2. Regenerate PDF
        pdf_generator = PDFGenerator()
        s3_key = await pdf_generator.regenerate_pdf(call_id)

        return {
            "status": "success",
            "message": "Call reprocessed successfully",
            "call_id": str(call_id),
            "pdf_key": s3_key,
            "json_fields": list(json_data.keys())
        }

    except PostProcessingError as e:
        if "not found" in str(e).lower():
            raise HTTPException(status_code=404, detail=str(e))
        else:
            raise HTTPException(status_code=500, detail=f"Reprocessing failed: {e}")

    except PDFGeneratorError as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")


# ===========================================
# Statistics
# ===========================================

@router.get("/stats")
async def get_stats(
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user"])),
):
    """
    Get statistics for the current user's tenant (system-wide for super_admin).

    Returns:
        Stats including call counts, status breakdown, etc.
    """
    db = get_database()

    if current_user.is_super_admin:
        tenant_where = ""
        params: dict = {}
    else:
        tenant_where = "WHERE tenant_id = :tenant_id"
        params = {"tenant_id": str(current_user.tenant_id)}

    # Total calls
    total = await db.fetch_one(f"SELECT COUNT(*) as count FROM calls {tenant_where}", params)

    # By status
    by_status = await db.fetch_all(
        f"""
        SELECT status, COUNT(*) as count
        FROM calls
        {tenant_where}
        GROUP BY status
        ORDER BY count DESC
        """,
        params,
    )

    # By project
    by_project = await db.fetch_all(
        f"""
        SELECT
            COALESCE(p.name, 'Unassigned') as project_name,
            COUNT(c.id) as call_count
        FROM calls c
        LEFT JOIN projects p ON c.project_id = p.id
        {tenant_where.replace("tenant_id", "c.tenant_id")}
        GROUP BY p.name
        ORDER BY call_count DESC
        """,
        params,
    )

    # Recent activity (last 7 days)
    recent_where = "started_at >= NOW() - INTERVAL '7 days'"
    if not current_user.is_super_admin:
        recent_where += " AND tenant_id = :tenant_id"
    recent = await db.fetch_all(
        f"""
        SELECT
            DATE(started_at) as date,
            COUNT(*) as calls
        FROM calls
        WHERE {recent_where}
        GROUP BY DATE(started_at)
        ORDER BY date DESC
        """,
        params,
    )

    return {
        "total_calls": total["count"] if total else 0,
        "by_status": {row["status"]: row["count"] for row in by_status},
        "by_project": [dict(row) for row in by_project],
        "recent_activity": [dict(row) for row in recent]
    }
