"""Workbench service - business logic layer for workbench aggregation"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.workbench.repository import workbench_repository


class WorkbenchService:
    """Workbench service - home page aggregation and todos"""

    async def get_home_summary(
        self,
        db: AsyncSession,
    ) -> dict:
        """
        Get home page summary data

        Returns:
            dict with summary, todo_queue, recent_items, recent_outputs
        """
        # Get summary counts
        summary = await workbench_repository.get_summary_counts(db)

        # Get todo queue
        todo_queue = await workbench_repository.get_todos(db, limit=20)

        # Get recent items
        recent_items = await workbench_repository.get_recent_items(db, limit=10)

        # Get recent outputs
        recent_outputs = await workbench_repository.get_recent_outputs(db, limit=10)

        return {
            "summary": summary,
            "todo_queue": todo_queue,
            "recent_items": recent_items,
            "recent_outputs": recent_outputs,
        }

    async def get_todos(
        self,
        db: AsyncSession,
        limit: int = 50,
    ) -> dict:
        """
        Get all todos

        Returns:
            dict with todos list and breakdown counts
        """
        # Get todos
        todos = await workbench_repository.get_todos(db, limit=limit)

        # Calculate breakdown
        breakdown = {
            "pending_item_confirm": 0,
            "pending_analysis_review": 0,
            "pending_output_confirm": 0,
            "pending_output_adopt": 0,
        }

        for todo in todos:
            breakdown[todo["todo_type"]] += 1

        return {
            "todos": todos,
            "total": len(todos),
            "breakdown": breakdown,
        }


# Global service instance
workbench_service = WorkbenchService()
