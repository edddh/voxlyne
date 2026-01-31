"""
Ascolta - Main Application
FastAPI entry point with lifecycle management
"""

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database.db import (
    check_database_health,
    connect_database,
    disconnect_database,
    run_migrations,
)
from app.models.schemas import ErrorResponse, HealthResponse
from app.routers import health, webhook

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

    # Run migrations
    try:
        await run_migrations()
    except Exception as e:
        logger.error(f"Migration error: {e}")
        # Continue anyway for development
        if settings.is_production:
            raise

    logger.info("Application started successfully")

    yield  # Application runs here

    # Shutdown
    logger.info("Shutting down...")
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

@app.get("/", tags=["Root"])
async def root():
    """Root endpoint - API information."""
    return {
        "name": "Ascolta",
        "version": "1.0.0-alpha",
        "milestone": "M1 - Voice Communication MVP",
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
