"""ActionLog model for tracking all state changes and actions"""

from datetime import datetime, timezone
from typing import Any
from sqlalchemy import Column, BigInteger, String, DateTime, Text, Index, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, DB_BIGINT, DB_JSON, utc_now


class ActionLog(Base):
    """
    Action log model for tracking all state changes and actions on business entities.

    This table records:
    - All status transitions for items, analyses, and outputs
    - AI suggestions and confirmations
    - User actions and system operations
    """
    __tablename__ = "action_logs"

    # Primary key
    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)

    # Business entity reference
    biz_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Business entity type: item | analysis | output"
    )
    biz_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        nullable=False,
        index=True,
        comment="Business entity ID"
    )

    # Action information
    action_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        comment="Action type: item_created | item_understood | item_confirmed | ..."
    )

    # Operator information (使用 operator_ref)
    operator_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="Operator type: user | ai | system"
    )
    operator_ref: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
        comment="Operator reference: user_id | ai_model_name | system_process_name"
    )

    # Status change
    from_status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="Previous status (if applicable)"
    )
    to_status: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        comment="New status (if applicable)"
    )

    # Action payload
    action_payload: Mapped[dict[str, Any] | None] = mapped_column(
        DB_JSON,
        nullable=True,
        comment="Action payload: changes, diff, reasons, etc."
    )

    # Comment
    comment: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="Additional comment or notes"
    )

    # Timestamp
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="Timestamp when the action occurred"
    )

    # Indexes
    __table_args__ = (
        Index('ix_action_logs_biz', 'biz_type', 'biz_id'),
        Index('ix_action_logs_created_at', 'created_at'),
        Index('ix_action_logs_operator', 'operator_type', 'operator_ref'),
    )

    def __repr__(self) -> str:
        return (
            f"<ActionLog(id={self.id}, biz_type={self.biz_type}, "
            f"biz_id={self.biz_id}, action_type={self.action_type})>"
        )
