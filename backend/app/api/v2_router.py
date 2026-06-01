"""V2 API router aggregation."""

from fastapi import APIRouter

from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.delivery.router import router as delivery_router
from app.modules.delivery.symphony_router import router as symphony_bridge_router
from app.modules.secrets.router import router as secrets_router


v2_router = APIRouter()
v2_router.include_router(auth_router)
v2_router.include_router(audit_router)
v2_router.include_router(secrets_router)
v2_router.include_router(delivery_router)
v2_router.include_router(symphony_bridge_router)
