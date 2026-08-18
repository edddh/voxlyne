"""
Ascolta - Agent version snapshot and inbound resolver (Fase 2 kernel).

Doesn't replace `projects` (see ADR-0001: reuse the working project model,
don't rewrite it) - snapshots it. A project keeps being where an admin
edits prompt/voice/language; publish_version() freezes that state into an
immutable agent_versions row, and the inbound resolver reads only from
published versions, never from the live-editable project row directly.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from app.database.db import get_database

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
               voice_name, language, voice_engine, output_config
        FROM projects WHERE id = :id
        """,
        {"id": str(project_id)},
    )
    if not project:
        raise ValueError(f"Project not found: {project_id}")

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
                voice_engine, output_config, published_at, created_by
            ) VALUES (
                :project_id, :tenant_id, :version_number, 'published',
                :prompt_a, :prompt_b, :consent_message, :voice_name, :language,
                :voice_engine, :output_config, :now, :created_by
            ) RETURNING id
            """,
            {
                "project_id": str(project_id),
                "tenant_id": str(project["tenant_id"]) if project["tenant_id"] else None,
                "version_number": next_version,
                "prompt_a": project["prompt_a"],
                "prompt_b": project["prompt_b"],
                "consent_message": project["consent_message"],
                "voice_name": project["voice_name"],
                "language": project["language"],
                "voice_engine": project["voice_engine"],
                "output_config": project["output_config"],
                "now": now,
                "created_by": str(created_by) if created_by else None,
            },
        )

    logger.info(f"Agent version published: project={project_id} version={next_version} id={new_id}")
    return {"id": new_id, "version_number": next_version}


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
                   v.voice_name, v.language, v.voice_engine
            FROM inbound_endpoints e
            LEFT JOIN agent_versions v
                ON v.project_id = e.project_id AND v.status = 'published'
            WHERE e.identifier = :identifier AND e.is_active = TRUE
            """,
            {"identifier": identifier},
        )
    return dict(row) if row else None
