"""Analysis schemas for request and response"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

from app.common.enums import (
    AnalysisType, AnalysisStatus, RiskLevel, Recommendation,
)


# ==================== Request Schemas ====================

class AnalysisCreateRequest(BaseModel):
    """创建 Analysis（空请求体，analysis_type 固定）"""
    pass

    class Config:
        json_schema_extra = {
            "example": {}
        }


class AnalysisConfirmRequest(BaseModel):
    """确认分析"""
    final_recommendation: Recommendation = Field(
        ...,
        description="最终结论: do_now | evaluate_first | plan_later | hold"
    )
    review_comment: Optional[str] = Field(
        default=None,
        description="复核评论",
        max_length=2000
    )

    class Config:
        json_schema_extra = {
            "example": {
                "final_recommendation": "do_now",
                "review_comment": "确认立即执行，下个迭代排期实现"
            }
        }


class AnalysisRejectRequest(BaseModel):
    """驳回分析"""
    review_comment: str = Field(
        ...,
        description="驳回原因",
        min_length=1,
        max_length=2000
    )

    class Config:
        json_schema_extra = {
            "example": {
                "review_comment": "分析不够深入，需要补充竞品对比数据"
            }
        }


# ==================== Response Schemas ====================

class AnalysisResponse(BaseModel):
    """Analysis 响应（完整信息）"""
    id: int
    item_id: int
    analysis_type: AnalysisType
    status: AnalysisStatus

    # 评分（Integer 1-5）
    business_value_score: Optional[int] = None
    technical_impact_score: Optional[int] = None

    # 风险等级
    risk_level: Optional[RiskLevel] = None

    # JSONB 字段
    candidate_capabilities_json: Optional[list[str]] = None
    candidate_modules_json: Optional[list[str]] = None
    similar_cases_json: Optional[list[dict[str, Any]]] = None

    # 建议（枚举）
    ai_recommendation: Optional[Recommendation] = None
    final_recommendation: Optional[Recommendation] = None

    # AI 元信息
    confidence_score: Optional[float] = None
    evidence_summary: Optional[str] = None
    missing_information: Optional[str] = None
    needs_deep_analysis: Optional[bool] = None

    # 复核
    review_comment: Optional[str] = None

    # 时间戳
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class AnalysisCreateResponse(BaseModel):
    """创建 Analysis 响应（简化版）"""
    id: int
    item_id: int
    analysis_type: AnalysisType
    status: AnalysisStatus
    created_at: datetime

    class Config:
        from_attributes = True


class AnalysisRunResponse(BaseModel):
    """运行分析响应"""
    id: int
    item_id: int
    analysis_type: AnalysisType
    status: AnalysisStatus
    business_value_score: Optional[int] = None
    technical_impact_score: Optional[int] = None
    risk_level: Optional[RiskLevel] = None
    candidate_capabilities_json: Optional[list[str]] = None
    candidate_modules_json: Optional[list[str]] = None
    similar_cases_json: Optional[list[dict[str, Any]]] = None
    ai_recommendation: Optional[Recommendation] = None
    confidence_score: Optional[float] = None
    evidence_summary: Optional[str] = None
    missing_information: Optional[str] = None
    needs_deep_analysis: Optional[bool] = None
    updated_at: datetime

    class Config:
        from_attributes = True


class AnalysisConfirmRejectResponse(BaseModel):
    """确认/驳回分析响应"""
    id: int
    item_id: int
    status: AnalysisStatus
    final_recommendation: Optional[Recommendation] = None
    review_comment: Optional[str] = None
    updated_at: datetime

    class Config:
        from_attributes = True
