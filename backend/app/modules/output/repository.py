"""Output repository - data access layer"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.modules.output.models import Output
from app.common.enums import OutputType, OutputStatus, AdoptedTarget


class OutputRepository:
    """Output repository - data access layer"""

    async def create(
        self,
        db: AsyncSession,
        item_id: int,
        output_type: str,
        title: str,
        content: str,
        summary: Optional[str] = None,
        analysis_id: Optional[int] = None,
    ) -> Output:
        """Create Output"""
        output = Output(
            item_id=item_id,
            output_type=output_type,
            title=title,
            content=content,
            summary=summary,
            analysis_id=analysis_id,
        )
        db.add(output)
        return output

    async def get_by_id(
        self,
        db: AsyncSession,
        output_id: int,
    ) -> Optional[Output]:
        """Get Output by ID"""
        result = await db.execute(
            select(Output).where(Output.id == output_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_item(
        self,
        db: AsyncSession,
        output_id: int,
    ) -> Optional[Output]:
        """Get Output by ID with item relationship loaded"""
        result = await db.execute(
            select(Output)
            .options(selectinload(Output.item))
            .where(Output.id == output_id)
        )
        return result.scalar_one_or_none()

    async def get_by_item_and_type(
        self,
        db: AsyncSession,
        item_id: int,
        output_type: str,
    ) -> Optional[Output]:
        """Get Output by item_id and output_type"""
        result = await db.execute(
            select(Output)
            .where(Output.item_id == item_id)
            .where(Output.output_type == output_type)
        )
        return result.scalar_one_or_none()

    async def list_by_item_id(
        self,
        db: AsyncSession,
        item_id: int,
    ) -> list[Output]:
        """List all Outputs for an Item"""
        result = await db.execute(
            select(Output)
            .where(Output.item_id == item_id)
            .order_by(Output.created_at)
        )
        return list(result.scalars().all())

    async def update_status(
        self,
        db: AsyncSession,
        output: Output,
        new_status: str,
    ) -> Output:
        """Update Output status"""
        output.status = new_status
        return output

    async def confirm(
        self,
        db: AsyncSession,
        output: Output,
    ) -> Output:
        """Confirm Output"""
        from app.core.db import utc_now
        output.status = OutputStatus.CONFIRMED
        output.confirmed_at = utc_now()
        return output

    async def adopt(
        self,
        db: AsyncSession,
        output: Output,
        adopted_target: str,
    ) -> Output:
        """Adopt Output"""
        from app.core.db import utc_now
        output.status = OutputStatus.ADOPTED
        output.adopted_target = adopted_target
        output.adopted_at = utc_now()
        return output


# Global repository instance
output_repository = OutputRepository()
