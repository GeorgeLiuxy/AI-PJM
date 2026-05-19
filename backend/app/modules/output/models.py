"""Output models - generated documents for Items"""

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime,
    Index, ForeignKey, UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, DB_BIGINT, utc_now
from app.common.enums import (
    OutputStatus, OutputType, AdoptedTarget,
)


class Output(Base):
    """
    Output 表 - AI 生成的输出文档
    
    核心原则：
    - item_id + output_type 唯一（一个 Item 的每种类型只能有一个 Output）
    - analysis_id 可选（某些输出可能依赖分析结果）
    - 状态流转：pending_confirm -> confirmed -> adopted
    - confirm 不改变 Item 状态，adopt 时将 Item 改为 done
    """
    __tablename__ = "outputs"
    
    # ==================== 主键 ====================
    id: Mapped[int] = mapped_column(
        DB_BIGINT,
        primary_key=True,
        autoincrement=True
    )
    
    # ==================== 关联 Item 和 Analysis ====================
    item_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        comment="关联的Item ID"
    )
    
    analysis_id: Mapped[Optional[int]] = mapped_column(
        DB_BIGINT,
        ForeignKey("analyses.id", ondelete="SET NULL"),
        nullable=True,
        comment="关联的Analysis ID（可选）"
    )
    
    # ==================== 输出类型与状态 ====================
    output_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="输出类型: prd | test_points | handling_advice"
    )
    
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=OutputStatus.PENDING_CONFIRM,
        comment="状态: pending_confirm | confirmed | adopted"
    )
    
    # ==================== 输出内容 ====================
    title: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="输出标题"
    )
    
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="输出内容（Markdown格式）"
    )
    
    summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="输出摘要"
    )
    
    # ==================== 采用目标 ====================
    adopted_target: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="采用目标: formal_prd | test_task | implementation_note"
    )
    
    # ==================== 时间戳 ====================
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="创建时间"
    )
    
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
        comment="更新时间"
    )
    
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="确认时间"
    )
    
    adopted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment="采用时间"
    )
    
    # ==================== 关系（反向） ====================
    item: Mapped["Item"] = relationship(
        "Item",
        back_populates="outputs"
    )
    
    analysis: Mapped[Optional["Analysis"]] = relationship(
        "Analysis",
        back_populates="outputs"
    )
    
    # ==================== 约束与索引 ====================
    __table_args__ = (
        UniqueConstraint('item_id', 'output_type', name='uq_outputs_item_type'),
        Index('ix_outputs_item_id', 'item_id'),
        Index('ix_outputs_status', 'status'),
        Index('ix_outputs_output_type', 'output_type'),
        Index('ix_outputs_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<Output(id={self.id}, item_id={self.item_id}, "
            f"output_type={self.output_type}, status={self.status})>"
        )
