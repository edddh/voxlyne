"""
Ascolta - Analytics API Routes

Dashboard statistics and reporting endpoints.
"""

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.middleware.auth_middleware import (
    CurrentUser,
    TenantContext,
    get_current_user,
    get_tenant_context,
    require_roles,
)
from app.models.schemas import (
    CallTrendResponse,
    DashboardStats,
    ProjectStatsResponse,
)
from app.services.analytics_service import get_analytics_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


@router.get("/dashboard", response_model=DashboardStats)
async def get_dashboard_stats(
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get dashboard statistics.

    Returns counts for calls today/week/month, conversion rate, etc.
    """
    analytics = get_analytics_service()

    stats = await analytics.get_dashboard_stats(tenant_id=tenant_ctx.tenant_id)

    return DashboardStats(**stats)


@router.get("/calls", response_model=CallTrendResponse)
async def get_call_trends(
    period: str = Query("week", regex="^(day|week|month)$"),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get call trends over time.

    Period can be "day", "week", or "month".
    """
    analytics = get_analytics_service()

    trends = await analytics.get_call_trends(
        period=period,
        tenant_id=tenant_ctx.tenant_id,
    )

    return CallTrendResponse(
        points=[
            {
                "date": p["date"],
                "total": p["total"],
                "completed": p["completed"],
                "cancelled": p["cancelled"],
            }
            for p in trends["points"]
        ],
        period=period,
        total_calls=trends["total_calls"],
    )


@router.get("/projects", response_model=List[ProjectStatsResponse])
async def get_project_stats(
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get statistics per project.
    """
    analytics = get_analytics_service()

    stats = await analytics.get_project_stats(tenant_id=tenant_ctx.tenant_id)

    return [
        ProjectStatsResponse(
            project_id=UUID(s["project_id"]),
            project_name=s["project_name"],
            total_calls=s["total_calls"],
            completed_calls=s["completed_calls"],
            conversion_rate=s["conversion_rate"],
            avg_duration_seconds=s["avg_duration_seconds"],
        )
        for s in stats
    ]


@router.get("/calls/by-status")
async def get_calls_by_status(
    days: int = Query(30, ge=1, le=365),
    current_user: CurrentUser = Depends(require_roles(["admin", "super_admin", "power_user"])),
    tenant_ctx: TenantContext = Depends(get_tenant_context),
):
    """
    Get call counts by status for the last N days.
    """
    analytics = get_analytics_service()

    stats = await analytics.get_call_stats_by_status(
        tenant_id=tenant_ctx.tenant_id,
        days=days,
    )

    return {
        "period_days": days,
        "by_status": stats,
        "total": sum(stats.values()),
    }
