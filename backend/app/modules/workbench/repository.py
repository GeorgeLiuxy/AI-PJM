"""Workbench repository - data access layer for workbench aggregation"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, case, literal_column, desc
from sqlalchemy.orm import selectinload

from app.modules.item.models import Item
from app.modules.analysis.models import Analysis
from app.modules.output.models import Output
from app.modules.audit.models import ActionLog
from app.common.enums import ItemStatus, AnalysisStatus, OutputStatus


class WorkbenchRepository:
    """Workbench repository - aggregation queries for workbench"""

    async def get_summary_counts(self, db: AsyncSession) -> dict:
        """
        Get summary counts for workbench home page

        Returns:
            dict with keys:
            - pending_item_confirm_count
            - pending_analysis_review_count
            - pending_output_confirm_count
            - done_item_count
        """
        # Query items counts
        items_result = await db.execute(
            select(
                func.sum(case((Item.status == ItemStatus.PENDING_CONFIRM, 1), else_=0)).label("pending_item_confirm"),
                func.sum(case((Item.status == ItemStatus.DONE, 1), else_=0)).label("done_item"),
            )
        )
        items_row = items_result.one()

        # Query analyses counts
        analyses_result = await db.execute(
            select(
                func.sum(case((Analysis.status == AnalysisStatus.PENDING_REVIEW, 1), else_=0)).label("pending_analysis_review"),
            )
        )
        analyses_row = analyses_result.one()

        # Query outputs counts
        outputs_result = await db.execute(
            select(
                func.sum(case((Output.status == OutputStatus.PENDING_CONFIRM, 1), else_=0)).label("pending_output_confirm"),
            )
        )
        outputs_row = outputs_result.one()

        return {
            "pending_item_confirm_count": items_row.pending_item_confirm or 0,
            "pending_analysis_review_count": analyses_row.pending_analysis_review or 0,
            "pending_output_confirm_count": outputs_row.pending_output_confirm or 0,
            "done_item_count": items_row.done_item or 0,
        }

    async def get_todos(
        self,
        db: AsyncSession,
        limit: int = 50,
    ) -> list[dict]:
        """
        Get todo queue items across all business types

        Returns list of todo items with fields:
        - todo_type, biz_type, biz_id, item_id, title, priority, updated_at
        """
        todos = []

        # 1. pending_item_confirm - Items with status = pending_confirm
        result = await db.execute(
            select(Item)
            .where(Item.status == ItemStatus.PENDING_CONFIRM)
            .order_by(desc(Item.updated_at))
            .limit(limit)
        )
        items = result.scalars().all()
        for item in items:
            # Use title_final if available, otherwise raw_input
            title = item.title_final if item.title_final else item.raw_input
            # Truncate if too long
            if len(title) > 100:
                title = title[:100] + "..."

            todos.append({
                "todo_type": "pending_item_confirm",
                "biz_type": "item",
                "biz_id": item.id,
                "item_id": item.id,
                "title": title,
                "priority": item.final_priority.value if item.final_priority else "medium",
                "updated_at": item.updated_at,
            })

        # 2. pending_analysis_review - Analyses with status = pending_review
        result = await db.execute(
            select(Analysis)
            .options(selectinload(Analysis.item))
            .where(Analysis.status == AnalysisStatus.PENDING_REVIEW)
            .order_by(desc(Analysis.updated_at))
            .limit(limit)
        )
        analyses = result.scalars().all()
        for analysis in analyses:
            # Title based on associated item
            item_title = analysis.item.title_final if analysis.item.title_final else analysis.item.raw_input
            if len(item_title) > 80:
                item_title = item_title[:80] + "..."
            title = f"分析: {item_title}"

            todos.append({
                "todo_type": "pending_analysis_review",
                "biz_type": "analysis",
                "biz_id": analysis.id,
                "item_id": analysis.item_id,
                "title": title,
                "priority": "medium",  # Analysis doesn't have priority, default to medium
                "updated_at": analysis.updated_at,
            })

        # 3. pending_output_confirm - Outputs with status = pending_confirm
        result = await db.execute(
            select(Output)
            .options(selectinload(Output.item))
            .where(Output.status == OutputStatus.PENDING_CONFIRM)
            .order_by(desc(Output.updated_at))
            .limit(limit)
        )
        outputs = result.scalars().all()
        for output in outputs:
            # Use output title
            title = f"{output.output_type}: {output.title}"
            if len(title) > 100:
                title = title[:100] + "..."

            todos.append({
                "todo_type": "pending_output_confirm",
                "biz_type": "output",
                "biz_id": output.id,
                "item_id": output.item_id,
                "title": title,
                "priority": "medium",  # Output doesn't have priority
                "updated_at": output.updated_at,
            })

        # 4. pending_output_adopt - Outputs with status = confirmed
        result = await db.execute(
            select(Output)
            .options(selectinload(Output.item))
            .where(Output.status == OutputStatus.CONFIRMED)
            .order_by(desc(Output.updated_at))
            .limit(limit)
        )
        outputs = result.scalars().all()
        for output in outputs:
            title = f"{output.output_type}: {output.title}"
            if len(title) > 100:
                title = title[:100] + "..."

            todos.append({
                "todo_type": "pending_output_adopt",
                "biz_type": "output",
                "biz_id": output.id,
                "item_id": output.item_id,
                "title": title,
                "priority": "low",
                "updated_at": output.updated_at,
            })

        # Sort todos by priority group and updated_at
        priority_order = {
            "pending_analysis_review": 0,
            "pending_output_confirm": 1,
            "pending_item_confirm": 2,
            "pending_output_adopt": 3,
        }

        # First sort by updated_at DESC
        todos.sort(key=lambda x: x["updated_at"], reverse=True)

        # Then sort by priority ASC (stable sort preserves updated_at order within same priority)
        todos.sort(key=lambda x: priority_order[x["todo_type"]])

        # Limit total results
        return todos[:limit]

    async def get_recent_items(
        self,
        db: AsyncSession,
        limit: int = 10,
    ) -> list[Item]:
        """Get recent items ordered by updated_at"""
        result = await db.execute(
            select(Item)
            .order_by(desc(Item.updated_at))
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_recent_outputs(
        self,
        db: AsyncSession,
        limit: int = 10,
    ) -> list[Output]:
        """Get recent outputs ordered by created_at"""
        result = await db.execute(
            select(Output)
            .order_by(desc(Output.created_at))
            .limit(limit)
        )
        return list(result.scalars().all())


# Global repository instance
workbench_repository = WorkbenchRepository()
