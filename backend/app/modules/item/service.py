"""Item service - business logic layer"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.item.models import Item, ItemSuggestion
from app.modules.item.repository import item_repository, item_suggestion_repository
from app.modules.audit.service import action_log_service
from app.ai.understanding_service import understanding_service
from app.common.enums import (
    ItemStatus, ActionType, OperatorType, BizType,
)


class ItemService:
    """Item service - business logic layer"""
    
    async def create_draft(
        self,
        db: AsyncSession,
        raw_input: str,
        source_type: str,
        operator_ref: Optional[str] = None,
    ) -> Item:
        """创建 Item 草稿"""
        # 1. 创建 Item（状态为 draft）
        item = await item_repository.create(
            db=db,
            raw_input=raw_input,
            source_type=source_type,
        )
        
        # 2. 写入 action_log
        await action_log_service.log(
            db=db,
            biz_type=BizType.ITEM,
            biz_id=item.id,
            action_type=ActionType.ITEM_CREATED,
            operator_type=OperatorType.USER,
            operator_ref=operator_ref or "system",
            from_status=None,
            to_status=ItemStatus.DRAFT,
            action_payload={
                "source_type": source_type,
                "raw_input_length": len(raw_input),
            },
            comment="Item created from user input",
        )
        
        await db.commit()
        
        # 重新加载以获取 suggestion（虽然此时还没有）
        return await item_repository.get_with_suggestion(db, item.id)

    async def understand(
        self,
        db: AsyncSession,
        item_id: int,
        force_refresh: bool = False,
    ) -> tuple[Item, ItemSuggestion]:
        """对 Item 执行 AI 理解"""
        from app.core.exceptions import BadRequestException
        
        # 1. 获取 Item
        item = await item_repository.get_with_suggestion(db, item_id)
        if not item:
            raise BadRequestException(f"Item {item_id} not found")
        
        # 2. 检查已有 suggestion
        existing_suggestion = item.suggestion

        # 3. 处理已有 suggestion 的情况（幂等性）
        if existing_suggestion:
            # pending_confirm + existing suggestion + force_refresh=false：幂等返回
            if item.status == ItemStatus.PENDING_CONFIRM and not force_refresh:
                return item, existing_suggestion

            # pending_confirm + existing suggestion + force_refresh=true：不支持
            if force_refresh:
                raise BadRequestException(
                    "Force refresh is not supported in this phase"
                )

            # draft + existing suggestion：状态不一致
            if item.status == ItemStatus.DRAFT:
                raise BadRequestException(
                    f"Item {item_id} has existing suggestion but status is draft. "
                    "This is an inconsistent state."
                )

        # 4. 检查状态：只有 draft 状态可以执行新的 understand
        if item.status != ItemStatus.DRAFT:
            raise BadRequestException(
                f"Only draft items can be understood. Current status: {item.status}"
            )
        
        # 5. 执行 AI 理解（使用 MockAdapter）
        ai_result = await understanding_service.understand(
            input_text=item.raw_input,
            source_type=item.source_type,
        )
        
        # 6. 创建 ItemSuggestion
        suggestion = await item_suggestion_repository.create(
            db=db,
            item_id=item.id,
            title_suggestion=ai_result["title"],
            type_suggestion=ai_result["type"],
            priority_suggestion=ai_result["priority"],
            project_suggestion=ai_result["project"],
            modules_suggestion_json=ai_result["modules"],
            impact_scope_suggestion=ai_result["impact_scope"],
            pending_questions_json=ai_result["questions"],
            similar_cases_json=ai_result["similar_cases"],
            recommendation_suggestion=ai_result["recommendation"],
            confidence_score=ai_result["confidence_score"],
            evidence_summary=ai_result["evidence_summary"],
            ai_model_version="mock_adapter_v1",
        )
        
        # 7. 更新 Item 状态为 pending_confirm
        from_status = item.status
        item = await item_repository.update_status(
            db=db,
            item=item,
            new_status=ItemStatus.PENDING_CONFIRM,
        )
        
        # 8. 写入 action_log
        await action_log_service.log(
            db=db,
            biz_type=BizType.ITEM,
            biz_id=item.id,
            action_type=ActionType.ITEM_UNDERSTOOD,
            operator_type=OperatorType.AI,
            operator_ref="mock_adapter",
            from_status=from_status,
            to_status=ItemStatus.PENDING_CONFIRM,
            action_payload={
                "suggestion_id": suggestion.id,
                "confidence_score": suggestion.confidence_score,
                "ai_model": "mock_adapter",
                "suggested_type": suggestion.type_suggestion,
                "suggested_priority": suggestion.priority_suggestion,
            },
            comment=f"AI understood item using mock_adapter",
        )
        
        await db.commit()

        # 重新加载以获取 suggestion
        item = await item_repository.get_with_suggestion(db, item.id)

        # 确保 suggestion 已加载
        suggestion = item.suggestion
        if not suggestion:
            # 如果仍然未加载，直接查询
            suggestion = await item_suggestion_repository.get_by_item_id(db, item.id)

        return item, suggestion

    async def confirm(
        self,
        db: AsyncSession,
        item_id: int,
        confirm_mode: str,
        overrides: Optional[dict] = None,
        operator_ref: Optional[str] = None,
    ) -> Item:
        """确认 Item 建议"""
        from app.core.exceptions import BadRequestException
        
        # 1. 获取 Item
        item = await item_repository.get_with_suggestion(db, item_id)
        if not item:
            raise BadRequestException(f"Item {item_id} not found")

        # 2. 检查是否有 suggestion
        suggestion = item.suggestion
        if not suggestion:
            raise BadRequestException(
                f"Item {item_id} has no suggestion to confirm"
            )

        # 3. 检查状态
        if item.status != ItemStatus.PENDING_CONFIRM:
            raise BadRequestException(
                f"Only pending_confirm items can be confirmed. Current status: {item.status}"
            )
        
        # 4. 根据 confirm_mode 处理
        from_status = item.status
        
        if confirm_mode == "accept":
            # 全接受：直接复制 suggestion → final
            item = await item_repository.update_final_fields(
                db=db,
                item=item,
                title_final=suggestion.title_suggestion,
                final_type=suggestion.type_suggestion,
                final_priority=suggestion.priority_suggestion,
                final_project=suggestion.project_suggestion,
            )
        elif confirm_mode == "modify":
            # 修改：使用 overrides
            item = await item_repository.update_final_fields(
                db=db,
                item=item,
                title_final=overrides.get("title_final") if overrides else None,
                final_type=overrides.get("final_type") if overrides else None,
                final_priority=overrides.get("final_priority") if overrides else None,
                final_project=overrides.get("final_project") if overrides else None,
            )
        else:
            raise BadRequestException(f"Invalid confirm_mode: {confirm_mode}")
        
        # 5. 更新 Item 状态为 confirmed
        item = await item_repository.update_status(
            db=db,
            item=item,
            new_status=ItemStatus.CONFIRMED,
        )
        
        # 6. 标记 suggestion 为已确认
        await item_suggestion_repository.mark_confirmed(db, suggestion)
        
        # 7. 写入 action_log
        await action_log_service.log(
            db=db,
            biz_type=BizType.ITEM,
            biz_id=item.id,
            action_type=ActionType.ITEM_CONFIRMED,
            operator_type=OperatorType.USER,
            operator_ref=operator_ref or "unknown_user",
            from_status=from_status,
            to_status=ItemStatus.CONFIRMED,
            action_payload={
                "confirm_mode": confirm_mode,
                "suggestion_id": suggestion.id,
                "changes": {
                    "title_final": item.title_final,
                    "final_type": item.final_type,
                    "final_priority": item.final_priority,
                    "final_project": item.final_project,
                },
                "overrides": overrides if confirm_mode == "modify" else None,
            },
            comment=f"User confirmed suggestion (mode={confirm_mode})",
        )
        
        await db.commit()
        
        return item


# Global service instance
item_service = ItemService()

# Export repositories for router
from app.modules.item.repository import item_repository, item_suggestion_repository
