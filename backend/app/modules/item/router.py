"""Item router - 4 core APIs"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import NotFoundException
from app.common.responses import success_response
from app.modules.item.repository import item_repository
from app.modules.item.service import item_service
from app.modules.item.schemas import (
    ItemDraftRequest,
    ItemDraftResponse,
    ItemUnderstandRequest,
    ItemUnderstandResponse,
    ItemConfirmRequest,
    ItemConfirmResponse,
    ItemResponse,
    ItemSuggestionResponse,
)

# Create router
router = APIRouter()


@router.post("/draft", status_code=201, tags=["items"])
async def create_draft(
    request: ItemDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    创建 Item 草稿

    - 接收用户原始输入
    - 创建 draft 状态的 Item
    - 写入 action_log (item_created)
    """
    item = await item_service.create_draft(
        db=db,
        raw_input=request.raw_input,
        source_type=request.source_type.value,
        operator_ref="user_from_api",
    )

    response_data = ItemDraftResponse.model_validate(item)
    return success_response(
        data=response_data.model_dump(),
        message="Item created successfully",
        code=201
    )


@router.post("/{item_id}/understand", tags=["items"])
async def understand_item(
    item_id: int,
    request: ItemUnderstandRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    对 Item 执行 AI 理解

    - 只允许 draft 状态的 Item 执行
    - 创建 ItemSuggestion（使用 MockAdapter）
    - 更新 Item 状态为 pending_confirm
    - 写入 action_log (item_understood)
    """
    item, suggestion = await item_service.understand(
        db=db,
        item_id=item_id,
        force_refresh=request.force_refresh,
    )

    response_data = ItemUnderstandResponse(
        id=item.id,
        status=item.status,
        suggestion=ItemSuggestionResponse.model_validate(suggestion),
    )
    return success_response(
        data=response_data.model_dump(),
        message="Item understood successfully"
    )


@router.get("/{item_id}", tags=["items"])
async def get_item(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    获取 Item 详情

    - 返回 Item 的完整信息
    - 包含 suggestion（如果存在）
    """
    item = await item_repository.get_with_suggestion(db, item_id)

    if not item:
        raise NotFoundException(f"Item {item_id} not found")

    response_data = ItemResponse.model_validate(item)
    return success_response(
        data=response_data.model_dump(),
        message="Item retrieved successfully"
    )


@router.post("/{item_id}/confirm", tags=["items"])
async def confirm_item(
    item_id: int,
    request: ItemConfirmRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    确认 Item 建议

    - 只允许 pending_confirm 状态的 Item 执行
    - confirm_mode=accept：直接复制 suggestion → final
    - confirm_mode=modify：使用 overrides 覆盖部分字段
    - 更新 Item 状态为 confirmed
    """
    item = await item_service.confirm(
        db=db,
        item_id=item_id,
        confirm_mode=request.confirm_mode,
        overrides=request.overrides.model_dump() if request.overrides else None,
        operator_ref="user_from_api",
    )

    response_data = ItemConfirmResponse.model_validate(item)
    return success_response(
        data=response_data.model_dump(),
        message="Item confirmed successfully"
    )


@router.get("/{item_id}/timeline", tags=["items"])
async def get_item_timeline(
    item_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    获取 Item 时间线

    - 返回 Item、Analysis、Output 的所有 action_logs
    - 按 created_at ASC 排序
    """
    from app.modules.item.timeline_service import timeline_service

    timeline_data = await timeline_service.get_item_timeline(db, item_id)

    return success_response(
        data=timeline_data,
        message="Timeline retrieved successfully"
    )
