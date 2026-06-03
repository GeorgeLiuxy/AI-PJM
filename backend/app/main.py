"""FastAPI application entry point"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v2_router import v2_router
from app.common.responses import HealthResponse
from app.core.config import settings
from app.core.db import async_session_maker, assert_database_current, init_db, is_sqlite_url
from app.core.logging import setup_logging
from app.core.exceptions import AppException
from app.modules.auth.service import auth_service


# Setup logging
setup_logging()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    # Startup
    print(f"Starting {settings.app_name} v{settings.app_version}")
    print(f"Environment: {settings.environment}")
    if is_sqlite_url(settings.database_url):
        await init_db()
        async with async_session_maker() as session:
            await auth_service.ensure_bootstrap_data(session)
        print("SQLite development database initialized")
    else:
        if settings.database_validate_migrations:
            await assert_database_current()
        async with async_session_maker() as session:
            await auth_service.ensure_bootstrap_data(session)
        print("Database migration state verified")
    yield
    # Shutdown
    print(f"Shutting down {settings.app_name}")


# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description="AI-assisted engineering delivery orchestration backend",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)


# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include API router
app.include_router(v2_router, prefix="/api/v2")


@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc),
        database=None,
    )


# Exception handlers
@app.exception_handler(AppException)
async def app_exception_handler(request, exc: AppException):
    """Handle custom application exceptions"""
    from fastapi.responses import JSONResponse
    return JSONResponse(
        status_code=exc.status_code,
        content={"code": exc.status_code, "message": exc.detail},
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    """Handle all other exceptions"""
    from fastapi.responses import JSONResponse
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": "Internal server error"},
    )
