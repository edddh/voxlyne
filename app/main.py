"""
Ascolta - Main Application
FastAPI entry point with lifecycle management
"""

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database.db import (
    check_database_health,
    connect_database,
    disconnect_database,
    run_migrations,
)
from app.models.schemas import ErrorResponse, HealthResponse
from app.routers import agent_versions, analytics, api, auth, calendar, calls, credentials, crm, health, knowledge_base, outbound, project_config, prompt_blocks, prompts, simulation, telephony_provisioning, templates, tenants, users, webhook, webhook_vapi, webhook_xai
from app.services.rag.scheduler import RagRecrawlScheduler
from app.services.session_cleanup import SessionCleanup

# ===========================================
# Logging Configuration
# ===========================================

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logger = logging.getLogger(__name__)


# ===========================================
# Application Lifecycle
# ===========================================

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator:
    """
    Application lifespan manager.
    Handles startup and shutdown events.
    """
    # Startup
    logger.info("=" * 50)
    logger.info("Ascolta - Starting up...")
    logger.info(f"Environment: {settings.app_env}")
    logger.info(f"Log Level: {settings.log_level}")
    logger.info("=" * 50)

    # Connect to database
    await connect_database()

    # Migrations are now owned by Alembic (18/08, see db_migrations/ and
    # migrations/README-legacy.md) - applied deliberately with
    # `alembic upgrade head`, not automatically on every boot. This legacy
    # runner used to re-execute every migrations/*.sql file on every
    # startup, relying on catching "already exists" errors to skip what
    # was already applied - it just crash-looped the service in
    # production, because one of those files does a seed INSERT that
    # RLS now rejects (no bypass GUC set at boot time), and
    # settings.is_production re-raises that into a hard startup failure.
    # Left disabled, not deleted, in case something still depends on it
    # in an environment without an .env DATABASE_URL Alembic can reach.

    # Start cleanup service
    cleanup_service = SessionCleanup()
    await cleanup_service.start()

    # RAG recrawl scheduler (kb_sources.recrawl_interval_hours, 18/08)
    rag_scheduler = RagRecrawlScheduler()
    await rag_scheduler.start()

    logger.info("Application started successfully")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down...")
    await rag_scheduler.stop()
    await cleanup_service.stop()
    await disconnect_database()
    logger.info("Application stopped")


# ===========================================
# FastAPI Application
# ===========================================

app = FastAPI(
    title="Ascolta",
    description="AI-powered phone interview system for recruiting",
    version="1.0.0-alpha",
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
    lifespan=lifespan,
)


# ===========================================
# Middleware
# ===========================================

# CORS (adjust origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.is_development else [settings.webhook_base_url],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ===========================================
# Exception Handlers
# ===========================================

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Global exception handler."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="internal_server_error",
            detail=str(exc) if settings.is_development else "An error occurred"
        ).model_dump()
    )


# ===========================================
# Root Endpoints
# ===========================================

@app.get("/api/info", tags=["Root"])
async def root():
    """API information endpoint."""
    return {
        "name": "Ascolta",
        "version": "5.0.0-alpha",
        "milestone": "M5 - Dual Voice Engine + Outbound Calling",
        "status": "running",
        "docs": "/docs" if not settings.is_production else None,
    }


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Health check endpoint.
    Used by Docker and load balancers to verify service health.
    """
    db_healthy = await check_database_health()

    return HealthResponse(
        status="ok" if db_healthy else "degraded",
        database=db_healthy,
        version="1.0.0-alpha",
        environment=settings.app_env,
    )


# ===========================================
# Include Routers
# ===========================================

# Health router (detailed health checks)
app.include_router(health.router, prefix="/api", tags=["Health"])

# Webhook router (OpenAI SIP events)
app.include_router(webhook.router, prefix="/api", tags=["Webhook"])

# API router (M2: Projects, calls, records, PDFs)
app.include_router(api.router, tags=["API"])

# CRM router (M3: CRM integration endpoints)
app.include_router(crm.router, tags=["CRM"])

# Calendar router (M3.5: Calendar scheduling endpoints)
app.include_router(calendar.router, tags=["Calendar"])

# Auth router (M4: Authentication)
app.include_router(auth.router, tags=["Authentication"])

# Users router (M4: User management)
app.include_router(users.router, tags=["Users"])

# Tenants router (M4: Tenant management)
app.include_router(tenants.router, tags=["Tenants"])

# Prompts router (M4: Prompt versioning)
app.include_router(prompts.router, tags=["Prompts"])

# Templates router (M4+: Template management)
app.include_router(templates.router, tags=["Templates"])

# Prompt Blocks router (M4+: Prompt composer blocks)
app.include_router(prompt_blocks.router, tags=["Prompt Blocks"])

# Project Config router (M4+: SIP, CRM, Calendar, Placeholders)
app.include_router(project_config.router, tags=["Project Configuration"])

# Analytics router (M4: Dashboard stats)
app.include_router(analytics.router, tags=["Analytics"])

# Calls router (M4: Enhanced calls management)
app.include_router(calls.router, tags=["Calls V2"])

# Outbound router (M5: Outbound call management)
app.include_router(outbound.router, tags=["Outbound"])
app.include_router(agent_versions.router, tags=["Agent Versions"])

# Vapi webhook router (M5: Vapi.ai events)
app.include_router(webhook_vapi.router, prefix="/api", tags=["Webhook Vapi"])

# xAI SIP-direct webhook router (Grok priority, 18/08)
app.include_router(webhook_xai.router, prefix="/api", tags=["Webhook xAI"])

# Credentials router (M5.5: Service credentials management)
app.include_router(credentials.router, prefix="/api", tags=["Credentials"])

# Telephony provisioning router (connect a real number to a project: xAI + Zadarma, 18/08)
app.include_router(telephony_provisioning.router, prefix="/api", tags=["Telephony Provisioning"])

# Knowledge base / RAG router (per-project, crawl + upload -> pgvector, 18/08)
app.include_router(knowledge_base.router, prefix="/api", tags=["Knowledge Base"])

# Prompt simulation router (test-chat prima di pubblicare, 19/08)
app.include_router(simulation.router, prefix="/api", tags=["Simulation"])


# ===========================================
# Admin UI (built React SPA) - must be registered after all API routers
# ===========================================

ADMIN_UI_DIST = Path(__file__).resolve().parent.parent / "admin-ui" / "dist"

if ADMIN_UI_DIST.exists():
    assets_dir = ADMIN_UI_DIST / "assets"
    if assets_dir.exists():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="admin-assets")

    @app.get("/", include_in_schema=False)
    @app.head("/", include_in_schema=False)
    async def serve_admin_index():
        return FileResponse(ADMIN_UI_DIST / "index.html")

    @app.get("/{full_path:path}", include_in_schema=False)
    @app.head("/{full_path:path}", include_in_schema=False)
    async def serve_admin_spa(full_path: str):
        candidate = ADMIN_UI_DIST / full_path
        if candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(ADMIN_UI_DIST / "index.html")


# ===========================================
# Development Server
# ===========================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.is_development,
        log_level=settings.log_level.lower(),
    )
