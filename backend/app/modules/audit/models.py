"""Audit event models."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, DB_BIGINT, DB_JSON, utc_now


class AuditEvent(Base):
    """Immutable audit event for security-sensitive or human-triggered actions."""

    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    project_id: Mapped[Optional[int]] = mapped_column(
        DB_BIGINT,
        ForeignKey("auth_projects.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        DB_BIGINT,
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    actor_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(DB_BIGINT, nullable=True)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    __table_args__ = (
        Index("ix_audit_events_project_id", "project_id"),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
        Index("ix_audit_events_action", "action"),
        Index("ix_audit_events_entity", "entity_type", "entity_id"),
        Index("ix_audit_events_created_at", "created_at"),
    )

