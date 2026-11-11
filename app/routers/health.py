"""
Voxlyne - Health Check Router
Detailed health checks for monitoring
"""

import logging
from datetime import datetime

from fastapi import APIRouter

from app.config import get_settings
from app.database.db import check_database_health, get_database

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health/detailed")
async def detailed_health_check():
    """
    Detailed health check with component status.
    Used for debugging and monitoring dashboards.
    """
    settings = get_settings()
    db_healthy = await check_database_health()

    # Get database stats if connected
    db_stats = {}
    if db_healthy:
        try:
            db = get_database()
            # Count recent calls (last 24h)
            result = await db.fetch_one(
                """
                SELECT
                    COUNT(*) as total_calls,
                    COUNT(*) FILTER (WHERE status = 'completed') as completed_calls,
                    COUNT(*) FILTER (WHERE status = 'cancelled') as cancelled_calls
                FROM calls
                WHERE created_at > NOW() - INTERVAL '24 hours'
                """
            )
            if result:
                db_stats = {
                    "calls_24h": result["total_calls"],
                    "completed_24h": result["completed_calls"],
                    "cancelled_24h": result["cancelled_calls"],
                }
        except Exception as e:
            logger.warning(f"Could not fetch DB stats: {e}")

    return {
        "status": "ok" if db_healthy else "degraded",
        "timestamp": datetime.utcnow().isoformat(),
        "version": "1.0.0-alpha",
        "milestone": "M1",
        "environment": settings.app_env,
        "components": {
            "database": {
                "status": "healthy" if db_healthy else "unhealthy",
                "type": "postgresql",
                **db_stats,
            },
            "openai": {
                "status": "configured" if settings.openai_api_key else "missing",
                "model": settings.openai_realtime_model,
                "voice": settings.openai_realtime_voice,
            },
            # MinIO will be added in M2
            # "storage": {
            #     "status": "not_configured",
            #     "type": "minio",
            # },
        },
        "config": {
            "silence_timeout": settings.silence_timeout_seconds,
            "max_call_duration": settings.max_call_duration_seconds,
            "dtmf_cancel_key": settings.dtmf_cancel_key,
        },
    }


@router.get("/health/ready")
async def readiness_check():
    """
    Kubernetes readiness probe.
    Returns 200 only if the service can accept traffic.
    """
    db_healthy = await check_database_health()

    if not db_healthy:
        return {"ready": False, "reason": "database_unavailable"}

    return {"ready": True}


@router.get("/health/live")
async def liveness_check():
    """
    Kubernetes liveness probe.
    Returns 200 if the service is running (even if dependencies are down).
    """
    return {"alive": True, "timestamp": datetime.utcnow().isoformat()}
