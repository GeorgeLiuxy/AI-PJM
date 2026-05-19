"""Item models - Item and ItemSuggestion"""

from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime, 
    ForeignKey, Index, Numeric, Boolean,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, DB_BIGINT, DB_JSON, utc_now
from app.common.enums import ItemStatus, SourceType, ItemType, Priority


class Item(Base):
    """
    Item 表 - 存储最终确认的值和原始输入
    
    核心原则：
    - raw_input 和 source_type 是原始输入，不可变
    - title_final, final_type, final_priority 是用户确认后的最终值
    - status 控制状态流转
    - 通过 item_suggestions.item_id (unique) 获取当前建议（一对一）
    """
    __tablename__ = "items"
    
    # ==================== 主键 ====================
    id: Mapped[int] = mapped_column(
        DB_BIGINT,
        primary_key=True, 
        autoincrement=True
    )
    
    # ==================== 原始输入（不可变） ====================
    raw_input: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        comment="用户原始输入"
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="输入来源: customer_feedback | new_requirement | meeting_note | bug_report | ticket | other"
    )
    
    # ==================== 最终确认值（由用户确认后填写） ====================
    title_final: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        comment="最终确认的标题"
    )
    final_type: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="最终确认的类型: improvement | new_feature | bug | meeting_action | question"
    )
    final_priority: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="最终确认的优先级: low | medium | high | critical"
    )
    final_project: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="最终归属的项目"
    )
    
    # ==================== 状态流转 ====================
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ItemStatus.DRAFT,
        comment="状态: draft | pending_confirm | confirmed | analyzing | decided | output_generated | done"
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
    
    # ==================== 关系（一对一，简化版） ====================
    suggestion: Mapped[Optional["ItemSuggestion"]] = relationship(
        "ItemSuggestion",
        back_populates="item",
        uselist=False,  # 一对一：返回单个对象
        cascade="all, delete-orphan",  # 删除 Item 时级联删除 Suggestion
        single_parent=True
    )

    analysis: Mapped[Optional["Analysis"]] = relationship(
        "Analysis",
        back_populates="item",
        uselist=False,  # 一对一：返回单个对象
        cascade="all, delete-orphan",  # 删除 Item 时级联删除 Analysis
        single_parent=True
    )

    outputs: Mapped[list["Output"]] = relationship(
        "Output",
        back_populates="item",
        cascade="all, delete-orphan",  # 删除 Item 时级联删除 Output
    )
    
    # ==================== 索引 ====================
    __table_args__ = (
        Index('ix_items_status', 'status'),
        Index('ix_items_source_type', 'source_type'),
        Index('ix_items_created_at', 'created_at'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<Item(id={self.id}, status={self.status}, "
            f"title_final={self.title_final})>"
        )


class ItemSuggestion(Base):
    """
    ItemSuggestion 表 - 存储AI生成的建议（与 final 分离）
    
    核心原则：
    - item_id 唯一且非空，形成一对一关系
    - 所有 *_suggestion 字段都是 AI 生成的建议值
    - is_confirmed 标记是否已被用户确认
    - 不需要 version 字段，当前阶段不做多版本管理
    """
    __tablename__ = "item_suggestions"
    
    # ==================== 主键 ====================
    id: Mapped[int] = mapped_column(
        DB_BIGINT,
        primary_key=True,
        autoincrement=True
    )
    
    # ==================== 关联 Item（一对一） ====================
    item_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # 关键：一对一关系
        comment="关联的Item ID（唯一，形成一个Item只有一个当前建议）"
    )
    
    # ==================== 核心建议字段 ====================
    title_suggestion: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        comment="AI建议的标题"
    )
    type_suggestion: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="AI建议的类型: improvement | new_feature | bug | meeting_action | question"
    )
    priority_suggestion: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        comment="AI建议的优先级: low | medium | high | critical"
    )
    project_suggestion: Mapped[Optional[str]] = mapped_column(
        String(200),
        nullable=True,
        comment="AI建议归属的项目"
    )
    
    # ==================== 扩展建议字段（JSONB，Python typing 精确） ====================
    modules_suggestion_json: Mapped[Optional[list[str]]] = mapped_column(
        DB_JSON,
        nullable=True,
        comment="AI建议的影响模块列表 (list[str])"
    )
    impact_scope_suggestion: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI建议的影响范围描述"
    )
    pending_questions_json: Mapped[Optional[list[str]]] = mapped_column(
        DB_JSON,
        nullable=True,
        comment="AI提出的待确认问题列表 (list[str])"
    )
    similar_cases_json: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        DB_JSON,
        nullable=True,
        comment="AI找到的相似案例列表 (list[dict])"
    )
    recommendation_suggestion: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI的建议结论"
    )
    
    # ==================== AI 元信息（Numeric 精度） ====================
    confidence_score: Mapped[Optional[float]] = mapped_column(
        Numeric(5, 2, asdecimal=False),  # 数据库 Numeric(5,2)，Python 返回 float
        nullable=True,
        comment="AI置信度 (0-100)，两位小数"
    )
    evidence_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI证据摘要"
    )
    ai_model_version: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        comment="AI模型版本标识"
    )
    
    # ==================== 状态 ====================
    is_confirmed: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        comment="是否已被用户确认"
    )
    
    # ==================== 时间戳 ====================
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        comment="创建时间"
    )
    
    # ==================== 关系（反向） ====================
    item: Mapped["Item"] = relationship(
        "Item",
        back_populates="suggestion"
    )
    
    # ==================== 索引 ====================
    __table_args__ = (
        Index('ix_item_suggestions_item_id', 'item_id', unique=True),
        Index('ix_item_suggestions_confidence', 'confidence_score'),
    )
    
    def __repr__(self) -> str:
        return (
            f"<ItemSuggestion(id={self.id}, item_id={self.item_id}, "
            f"type_suggestion={self.type_suggestion}, is_confirmed={self.is_confirmed})>"
        )
