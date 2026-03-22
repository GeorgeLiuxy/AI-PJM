"""Item repository for data access"""

from typing import Optional
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.item.models import Item, ItemSuggestion
from app.common.enums import ItemStatus


class ItemRepository:
    """Item repository - 数据访问层"""
    
    async def create(
        self,
        db: AsyncSession,
        raw_input: str,
        source_type: str,
    ) -> Item:
        """创建 Item"""
        item = Item(
            raw_input=raw_input,
            source_type=source_type,
            status=ItemStatus.DRAFT,
        )
        db.add(item)
        await db.flush()
        return item
    
    async def get_by_id(
        self,
        db: AsyncSession,
        item_id: int,
    ) -> Optional[Item]:
        """根据 ID 获取 Item"""
        result = await db.execute(
            select(Item).where(Item.id == item_id)
        )
        return result.scalar_one_or_none()
    
    async def get_with_suggestion(
        self,
        db: AsyncSession,
        item_id: int,
    ) -> Optional[Item]:
        """
        根据 ID 获取 Item（包含关联的 Suggestion）

        使用 selectinload 预加载 suggestion
        """
        result = await db.execute(
            select(Item)
            .options(selectinload(Item.suggestion))
            .where(Item.id == item_id)
        )
        return result.scalar_one_or_none()
    
    async def update_status(
        self,
        db: AsyncSession,
        item: Item,
        new_status: str,
    ) -> Item:
        """更新 Item 状态"""
        item.status = new_status
        await db.flush()
        return item
    
    async def update_final_fields(
        self,
        db: AsyncSession,
        item: Item,
        title_final: Optional[str] = None,
        final_type: Optional[str] = None,
        final_priority: Optional[str] = None,
        final_project: Optional[str] = None,
    ) -> Item:
        """更新 Item 的最终确认字段"""
        if title_final is not None:
            item.title_final = title_final
        if final_type is not None:
            item.final_type = final_type
        if final_priority is not None:
            item.final_priority = final_priority
        if final_project is not None:
            item.final_project = final_project
        
        await db.flush()
        return item


class ItemSuggestionRepository:
    """ItemSuggestion repository - 数据访问层"""
    
    async def create(
        self,
        db: AsyncSession,
        item_id: int,
        title_suggestion: str,
        type_suggestion: str,
        priority_suggestion: str,
        project_suggestion: Optional[str] = None,
        modules_suggestion_json: Optional[list] = None,
        impact_scope_suggestion: Optional[str] = None,
        pending_questions_json: Optional[list] = None,
        similar_cases_json: Optional[list] = None,
        recommendation_suggestion: Optional[str] = None,
        confidence_score: Optional[float] = None,
        evidence_summary: Optional[str] = None,
        ai_model_version: Optional[str] = None,
    ) -> ItemSuggestion:
        """创建 ItemSuggestion"""
        suggestion = ItemSuggestion(
            item_id=item_id,
            title_suggestion=title_suggestion,
            type_suggestion=type_suggestion,
            priority_suggestion=priority_suggestion,
            project_suggestion=project_suggestion,
            modules_suggestion_json=modules_suggestion_json,
            impact_scope_suggestion=impact_scope_suggestion,
            pending_questions_json=pending_questions_json,
            similar_cases_json=similar_cases_json,
            recommendation_suggestion=recommendation_suggestion,
            confidence_score=confidence_score,
            evidence_summary=evidence_summary,
            ai_model_version=ai_model_version,
            is_confirmed=False,
        )
        db.add(suggestion)
        await db.flush()
        return suggestion
    
    async def get_by_item_id(
        self,
        db: AsyncSession,
        item_id: int,
    ) -> Optional[ItemSuggestion]:
        """根据 item_id 获取 ItemSuggestion（一对一）"""
        result = await db.execute(
            select(ItemSuggestion).where(ItemSuggestion.item_id == item_id)
        )
        return result.scalar_one_or_none()
    
    async def mark_confirmed(
        self,
        db: AsyncSession,
        suggestion: ItemSuggestion,
    ) -> ItemSuggestion:
        """标记建议为已确认"""
        suggestion.is_confirmed = True
        await db.flush()
        return suggestion


# Global repository instances
item_repository = ItemRepository()
item_suggestion_repository = ItemSuggestionRepository()
