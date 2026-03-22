"""Item schemas for request and response"""

from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

from app.common.enums import ItemType, Priority, SourceType, ItemStatus


# ==================== Request Schemas ====================

class ItemDraftRequest(BaseModel):
    """创建 Item 草稿请求"""
    raw_input: str = Field(
        ...,
        description="用户原始输入",
        min_length=1,
        max_length=10000
    )
    source_type: SourceType = Field(
        ...,
        description="输入来源"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "raw_input": "客户希望审批节点支持抄送，并且通知内容要能区分审批人和抄送人",
                "source_type": "customer_feedback"
            }
        }


class ItemUnderstandRequest(BaseModel):
    """Item 理解请求"""
    force_refresh: bool = Field(
        default=False,
        description="是否强制刷新（当前阶段不支持）"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "force_refresh": False
            }
        }


class ItemFinalFields(BaseModel):
    """Item 最终值字段集合（用于 confirm 的 overrides）"""
    title_final: Optional[str] = Field(
        default=None,
        description="最终确认的标题",
        max_length=500
    )
    final_type: Optional[ItemType] = Field(
        default=None,
        description="最终确认的类型"
    )
    final_priority: Optional[Priority] = Field(
        default=None,
        description="最终确认的优先级"
    )
    final_project: Optional[str] = Field(
        default=None,
        description="最终归属的项目",
        max_length=200
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "title_final": "审批节点支持抄送并优化通知内容（修改版）",
                "final_type": "improvement",
                "final_priority": "medium",
                "final_project": "流程审批重构项目"
            }
        }


class ItemConfirmRequest(BaseModel):
    """Item 确认请求"""
    confirm_mode: str = Field(
        ...,
        description="确认模式: accept（全接受）| modify（修改部分字段）",
        pattern="^(accept|modify)$"
    )
    overrides: Optional[ItemFinalFields] = Field(
        default=None,
        description="当 confirm_mode=modify 时，允许覆盖的最终值字段"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "confirm_mode": "accept"
            }
        }


# ==================== Response Schemas ====================

class ItemSuggestionResponse(BaseModel):
    """ItemSuggestion 响应"""
    id: int
    item_id: int
    title_suggestion: str
    type_suggestion: str
    priority_suggestion: str
    project_suggestion: Optional[str] = None
    modules_suggestion_json: Optional[list] = None  # list[str]
    impact_scope_suggestion: Optional[str] = None
    pending_questions_json: Optional[list] = None  # list[str]
    similar_cases_json: Optional[list] = None  # list[dict]
    recommendation_suggestion: Optional[str] = None
    confidence_score: Optional[float] = None
    evidence_summary: Optional[str] = None
    ai_model_version: Optional[str] = None
    is_confirmed: bool = False
    created_at: datetime
    
    class Config:
        from_attributes = True


class ItemResponse(BaseModel):
    """Item 响应（完整信息）"""
    id: int
    raw_input: str
    source_type: str
    
    # Final values
    title_final: Optional[str] = None
    final_type: Optional[str] = None
    final_priority: Optional[str] = None
    final_project: Optional[str] = None
    
    # Status
    status: str
    
    # Suggestion (included when available)
    suggestion: Optional[ItemSuggestionResponse] = None
    
    # Timestamps
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class ItemDraftResponse(BaseModel):
    """创建草稿响应（简化版）"""
    id: int
    raw_input: str
    source_type: str
    title_final: Optional[str] = None
    final_type: Optional[str] = None
    final_priority: Optional[str] = None
    final_project: Optional[str] = None
    status: str
    created_at: datetime
    
    class Config:
        from_attributes = True


class ItemUnderstandResponse(BaseModel):
    """理解响应"""
    id: int
    status: str
    suggestion: ItemSuggestionResponse
    
    class Config:
        from_attributes = False  # 不从 ORM 模型自动转换


class ItemConfirmResponse(BaseModel):
    """确认响应"""
    id: int
    title_final: Optional[str] = None
    final_type: Optional[str] = None
    final_priority: Optional[str] = None
    final_project: Optional[str] = None
    status: str
    updated_at: datetime
    
    class Config:
        from_attributes = True
