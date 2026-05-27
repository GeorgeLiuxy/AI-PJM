"""Secret store models."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, DB_BIGINT, DB_JSON, utc_now


class SecretRecord(Base):
    """Encrypted project-scoped credential."""

    __tablename__ = "secret_records"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("auth_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    key_id: Mapped[str] = mapped_column(String(100), nullable=False)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    value_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    value_mask: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        DB_BIGINT,
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by_user_id: Mapped[Optional[int]] = mapped_column(
        DB_BIGINT,
        ForeignKey("auth_users.id", ondelete="SET NULL"),
        nullable=True,
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_secret_records_project_name"),
        Index("ix_secret_records_project_id", "project_id"),
        Index("ix_secret_records_provider", "provider"),
        Index("ix_secret_records_status", "status"),
        Index("ix_secret_records_created_at", "created_at"),
    )
