"""Audit event data access."""

from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
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
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
        created_from: datetime | None = None,
        created_to: datetime | None = None,
        query_text: str | None = None,
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
        if actor_user_id is not None:
            query = query.where(AuditEvent.actor_user_id == actor_user_id)
        if actor_ref:
            query = query.where(AuditEvent.actor_ref.ilike(f"%{actor_ref}%"))
        if created_from is not None:
            query = query.where(AuditEvent.created_at >= created_from)
        if created_to is not None:
            query = query.where(AuditEvent.created_at <= created_to)
        if query_text:
            pattern = f"%{query_text}%"
            query = query.where(
                or_(
                    AuditEvent.summary.ilike(pattern),
                    AuditEvent.action.ilike(pattern),
                    AuditEvent.entity_type.ilike(pattern),
                    AuditEvent.actor_ref.ilike(pattern),
                )
            )
        result = await db.execute(query.offset(offset).limit(limit))
        return list(result.scalars().all())


audit_repository = AuditRepository()
