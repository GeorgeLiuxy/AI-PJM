"""Workbench router - API endpoints for home page and todos"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.modules.workbench.service import workbench_service
from app.modules.workbench.schemas import (
    HomeResponse,
    HomeSummaryResponse,
    TodosResponse,
)
from app.common.responses import success_response


router = APIRouter(tags=["Workbench"])


@router.get("/home", response_model=dict)
async def get_home(
    db: AsyncSession = Depends(get_db),
):
    """
    Get workbench home page data

    Returns summary counts, todo queue, recent items, and recent outputs
    """
    data = await workbench_service.get_home_summary(db)

    # Convert to response models
    summary_response = HomeSummaryResponse.model_validate(data["summary"])
    todo_queue_response = [TodoResponse.model_validate(t) for t in data["todo_queue"]]
    recent_items_response = [RecentItemResponse.model_validate(item) for item in data["recent_items"]]
    recent_outputs_response = [RecentOutputResponse.model_validate(output) for output in data["recent_outputs"]]

    return success_response(
        data={
            "summary": summary_response.model_dump(),
            "todo_queue": [t.model_dump() for t in todo_queue_response],
            "recent_items": [i.model_dump() for i in recent_items_response],
            "recent_outputs": [o.model_dump() for o in recent_outputs_response],
        },
        message="Success",
    )


@router.get("/todos", response_model=dict)
async def get_todos(
    db: AsyncSession = Depends(get_db),
):
    """
    Get all todos (read-only, no filters, no pagination)

    Returns up to 50 todos ordered by priority and updated_at
    """
    data = await workbench_service.get_todos(db, limit=50)

    # Convert to response models
    todos_response = [TodoResponse.model_validate(t) for t in data["todos"]]
    breakdown_response = TodosBreakdown.model_validate(data["breakdown"])

    return success_response(
        data={
            "todos": [t.model_dump() for t in todos_response],
            "total": data["total"],
            "breakdown": breakdown_response.model_dump(),
        },
        message="Success",
    )


# Import schemas for use in router
from app.modules.workbench.schemas import TodoResponse, TodosBreakdown, RecentItemResponse, RecentOutputResponse
