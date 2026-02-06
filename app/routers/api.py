"""
Ascolta - API Routes (M2)
Project-aware RESTful API for call data and PDF access
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Response
from fastapi.responses import StreamingResponse

import json

from app.database.db import get_database
from app.models.schemas import (
    Call,
    CallComplete,
    Project,
    Record,
    RecordWithCall,
)
from app.services.pdf_generator import PDFGenerator, PDFGeneratorError
from app.services.post_processor import PostProcessor, PostProcessingError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["api"])


# ===========================================
# Projects
# ===========================================

@router.get("/projects", response_model=List[Project])
async def list_projects(
    active_only: bool = Query(True, description="Only return active projects")
):
    """
    List all projects.

    Args:
        active_only: Filter to active projects only (default: True)

    Returns:
        List of projects
    """
    db = get_database()

    query = "SELECT * FROM projects"
    if active_only:
        query += " WHERE is_active = TRUE"
    query += " ORDER BY created_at DESC"

    projects = await db.fetch_all(query)

    result = []
    for p in projects:
        item = dict(p)
        output_config = item.get("output_config")
        if isinstance(output_config, str):
            try:
                item["output_config"] = json.loads(output_config)
            except json.JSONDecodeError:
                item["output_config"] = {}
        result.append(item)

    return result


@router.get("/projects/{project_identifier}", response_model=Project)
async def get_project(project_identifier: str):
    """
    Get project by ID (UUID) or slug.

    Args:
        project_identifier: Project UUID or slug

    Returns:
        Project details

    Raises:
        404: Project not found
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

    if not project:
        raise HTTPException(status_code=404, detail=f"Project not found: {project_identifier}")

    item = dict(project)
    output_config = item.get("output_config")
    if isinstance(output_config, str):
        try:
            item["output_config"] = json.loads(output_config)
        except json.JSONDecodeError:
            item["output_config"] = {}
    return item


# ===========================================
# Calls
# ===========================================

@router.get("/projects/{slug}/calls", response_model=List[Call])
async def list_project_calls(
    slug: str,
    status: Optional[str] = Query(None, description="Filter by status"),
    limit: int = Query(50, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Pagination offset")
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
        "SELECT id FROM projects WHERE slug = :slug",
        {"slug": slug}
    )

    if not project:
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
    offset: int = Query(0, ge=0, description="Pagination offset")
):
    """
    List all calls (across all projects).

    Args:
        status: Optional status filter
        limit: Max results (default: 50, max: 500)
        offset: Pagination offset (default: 0)

    Returns:
        List of calls
    """
    db = get_database()

    query = "SELECT * FROM calls"
    params = {"limit": limit, "offset": offset}

    if status:
        query += " WHERE status = :status"
        params["status"] = status

    query += " ORDER BY started_at DESC LIMIT :limit OFFSET :offset"

    calls = await db.fetch_all(query, params)

    return [dict(c) for c in calls]


@router.get("/calls/{call_id}", response_model=CallComplete)
async def get_call(call_id: UUID):
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
        404: Call not found
    """
    db = get_database()

    # Fetch call
    call = await db.fetch_one(
        "SELECT * FROM calls WHERE id = :id",
        {"id": str(call_id)}
    )

    if not call:
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
async def get_call_record(call_id: UUID):
    """
    Get extracted JSON record for a call.

    Args:
        call_id: Call UUID

    Returns:
        Record with JSON data

    Raises:
        404: Record not found
    """
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
async def download_pdf(call_id: UUID):
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
async def reprocess_call(call_id: UUID):
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
    logger.info(f"Manual reprocess requested for call {call_id}")

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
async def get_stats():
    """
    Get system-wide statistics.

    Returns:
        Stats including call counts, status breakdown, etc.
    """
    db = get_database()

    # Total calls
    total = await db.fetch_one("SELECT COUNT(*) as count FROM calls")

    # By status
    by_status = await db.fetch_all(
        """
        SELECT status, COUNT(*) as count
        FROM calls
        GROUP BY status
        ORDER BY count DESC
        """
    )

    # By project
    by_project = await db.fetch_all(
        """
        SELECT
            COALESCE(p.name, 'Unassigned') as project_name,
            COUNT(c.id) as call_count
        FROM calls c
        LEFT JOIN projects p ON c.project_id = p.id
        GROUP BY p.name
        ORDER BY call_count DESC
        """
    )

    # Recent activity (last 7 days)
    recent = await db.fetch_all(
        """
        SELECT
            DATE(started_at) as date,
            COUNT(*) as calls
        FROM calls
        WHERE started_at >= NOW() - INTERVAL '7 days'
        GROUP BY DATE(started_at)
        ORDER BY date DESC
        """
    )

    return {
        "total_calls": total["count"] if total else 0,
        "by_status": {row["status"]: row["count"] for row in by_status},
        "by_project": [dict(row) for row in by_project],
        "recent_activity": [dict(row) for row in recent]
    }
