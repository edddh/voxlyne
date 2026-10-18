"""
Ascolta - Agent version snapshot and inbound resolver (Fase 2 kernel).

Doesn't replace `projects` (see ADR-0001: reuse the working project model,
don't rewrite it) - snapshots it. A project keeps being where an admin
edits prompt/voice/language; publish_version() freezes that state into an
immutable agent_versions row, and the inbound resolver reads only from
published versions, never from the live-editable project row directly.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from app.database.db import get_database
from app.services.prompt_variables import substitute_custom_variables
from app.services.demo_showcase import is_demo_tenant


async def resolve_provider_api_key(
    tenant_id: Any, provider: str, project_id: Any = None,
) -> Optional[str]:
    """
    Strictly per-tenant, no fallback to a global env var - explicit request
    from maintainer, 18/08 (see .env: "XAI_API_KEY volutamente NON qui").
    Shared by runtime_workers/livekit_agent.py and realtime_service.py -
    every voice worker resolves provider credentials the same way.

    Uses CredentialsManager._fetch_db_credentials(), not get_credentials()/
    get_credentials_with_fallback() - those two fall back to os.environ,
    which is exactly what must not happen here. None means "this tenant
    has no voice/{provider} credential stored", and the caller must treat
    that as a hard failure (decline the call), not silently reuse another
    tenant's key or a global one.
    """
    if not tenant_id or is_demo_tenant(tenant_id):
        return None
    from app.services.credentials.manager import CredentialsManager

    manager = CredentialsManager()
    if project_id:
        project_creds = await manager._fetch_db_credentials(
            entity_type="project", entity_id=project_id,
            service_type="voice", provider=provider,
        )
        if project_creds:
            return project_creds.get("api_key")
    creds = await manager._fetch_db_credentials(
        entity_type="tenant", entity_id=tenant_id, service_type="voice", provider=provider,
    )
    return creds.get("api_key") if creds else None

logger = logging.getLogger(__name__)


async def publish_version(project_id: UUID, created_by: Optional[UUID] = None) -> Dict[str, Any]:
    """
    Snapshot the current state of a project into a new, immutable, published
    agent_version. Deactivates (archives) whatever was published before -
    exactly one published version per project at a time (enforced by the
    partial unique index in the migration, not just by this function).

    Runs inside the caller's already-open RLS transaction (project_config
    router, etc.) - no bypass here, unlike the resolver below, because this
    is always called from an authenticated request that already has
    app.tenant_id set.
    """
    db = get_database()

    project = await db.fetch_one(
        """
        SELECT id, tenant_id, prompt_a, prompt_b, consent_message,
               voice_name, language, voice_engine, output_config,
               custom_variables
        FROM projects WHERE id = :id
        """,
        {"id": str(project_id)},
    )
    if not project:
        raise ValueError(f"Project not found: {project_id}")

    # {{key}} custom variable substitution happens exactly once, right
    # here - the draft on `projects` keeps its {{key}} markers forever
    # (so a value can be edited later, Progetti > Variabili tab, without
    # touching the prompt text), the published snapshot gets the final
    # literal text. {{system__xxx}} tags are left untouched for the
    # voice provider to resolve (see app/services/prompt_variables.py).
    custom_variables = project["custom_variables"]
    if isinstance(custom_variables, str):
        try:
            custom_variables = json.loads(custom_variables)
        except json.JSONDecodeError:
            custom_variables = {}
    prompt_a = substitute_custom_variables(project["prompt_a"], custom_variables)
    prompt_b = substitute_custom_variables(project["prompt_b"], custom_variables)
    consent_message = substitute_custom_variables(project["consent_message"], custom_variables)

    async with db.transaction():
        next_version = await db.fetch_val(
            "SELECT COALESCE(MAX(version_number), 0) + 1 FROM agent_versions WHERE project_id = :id",
            {"id": str(project_id)},
        )
        await db.execute(
            "UPDATE agent_versions SET status = 'archived' WHERE project_id = :id AND status = 'published'",
            {"id": str(project_id)},
        )
        now = datetime.now(timezone.utc)
        new_id = await db.fetch_val(
            """
            INSERT INTO agent_versions (
                project_id, tenant_id, version_number, status,
                prompt_a, prompt_b, consent_message, voice_name, language,
                voice_engine, output_config, custom_variables, published_at, created_by
            ) VALUES (
                :project_id, :tenant_id, :version_number, 'published',
                :prompt_a, :prompt_b, :consent_message, :voice_name, :language,
                :voice_engine, :output_config, :custom_variables, :now, :created_by
            ) RETURNING id
            """,
            {
                "project_id": str(project_id),
                "tenant_id": str(project["tenant_id"]) if project["tenant_id"] else None,
                "version_number": next_version,
                "prompt_a": prompt_a,
                "prompt_b": prompt_b,
                "consent_message": consent_message,
                "voice_name": project["voice_name"],
                "language": project["language"],
                "voice_engine": project["voice_engine"],
                "output_config": project["output_config"],
                "custom_variables": json.dumps(custom_variables or {}),
                "now": now,
                "created_by": str(created_by) if created_by else None,
            },
        )

    logger.info(f"Agent version published: project={project_id} version={next_version} id={new_id}")
    return {"id": new_id, "version_number": next_version}


async def list_versions(project_id: UUID) -> list[Dict[str, Any]]:
    """All versions of a project (draft/published/archived), newest first."""
    db = get_database()
    rows = await db.fetch_all(
        """
        SELECT id, version_number, status, prompt_a, prompt_b, consent_message,
               voice_name, language, voice_engine, published_at, created_by, created_at
        FROM agent_versions
        WHERE project_id = :project_id
        ORDER BY version_number DESC
        """,
        {"project_id": str(project_id)},
    )
    return [dict(r) for r in rows]


async def rollback_to_version(project_id: UUID, version_id: UUID) -> Dict[str, Any]:
    """
    Make an existing (already-published-at-some-point, i.e. not still a
    draft) version the active one again - instant, no new version_number,
    no snapshot re-taken. Does NOT touch the live `projects` row: rollback
    changes what resolve_inbound() serves right now, it doesn't discard
    whatever draft edits an admin currently has open in the project editor.
    """
    db = get_database()
    async with db.transaction():
        target = await db.fetch_one(
            "SELECT id, project_id, status FROM agent_versions WHERE id = :id AND project_id = :project_id",
            {"id": str(version_id), "project_id": str(project_id)},
        )
        if not target:
            raise ValueError(f"Version not found: {version_id}")
        if target["status"] == "draft":
            raise ValueError("Cannot roll back to a version that was never published")

        await db.execute(
            "UPDATE agent_versions SET status = 'archived' WHERE project_id = :id AND status = 'published'",
            {"id": str(project_id)},
        )
        await db.execute(
            "UPDATE agent_versions SET status = 'published', published_at = now() WHERE id = :id",
            {"id": str(version_id)},
        )

    logger.info(f"Rolled back: project={project_id} -> version={version_id}")
    return {"id": str(version_id), "status": "published"}


async def resolve_inbound(identifier: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a dialed SIP identifier (the "To" header, or a phone number for
    other transports) to the tenant/project/published-version that should
    answer. Returns None if there's no matching, active endpoint, or the
    matched project has no published version - callers must have an
    explicit fallback policy for that case (see ADR-0001 rule 9: "il
    sistema applica una fallback policy esplicita e tracciata, non un
    default globale nascosto"), not treat None as "use the global default"
    silently.

    Runs with an explicit RLS bypass: this is called from webhook.py before
    any user/tenant is known - the whole point of this function is to
    figure out the tenant from the dialed number, so it can't itself
    require app.tenant_id to already be set. See the identical pattern (and
    the incident it fixes) in auth_service.authenticate_user.
    """
    db = get_database()
    async with db.transaction():
        await db.execute("SELECT set_config('app.is_super_admin', 'true', true)")
        row = await db.fetch_one(
            """
            SELECT e.tenant_id, e.project_id, v.id AS agent_version_id,
                   v.version_number, v.prompt_a, v.prompt_b, v.consent_message,
                   v.voice_name, v.language, v.voice_engine,
                   p.voice_provider_config
            FROM inbound_endpoints e
            JOIN projects p ON p.id = e.project_id
            LEFT JOIN agent_versions v
                ON v.project_id = e.project_id AND v.status = 'published'
            WHERE e.identifier = :identifier AND e.is_active = TRUE
            """,
            {"identifier": identifier},
        )
    return dict(row) if row else None
