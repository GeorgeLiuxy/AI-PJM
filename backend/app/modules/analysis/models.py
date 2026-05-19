"""Analysis models - impact assessment for Items"""

from datetime import datetime, timezone
from typing import Any, Optional
from sqlalchemy import (
    Column, BigInteger, String, Text, DateTime,
    Integer, Boolean, Index, ForeignKey, CheckConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, DB_BIGINT, DB_JSON, utc_now
from app.common.enums import (
    AnalysisStatus, AnalysisType, RiskLevel, Recommendation,
)


class Analysis(Base):
    """
    Analysis 表 - 影响评估分析

    核心原则：
    - item_id 唯一且非空，形成一对一关系
    - analysis_type 固定为 impact_assessment
    - 评分为 Integer 1-5，非 0-100 浮点数
    - ai_recommendation / final_recommendation 使用枚举
    - reject 回到 pending（非终态，可重新 run）
    """
    __tablename__ = "analyses"

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
        unique=True,
        comment="关联的Item ID（唯一，一个Item只能有一个Analysis）"
    )

    # ==================== 分析类型（固定） ====================
    analysis_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=AnalysisType.IMPACT_ASSESSMENT,
        comment="分析类型: impact_assessment（固定值）"
    )

    # ==================== 状态 ====================
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=AnalysisStatus.PENDING,
        comment="状态: pending | running | pending_review | confirmed"
    )

    # ==================== 评分（Integer 1-5） ====================
    business_value_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="业务价值评分 (1-5)"
    )

    technical_impact_score: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        comment="技术影响评分 (1-5)"
    )

    # ==================== 风险等级（三档） ====================
    risk_level: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="风险等级: low | medium | high"
    )

    # ==================== JSONB 字段 ====================
    candidate_capabilities_json: Mapped[Optional[list[str]]] = mapped_column(
        DB_JSON,
        nullable=True,
        comment="候选能力列表 (list[str])"
    )

    candidate_modules_json: Mapped[Optional[list[str]]] = mapped_column(
        DB_JSON,
        nullable=True,
        comment="候选模块列表 (list[str])"
    )

    similar_cases_json: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        DB_JSON,
        nullable=True,
        comment="相似案例列表 (list[dict])"
    )

    # ==================== AI 建议（枚举） ====================
    ai_recommendation: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="AI建议结论: do_now | evaluate_first | plan_later | hold"
    )

    # ==================== 最终结论（枚举） ====================
    final_recommendation: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        comment="最终确认结论: do_now | evaluate_first | plan_later | hold"
    )

    # ==================== AI 元信息 ====================
    confidence_score: Mapped[Optional[float]] = mapped_column(
        # Numeric(5, 2, asdecimal=False)，Python 返回 float
        nullable=True,
        comment="AI置信度 (0-100)，两位小数"
    )

    evidence_summary: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="AI证据摘要"
    )

    missing_information: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="缺失信息说明"
    )

    needs_deep_analysis: Mapped[Optional[bool]] = mapped_column(
        Boolean,
        nullable=True,
        default=False,
        comment="是否需要深度分析"
    )

    # ==================== 复核信息 ====================
    review_comment: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        comment="复核评论"
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

    # ==================== 关系（反向） ====================
    item: Mapped["Item"] = relationship(
        "Item",
        back_populates="analysis"
    )

    outputs: Mapped[list["Output"]] = relationship(
        "Output",
        back_populates="analysis"
    )

    # ==================== 约束与索引 ====================
    __table_args__ = (
        CheckConstraint(
            "business_value_score BETWEEN 1 AND 5",
            name="chk_business_value_score"
        ),
        CheckConstraint(
            "technical_impact_score BETWEEN 1 AND 5",
            name="chk_technical_impact_score"
        ),
        Index('ix_analyses_item_id', 'item_id', unique=True),
        Index('ix_analyses_status', 'status'),
        Index('ix_analyses_created_at', 'created_at'),
    )

    def __repr__(self) -> str:
        return (
            f"<Analysis(id={self.id}, item_id={self.item_id}, "
            f"status={self.status}, analysis_type={self.analysis_type})>"
        )
