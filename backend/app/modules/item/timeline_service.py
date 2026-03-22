"""Timeline service - query and assemble action_logs for item timeline"""

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_

from app.modules.item.models import Item
from app.modules.analysis.models import Analysis
from app.modules.output.models import Output
from app.modules.audit.models import ActionLog
from app.core.exceptions import NotFoundException


class TimelineService:
    """Timeline service - assemble action_logs for item timeline"""

    async def get_item_timeline(
        self,
        db: AsyncSession,
        item_id: int,
    ) -> dict:
        """
        Get timeline for an item

        Includes action_logs for:
        - The item itself
        - All analyses associated with this item
        - All outputs associated with this item

        Args:
            db: Database session
            item_id: Item ID

        Returns:
            dict with item_id, timeline list, and total count
        """
        # 1. Verify item exists
        result = await db.execute(select(Item).where(Item.id == item_id))
        item = result.scalar_one_or_none()
        if not item:
            raise NotFoundException(f"Item {item_id} not found")

        # 2. Get all analysis IDs for this item
        result = await db.execute(
            select(Analysis.id).where(Analysis.item_id == item_id)
        )
        analysis_ids = [row[0] for row in result.all()]

        # 3. Get all output IDs for this item
        result = await db.execute(
            select(Output.id).where(Output.item_id == item_id)
        )
        output_ids = [row[0] for row in result.all()]

        # 4. Query all relevant action_logs
        # - Item logs (biz_type='item' AND biz_id=item_id)
        # - Analysis logs (biz_type='analysis' AND biz_id IN analysis_ids)
        # - Output logs (biz_type='output' AND biz_id IN output_ids)

        conditions = []

        # Item logs
        conditions.append(
            and_(
                ActionLog.biz_type == "item",
                ActionLog.biz_id == item_id
            )
        )

        # Analysis logs
        if analysis_ids:
            conditions.append(
                and_(
                    ActionLog.biz_type == "analysis",
                    ActionLog.biz_id.in_(analysis_ids)
                )
            )

        # Output logs
        if output_ids:
            conditions.append(
                and_(
                    ActionLog.biz_type == "output",
                    ActionLog.biz_id.in_(output_ids)
                )
            )

        # Combine with OR
        if conditions:
            query = select(ActionLog).where(or_(*conditions))
        else:
            # Only item logs if no analyses or outputs
            query = select(ActionLog).where(
                and_(
                    ActionLog.biz_type == "item",
                    ActionLog.biz_id == item_id
                )
            )

        # Order by created_at ASC
        query = query.order_by(ActionLog.created_at)

        result = await db.execute(query)
        action_logs = result.scalars().all()

        # 5. Convert to timeline response format
        timeline = []
        for log in action_logs:
            timeline.append({
                "id": log.id,
                "action_type": log.action_type,
                "biz_type": log.biz_type,
                "biz_id": log.biz_id,
                "operator_type": log.operator_type,
                "operator_ref": log.operator_ref,
                "from_status": log.from_status,
                "to_status": log.to_status,
                "comment": log.comment,
                "created_at": log.created_at,
            })

        return {
            "item_id": item_id,
            "timeline": timeline,
            "total": len(timeline),
        }


# Global service instance
timeline_service = TimelineService()
