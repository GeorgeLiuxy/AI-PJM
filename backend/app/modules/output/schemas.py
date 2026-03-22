"""Output schemas for request and response"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.common.enums import (
    OutputType, OutputStatus, AdoptedTarget,
)


# ==================== Request Schemas ====================

class OutputCreateRequest(BaseModel):
    """创建 Output"""
    output_type: OutputType = Field(
        ...,
        description="输出类型: prd | test_points | handling_advice"
    )
    analysis_id: Optional[int] = Field(
        default=None,
        description="关联的 Analysis ID（可选，必须属于当前 Item 且状态为 confirmed）"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "output_type": "prd",
                "analysis_id": None
            }
        }


class OutputConfirmRequest(BaseModel):
    """确认 Output（空请求体）"""
    pass
    
    class Config:
        json_schema_extra = {
            "example": {}
        }


class OutputAdoptRequest(BaseModel):
    """采用 Output"""
    adopted_target: AdoptedTarget = Field(
        ...,
        description="采用目标: formal_prd | test_task | implementation_note（必须与 output_type 匹配）"
    )
    
    class Config:
        json_schema_extra = {
            "example": {
                "adopted_target": "formal_prd"
            }
        }


# ==================== Response Schemas ====================

class OutputResponse(BaseModel):
    """Output 响应（完整信息）"""
    id: int
    item_id: int
    analysis_id: Optional[int] = None
    output_type: OutputType
    status: OutputStatus
    
    # 输出内容
    title: str
    content: str
    summary: Optional[str] = None
    
    # 采用目标
    adopted_target: Optional[AdoptedTarget] = None
    
    # 时间戳
    created_at: datetime
    updated_at: datetime
    confirmed_at: Optional[datetime] = None
    adopted_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class OutputCreateResponse(BaseModel):
    """创建 Output 响应（简化版）"""
    id: int
    item_id: int
    analysis_id: Optional[int] = None
    output_type: OutputType
    title: str
    status: OutputStatus
    summary: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class OutputListResponse(BaseModel):
    """Output 列表响应（用于 GET /items/{id}/outputs）"""
    id: int
    item_id: int
    output_type: OutputType
    title: str
    status: OutputStatus
    summary: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True


class OutputConfirmResponse(BaseModel):
    """确认 Output 响应"""
    id: int
    item_id: int
    output_type: OutputType
    status: OutputStatus
    adopted_target: Optional[AdoptedTarget] = None
    confirmed_at: Optional[datetime] = None
    updated_at: datetime
    
    class Config:
        from_attributes = True


class OutputAdoptResponse(BaseModel):
    """采用 Output 响应"""
    id: int
    item_id: int
    output_type: OutputType
    status: OutputStatus
    adopted_target: AdoptedTarget
    adopted_at: Optional[datetime] = None
    updated_at: datetime
    
    class Config:
        from_attributes = True
