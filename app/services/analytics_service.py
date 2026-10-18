"""
Ascolta - Analytics Service

Dashboard statistics and call trend analysis.
"""

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from uuid import UUID

from app.database.db import get_database
from app.services.demo_showcase import DEMO_TENANT_ID

logger = logging.getLogger(__name__)


class AnalyticsService:
    """
    Service for analytics and reporting.

    Features:
    - Dashboard statistics
    - Call trends over time
    - Project-level statistics
    - Completion rate (% of calls reaching status=completed - not a
      sales/lead conversion metric, see maintainer 20/08's rename from
      conversion_rate)
    """

    async def get_dashboard_stats(
        self,
        tenant_id: Optional[UUID] = None,
    ) -> Dict:
        """
        Get dashboard statistics.

        Args:
            tenant_id: Optional tenant filter (None for all tenants)

        Returns:
            Dict with dashboard stats
        """
        db = get_database()

        now = datetime.now(timezone.utc)
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=7)
        month_start = today_start - timedelta(days=30)

        # Build tenant filter
        tenant_filter = "AND c.tenant_id IS DISTINCT FROM :demo_tenant_id"
        base_params = {
            "today_start": today_start,
            "week_start": week_start,
            "month_start": month_start,
            "demo_tenant_id": str(DEMO_TENANT_ID),
        }

        if tenant_id:
            tenant_filter = "AND c.tenant_id = :tenant_id"
            base_params["tenant_id"] = str(tenant_id)
            del base_params["demo_tenant_id"]

        # Calls today
        calls_today = await db.fetch_one(
            f"""
            SELECT
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed' OR status = 'processed') as completed
            FROM calls c
            WHERE c.created_at >= :today_start {tenant_filter}
            """,
            {k: v for k, v in base_params.items() if k in ("today_start", "tenant_id", "demo_tenant_id")},
        )

        # Calls this week
        calls_week = await db.fetch_one(
            f"""
            SELECT COUNT(*) as total
            FROM calls c
            WHERE c.created_at >= :week_start {tenant_filter}
            """,
            {k: v for k, v in base_params.items() if k in ("week_start", "tenant_id", "demo_tenant_id")},
        )

        # Calls this month
        calls_month = await db.fetch_one(
            f"""
            SELECT COUNT(*) as total
            FROM calls c
            WHERE c.created_at >= :month_start {tenant_filter}
            """,
            {k: v for k, v in base_params.items() if k in ("month_start", "tenant_id", "demo_tenant_id")},
        )

        # Average duration (completed calls)
        avg_duration = await db.fetch_one(
            f"""
            SELECT AVG(duration_seconds) as avg_duration
            FROM calls c
            WHERE duration_seconds IS NOT NULL
              AND (status = 'completed' OR status = 'processed')
              {tenant_filter}
            """,
            {k: v for k, v in base_params.items() if k in ("tenant_id", "demo_tenant_id")},
        )

        # Active projects. Was interpolating tenant_id straight into the
        # SQL string (f"... = '{tenant_id}'") instead of binding it like
        # every other filter in this file - tenant_id is always a UUID
        # from the authenticated request context here, never raw user
        # input, so there wasn't an actual injection path, but it's the
        # kind of inconsistency worth fixing on sight (18/08).
        project_filter = "WHERE p.is_active = TRUE AND p.tenant_id IS DISTINCT FROM :demo_tenant_id"
        project_params: Dict = {"demo_tenant_id": str(DEMO_TENANT_ID)}
        if tenant_id:
            project_filter = "WHERE p.is_active = TRUE AND p.tenant_id = :tenant_id"
            project_params = {}
            project_params["tenant_id"] = str(tenant_id)

        active_projects = await db.fetch_one(
            f"SELECT COUNT(*) as count FROM projects p {project_filter}",
            project_params,
        )

        # CRM synced count
        crm_synced = await db.fetch_one(
            f"""
            SELECT COUNT(*) as count
            FROM records r
            JOIN calls c ON r.call_id = c.id
            WHERE r.crm_synced = TRUE {tenant_filter.replace('c.', 'c.')}
            """,
            {k: v for k, v in base_params.items() if k in ("tenant_id", "demo_tenant_id")},
        )

        # Appointments scheduled
        appointments = await db.fetch_one(
            f"""
            SELECT COUNT(*) as count
            FROM records r
            JOIN calls c ON r.call_id = c.id
            WHERE r.appointment_scheduled = TRUE {tenant_filter.replace('c.', 'c.')}
            """,
            {k: v for k, v in base_params.items() if k in ("tenant_id", "demo_tenant_id")},
        )

        # Calculate conversion rate
        total_today = calls_today["total"] or 0
        completed_today = calls_today["completed"] or 0
        completion_rate = (completed_today / total_today * 100) if total_today > 0 else 0.0

        return {
            "total_calls_today": total_today,
            "total_calls_week": calls_week["total"] or 0,
            "total_calls_month": calls_month["total"] or 0,
            "completed_calls_today": completed_today,
            "completion_rate": round(completion_rate, 1),
            "avg_duration_seconds": round(avg_duration["avg_duration"] or 0, 1),
            "active_projects": active_projects["count"] or 0,
            "crm_synced_count": crm_synced["count"] or 0 if crm_synced else 0,
            "appointments_scheduled_count": appointments["count"] or 0 if appointments else 0,
        }

    async def get_call_trends(
        self,
        period: str = "week",
        tenant_id: Optional[UUID] = None,
    ) -> Dict:
        """
        Get call trends over time.

        Args:
            period: "day", "week", or "month"
            tenant_id: Optional tenant filter

        Returns:
            Dict with trend data
        """
        db = get_database()

        now = datetime.now(timezone.utc)

        # Calculate date range based on period
        if period == "day":
            start_date = now - timedelta(days=1)
            interval = "hour"
            trunc = "hour"
        elif period == "week":
            start_date = now - timedelta(days=7)
            interval = "day"
            trunc = "day"
        else:  # month
            start_date = now - timedelta(days=30)
            interval = "day"
            trunc = "day"

        tenant_filter = "AND tenant_id IS DISTINCT FROM :demo_tenant_id"
        params = {"start_date": start_date, "demo_tenant_id": str(DEMO_TENANT_ID)}

        if tenant_id:
            tenant_filter = "AND tenant_id = :tenant_id"
            params["tenant_id"] = str(tenant_id)
            del params["demo_tenant_id"]

        # Get trend data
        trends = await db.fetch_all(
            f"""
            SELECT
                DATE_TRUNC(:trunc, created_at) as period,
                COUNT(*) as total,
                COUNT(*) FILTER (WHERE status = 'completed' OR status = 'processed') as completed,
                COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled
            FROM calls
            WHERE created_at >= :start_date {tenant_filter}
            GROUP BY DATE_TRUNC(:trunc, created_at)
            ORDER BY period
            """,
            {"trunc": trunc, **params},
        )

        # Total calls in period
        total = await db.fetch_one(
            f"""
            SELECT COUNT(*) as count
            FROM calls
            WHERE created_at >= :start_date {tenant_filter}
            """,
            params,
        )

        return {
            "points": [
                {
                    "date": t["period"],
                    "total": t["total"],
                    "completed": t["completed"],
                    "cancelled": t["cancelled"],
                }
                for t in trends
            ],
            "period": period,
            "total_calls": total["count"] or 0,
        }

    async def get_project_stats(
        self,
        tenant_id: Optional[UUID] = None,
    ) -> List[Dict]:
        """
        Get statistics per project.

        Args:
            tenant_id: Optional tenant filter

        Returns:
            List of project stats
        """
        db = get_database()

        tenant_filter = "WHERE p.tenant_id IS DISTINCT FROM :demo_tenant_id"
        params = {"demo_tenant_id": str(DEMO_TENANT_ID)}

        if tenant_id:
            tenant_filter = "WHERE p.tenant_id = :tenant_id"
            params["tenant_id"] = str(tenant_id)
            del params["demo_tenant_id"]

        stats = await db.fetch_all(
            f"""
            SELECT
                p.id as project_id,
                p.name as project_name,
                COUNT(c.id) as total_calls,
                COUNT(c.id) FILTER (WHERE c.status = 'completed' OR c.status = 'processed') as completed_calls,
                AVG(c.duration_seconds) FILTER (WHERE c.duration_seconds IS NOT NULL) as avg_duration
            FROM projects p
            LEFT JOIN calls c ON c.project_id = p.id
            {tenant_filter}
            GROUP BY p.id, p.name
            ORDER BY total_calls DESC
            """,
            params,
        )

        return [
            {
                "project_id": str(s["project_id"]),
                "project_name": s["project_name"],
                "total_calls": s["total_calls"] or 0,
                "completed_calls": s["completed_calls"] or 0,
                "completion_rate": round(
                    (s["completed_calls"] or 0) / (s["total_calls"] or 1) * 100, 1
                ),
                "avg_duration_seconds": round(s["avg_duration"] or 0, 1),
            }
            for s in stats
        ]

    async def get_call_stats_by_status(
        self,
        tenant_id: Optional[UUID] = None,
        days: int = 30,
    ) -> Dict:
        """
        Get call counts by status.

        Args:
            tenant_id: Optional tenant filter
            days: Number of days to look back

        Returns:
            Dict with status counts
        """
        db = get_database()

        start_date = datetime.now(timezone.utc) - timedelta(days=days)

        tenant_filter = "AND tenant_id IS DISTINCT FROM :demo_tenant_id"
        params = {"start_date": start_date, "demo_tenant_id": str(DEMO_TENANT_ID)}

        if tenant_id:
            tenant_filter = "AND tenant_id = :tenant_id"
            params["tenant_id"] = str(tenant_id)
            del params["demo_tenant_id"]

        stats = await db.fetch_all(
            f"""
            SELECT status, COUNT(*) as count
            FROM calls
            WHERE created_at >= :start_date {tenant_filter}
            GROUP BY status
            """,
            params,
        )

        result = {
            "pending_consent": 0,
            "consented": 0,
            "in_progress": 0,
            "completed": 0,
            "processing": 0,
            "processed": 0,
            "declined": 0,
            # Aggiunto 20/08 insieme al nuovo CallStatus.ESCALATED (vedi
            # db_migrations/versions/a3905808ab22_*) - questo dict era
            # rimasto quello di prima, quindi una chiamata "escalated"
            # sarebbe comunque comparsa (l'assegnazione sotto crea la
            # chiave se manca) ma senza uno zero esplicito quando non ce
            # ne sono, trovato verificando dal vivo la nuova pagina
            # Analytics.
            "escalated": 0,
            "cancelled": 0,
        }

        for s in stats:
            result[s["status"]] = s["count"]

        return result


# Singleton instance
_analytics_service = None


def get_analytics_service() -> AnalyticsService:
    """Get the analytics service singleton."""
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = AnalyticsService()
    return _analytics_service
