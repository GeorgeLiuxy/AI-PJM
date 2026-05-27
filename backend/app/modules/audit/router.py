"""Audit API endpoints."""

import csv
from datetime import datetime
from io import StringIO

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.core.db import get_db
from app.modules.audit.repository import audit_repository
from app.modules.audit.schemas import AuditEventResponse
from app.modules.auth.dependencies import get_current_principal, require_capability
from app.modules.auth.service import AuthPrincipal


router = APIRouter(prefix="/audit", tags=["audit"])


def _normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None


async def _list_authorized_events(
    *,
    db: AsyncSession,
    principal: AuthPrincipal,
    project_id: int | None,
    entity_type: str | None,
    entity_id: int | None,
    action: str | None,
    actor_user_id: int | None,
    actor_ref: str | None,
    created_from: datetime | None,
    created_to: datetime | None,
    query: str | None,
    limit: int,
    offset: int,
):
    require_capability(principal, "read", project_id)
    return await audit_repository.list_events(
        db=db,
        project_ids=principal.accessible_project_ids if project_id is None else None,
        project_id=project_id,
        entity_type=_normalize_text(entity_type),
        entity_id=entity_id,
        action=_normalize_text(action),
        actor_user_id=actor_user_id,
        actor_ref=_normalize_text(actor_ref),
        created_from=created_from,
        created_to=created_to,
        query_text=_normalize_text(query),
        limit=limit,
        offset=offset,
    )


@router.get("/events", response_model=dict)
async def list_audit_events(
    project_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    actor_user_id: int | None = None,
    actor_ref: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    query: str | None = None,
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    events = await _list_authorized_events(
        db=db,
        principal=principal,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        actor_ref=actor_ref,
        created_from=created_from,
        created_to=created_to,
        query=query,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )
    return success_response(
        data=[AuditEventResponse.model_validate(event).model_dump() for event in events],
        message="Success",
    )


@router.get("/events/export", response_class=Response)
async def export_audit_events(
    project_id: int | None = None,
    entity_type: str | None = None,
    entity_id: int | None = None,
    action: str | None = None,
    actor_user_id: int | None = None,
    actor_ref: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    query: str | None = None,
    limit: int = 1000,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    events = await _list_authorized_events(
        db=db,
        principal=principal,
        project_id=project_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        actor_user_id=actor_user_id,
        actor_ref=actor_ref,
        created_from=created_from,
        created_to=created_to,
        query=query,
        limit=min(max(limit, 1), 2000),
        offset=0,
    )
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "id",
            "created_at",
            "project_id",
            "actor_user_id",
            "actor_ref",
            "action",
            "entity_type",
            "entity_id",
            "summary",
        ]
    )
    for event in events:
        writer.writerow(
            [
                event.id,
                event.created_at.isoformat(),
                event.project_id or "",
                event.actor_user_id or "",
                event.actor_ref,
                event.action,
                event.entity_type,
                event.entity_id or "",
                event.summary,
            ]
        )

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="audit-events.csv"'},
    )
