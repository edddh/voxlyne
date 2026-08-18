"""
Ascolta - Knowledge base (RAG) admin API.

Answers maintainer's request (18/08): "mi piacerebbe poter lavorare sulla
funzione RAG e avere la base dati dal crawl del comune di Exampleville" -
generalized per his explicit instruction ("se ti chiedo la RAG del
comune di Exampleville significa che devi generalizzare la mia richiesta in
maniera da ottenerla tramite configurazione del pannello admin"): this is
a per-project knowledge base any tenant can populate from the admin UI,
Exampleville is just the first one to use it, not a hardcoded case.

Indexing (crawl or file parsing + chunking + embedding) runs as a
background asyncio task kicked off here, not inline in the request - a
crawl of 20 pages can take way longer than an HTTP request should block
for. The client polls GET .../sources for status (pending -> processing
-> indexed|failed), same pattern as the rest of this app (no websocket/
SSE progress channel built for this - a poll every few seconds from the
UI is enough for the Fase 3 scope this is landing in).
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field

from app.database.db import get_database
from app.middleware.auth_middleware import CurrentUser, check_tenant_access, require_roles
from app.services.rag import search as rag_search
from app.services.rag.extractors import extract_upload_text
from app.services.rag.indexer import index_upload_source, index_url_source

logger = logging.getLogger(__name__)
router = APIRouter()


async def _project_context(project_id: UUID, current_user: CurrentUser) -> Dict[str, Any]:
    db = get_database()
    project = await db.fetch_one(
        "SELECT id, tenant_id FROM projects WHERE id = :id", {"id": str(project_id)},
    )
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    tenant_id = UUID(str(project["tenant_id"])) if project["tenant_id"] else None
    if not check_tenant_access(current_user, tenant_id):
        raise HTTPException(status_code=403, detail="Access denied to this project")
    return {"project_id": project_id, "tenant_id": tenant_id}


class AddUrlSourceRequest(BaseModel):
    url: str = Field(..., description="Starting URL to crawl, e.g. https://www.comune.exampleville.it")
    max_pages: int = Field(default=20, ge=1, le=200)
    recrawl_interval_hours: Optional[int] = Field(
        default=None, ge=1,
        description="Se impostato, il crawl si ripete automaticamente ogni N ore. Vuoto = solo una volta (reindex manuale in seguito).",
    )


class UpdateScheduleRequest(BaseModel):
    recrawl_interval_hours: Optional[int] = Field(default=None, ge=1)


@router.post("/projects/{project_id}/kb/sources/url", status_code=status.HTTP_201_CREATED)
async def add_url_source(
    project_id: UUID,
    body: AddUrlSourceRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> Dict[str, Any]:
    ctx = await _project_context(project_id, current_user)
    db = get_database()
    row = await db.fetch_one(
        """
        INSERT INTO kb_sources (project_id, tenant_id, source_type, url, crawl_max_pages, recrawl_interval_hours, status, created_by)
        VALUES (:project_id, :tenant_id, 'url', :url, :max_pages, :recrawl_interval_hours, 'pending', :created_by)
        RETURNING id
        """,
        {
            "project_id": str(project_id),
            "tenant_id": str(ctx["tenant_id"]) if ctx["tenant_id"] else None,
            "url": body.url,
            "max_pages": body.max_pages,
            "recrawl_interval_hours": body.recrawl_interval_hours,
            "created_by": str(current_user.id),
        },
    )
    source_id = row["id"]

    asyncio.create_task(
        index_url_source(source_id, project_id, ctx["tenant_id"], body.url, body.max_pages)
    )

    return {"id": str(source_id), "status": "pending"}


@router.patch("/projects/{project_id}/kb/sources/{source_id}/schedule")
async def update_schedule(
    project_id: UUID,
    source_id: UUID,
    body: UpdateScheduleRequest,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> Dict[str, Any]:
    await _project_context(project_id, current_user)
    db = get_database()
    row = await db.fetch_one(
        """
        UPDATE kb_sources SET recrawl_interval_hours = :interval,
            next_crawl_at = CASE WHEN :interval IS NOT NULL AND indexed_at IS NOT NULL
                THEN indexed_at + (:interval || ' hours')::interval ELSE NULL END
        WHERE id = :id AND project_id = :project_id AND source_type = 'url'
        RETURNING id, recrawl_interval_hours, next_crawl_at
        """,
        {"interval": body.recrawl_interval_hours, "id": str(source_id), "project_id": str(project_id)},
    )
    if not row:
        raise HTTPException(status_code=404, detail="Source not found or not a URL source")
    return dict(row)


@router.post("/projects/{project_id}/kb/sources/upload", status_code=status.HTTP_201_CREATED)
async def add_upload_source(
    project_id: UUID,
    file: UploadFile = File(...),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> Dict[str, Any]:
    ctx = await _project_context(project_id, current_user)
    data = await file.read()
    try:
        text = extract_upload_text(file.filename, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not text.strip():
        raise HTTPException(status_code=400, detail="Nessun testo estraibile da questo file")

    db = get_database()
    row = await db.fetch_one(
        """
        INSERT INTO kb_sources (project_id, tenant_id, source_type, filename, status, created_by)
        VALUES (:project_id, :tenant_id, 'upload', :filename, 'pending', :created_by)
        RETURNING id
        """,
        {
            "project_id": str(project_id),
            "tenant_id": str(ctx["tenant_id"]) if ctx["tenant_id"] else None,
            "filename": file.filename,
            "created_by": str(current_user.id),
        },
    )
    source_id = row["id"]

    asyncio.create_task(
        index_upload_source(source_id, project_id, ctx["tenant_id"], file.filename, text)
    )

    return {"id": str(source_id), "status": "pending"}


@router.get("/projects/{project_id}/kb/sources")
async def list_sources(
    project_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user", "user"])),
) -> Dict[str, List[Dict[str, Any]]]:
    await _project_context(project_id, current_user)
    db = get_database()
    rows = await db.fetch_all(
        """
        SELECT id, source_type, url, filename, status, error, chunk_count, created_at, indexed_at,
               crawl_max_pages, recrawl_interval_hours, next_crawl_at
        FROM kb_sources WHERE project_id = :project_id ORDER BY created_at DESC
        """,
        {"project_id": str(project_id)},
    )
    return {"sources": [dict(r) for r in rows]}


@router.delete("/projects/{project_id}/kb/sources/{source_id}")
async def delete_source(
    project_id: UUID,
    source_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> Dict[str, str]:
    await _project_context(project_id, current_user)
    db = get_database()
    result = await db.execute(
        "DELETE FROM kb_sources WHERE id = :id AND project_id = :project_id",
        {"id": str(source_id), "project_id": str(project_id)},
    )
    return {"status": "deleted"}


@router.post("/projects/{project_id}/kb/sources/{source_id}/reindex")
async def reindex_source(
    project_id: UUID,
    source_id: UUID,
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator"])),
) -> Dict[str, str]:
    ctx = await _project_context(project_id, current_user)
    db = get_database()
    source = await db.fetch_one(
        "SELECT * FROM kb_sources WHERE id = :id AND project_id = :project_id",
        {"id": str(source_id), "project_id": str(project_id)},
    )
    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    if source["source_type"] == "url":
        asyncio.create_task(
            index_url_source(source_id, project_id, ctx["tenant_id"], source["url"], source["crawl_max_pages"])
        )
    else:
        raise HTTPException(
            status_code=400,
            detail="Il reindex automatico e' disponibile solo per le fonti URL - per un upload, ricarica di nuovo il file.",
        )
    return {"status": "reindexing"}


@router.get("/projects/{project_id}/kb/search")
async def search_kb(
    project_id: UUID,
    q: str = Query(..., min_length=1),
    top_k: int = Query(default=5, ge=1, le=20),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "creator", "power_user", "user"])),
) -> Dict[str, Any]:
    """Manual test/preview endpoint for the admin UI - same search the voice tool uses."""
    ctx = await _project_context(project_id, current_user)
    try:
        results = await rag_search.search_knowledge_base(project_id, ctx["tenant_id"], q, top_k=top_k)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"query": q, "results": results}
