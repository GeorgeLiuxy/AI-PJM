"""Audit event data access."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.audit.models import AuditEvent


class AuditRepository:
    """Repository for audit events."""

    async def create_event(
        self,
        db: AsyncSession,
        *,
        action: str,
        entity_type: str,
        summary: str,
        actor_ref: str,
        project_id: int | None = None,
        actor_user_id: int | None = None,
        entity_id: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AuditEvent:
        event = AuditEvent(
            project_id=project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            summary=summary,
            metadata_json=metadata,
        )
        db.add(event)
        await db.flush()
        return event

    async def list_events(
        self,
        db: AsyncSession,
        *,
        project_ids: list[int] | None = None,
        project_id: int | None = None,
        entity_type: str | None = None,
        entity_id: int | None = None,
        action: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditEvent]:
        query = select(AuditEvent).order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        if project_ids is not None:
            if not project_ids:
                return []
            query = query.where(AuditEvent.project_id.in_(project_ids))
        if project_id is not None:
            query = query.where(AuditEvent.project_id == project_id)
        if entity_type:
            query = query.where(AuditEvent.entity_type == entity_type)
        if entity_id is not None:
            query = query.where(AuditEvent.entity_id == entity_id)
        if action:
            query = query.where(AuditEvent.action == action)
        result = await db.execute(query.offset(offset).limit(limit))
        return list(result.scalars().all())


audit_repository = AuditRepository()

