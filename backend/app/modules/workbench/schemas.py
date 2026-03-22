"""Workbench schemas for request and response"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field

from app.common.enums import ItemType, Priority, ItemStatus, OutputType, OutputStatus


# ==================== Summary Schemas ====================

class HomeSummaryResponse(BaseModel):
    """Home page summary counts"""
    pending_item_confirm_count: int = Field(..., description="Items pending user confirmation")
    pending_analysis_review_count: int = Field(..., description="Analyses pending review")
    pending_output_confirm_count: int = Field(..., description="Outputs pending confirmation")
    done_item_count: int = Field(..., description="Items completed")


# ==================== Todo Schemas ====================

class TodoResponse(BaseModel):
    """Todo item in queue"""
    todo_type: str = Field(..., description="Type of todo")
    biz_type: str = Field(..., description="Business entity type")
    biz_id: int = Field(..., description="Business entity ID")
    item_id: int = Field(..., description="Associated item ID")
    title: str = Field(..., description="Todo title")
    priority: str = Field(..., description="Priority level")
    updated_at: datetime = Field(..., description="Last update time")


class TodosBreakdown(BaseModel):
    """Todo breakdown by type"""
    pending_item_confirm: int
    pending_analysis_review: int
    pending_output_confirm: int
    pending_output_adopt: int


class TodosResponse(BaseModel):
    """Todos response"""
    todos: list[TodoResponse]
    total: int
    breakdown: TodosBreakdown


# ==================== Recent Item Schema ====================

class RecentItemResponse(BaseModel):
    """Recent item in workbench"""
    id: int
    title_final: Optional[str] = None
    status: ItemStatus
    final_type: Optional[ItemType] = None
    final_priority: Optional[Priority] = None
    updated_at: datetime

    class Config:
        from_attributes = True


# ==================== Recent Output Schema ====================

class RecentOutputResponse(BaseModel):
    """Recent output in workbench"""
    id: int
    item_id: int
    output_type: OutputType
    title: str
    status: OutputStatus
    created_at: datetime

    class Config:
        from_attributes = True


# ==================== Home Response ====================

class HomeResponse(BaseModel):
    """Home page response"""
    summary: HomeSummaryResponse
    todo_queue: list[TodoResponse]
    recent_items: list[RecentItemResponse]
    recent_outputs: list[RecentOutputResponse]
