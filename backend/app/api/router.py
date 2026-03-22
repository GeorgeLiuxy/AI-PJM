"""Main API router aggregation and health check endpoint"""

from fastapi import APIRouter
from app.common.responses import HealthResponse
from app.core.config import settings
from datetime import datetime, timezone

# Import item router
from app.modules.item.router import router as item_router
from app.modules.analysis.router import router as analysis_router
from app.modules.output.router import router as output_router
from app.modules.workbench.router import router as workbench_router

# Create main API router
api_router = APIRouter()


# Health check endpoint (only one)
@api_router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check() -> HealthResponse:
    """
    Health check endpoint.
    
    Returns the current status of the service.
    """
    return HealthResponse(
        status="healthy",
        version=settings.app_version,
        timestamp=datetime.now(timezone.utc),
        database=None,  # Will add DB health check in future
    )


# Include item router
api_router.include_router(item_router, prefix="/items", tags=["items"])

# Include analysis router
api_router.include_router(analysis_router)

# Include output router
api_router.include_router(output_router)

# Include workbench router
api_router.include_router(workbench_router, prefix="/workbench", tags=["workbench"])
