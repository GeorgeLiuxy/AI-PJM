"""Audit API endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.core.db import get_db
from app.modules.audit.repository import audit_repository
from app.modules.audit.schemas import AuditEventResponse
from app.modules.auth.dependencies import get_current_principal, require_capability
from app.modules.auth.service import AuthPrincipal


router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=dict)
async def list_audit_events(
    project_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "read", project_id)
    events = await audit_repository.list_events(
        db=db,
        project_ids=principal.accessible_project_ids if project_id is None else None,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )
    return success_response(
        data=[AuditEventResponse.model_validate(event).model_dump() for event in events],
        message="Success",
    )

