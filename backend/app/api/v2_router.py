"""V2 API router aggregation."""

from fastapi import APIRouter

from app.modules.delivery.router import router as delivery_router


v2_router = APIRouter()
v2_router.include_router(delivery_router)

