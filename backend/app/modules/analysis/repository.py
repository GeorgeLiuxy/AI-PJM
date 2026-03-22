"""Analysis repository - data access layer"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.modules.analysis.models import Analysis
from app.common.enums import AnalysisType, AnalysisStatus


class AnalysisRepository:
    """Analysis repository - 数据访问层"""

    async def create(
        self,
        db: AsyncSession,
        item_id: int,
    ) -> Analysis:
        """创建 Analysis（analysis_type 固定为 impact_assessment）"""
        analysis = Analysis(
            item_id=item_id,
            analysis_type=AnalysisType.IMPACT_ASSESSMENT,
            status=AnalysisStatus.PENDING,
        )
        db.add(analysis)
        return analysis

    async def get_by_id(
        self,
        db: AsyncSession,
        analysis_id: int,
    ) -> Optional[Analysis]:
        """根据 ID 获取 Analysis"""
        result = await db.execute(
            select(Analysis).where(Analysis.id == analysis_id)
        )
        return result.scalar_one_or_none()

    async def get_by_item_id(
        self,
        db: AsyncSession,
        item_id: int,
    ) -> Optional[Analysis]:
        """根据 item_id 获取 Analysis（一对一）"""
        result = await db.execute(
            select(Analysis).where(Analysis.item_id == item_id)
        )
        return result.scalar_one_or_none()

    async def get_by_id_with_item(
        self,
        db: AsyncSession,
        analysis_id: int,
    ) -> Optional[Analysis]:
        """根据 ID 获取 Analysis，预加载 Item"""
        result = await db.execute(
            select(Analysis)
            .options(selectinload(Analysis.item))
            .where(Analysis.id == analysis_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        db: AsyncSession,
        analysis: Analysis,
        new_status: str,
    ) -> Analysis:
        """更新 Analysis 状态"""
        analysis.status = new_status
        return analysis

    async def update_analysis_result(
        self,
        db: AsyncSession,
        analysis: Analysis,
        business_value_score: int,
        technical_impact_score: int,
        risk_level: str,
        candidate_capabilities_json: list[str],
        candidate_modules_json: list[str],
        similar_cases_json: list[dict],
        ai_recommendation: str,
        confidence_score: float,
        evidence_summary: str,
        missing_information: Optional[str],
        needs_deep_analysis: bool,
    ) -> Analysis:
        """更新分析结果（run 完成后）"""
        analysis.business_value_score = business_value_score
        analysis.technical_impact_score = technical_impact_score
        analysis.risk_level = risk_level
        analysis.candidate_capabilities_json = candidate_capabilities_json
        analysis.candidate_modules_json = candidate_modules_json
        analysis.similar_cases_json = similar_cases_json
        analysis.ai_recommendation = ai_recommendation
        analysis.confidence_score = confidence_score
        analysis.evidence_summary = evidence_summary
        analysis.missing_information = missing_information
        analysis.needs_deep_analysis = needs_deep_analysis
        return analysis

    async def update_final_recommendation(
        self,
        db: AsyncSession,
        analysis: Analysis,
        final_recommendation: str,
        review_comment: Optional[str] = None,
    ) -> Analysis:
        """更新最终结论（confirm/reject 后）"""
        analysis.final_recommendation = final_recommendation
        if review_comment is not None:
            analysis.review_comment = review_comment
        return analysis

    async def update_review_comment(
        self,
        db: AsyncSession,
        analysis: Analysis,
        review_comment: str,
    ) -> Analysis:
        """更新复核评论（reject 时）"""
        analysis.review_comment = review_comment
        return analysis


# Global repository instance
analysis_repository = AnalysisRepository()
