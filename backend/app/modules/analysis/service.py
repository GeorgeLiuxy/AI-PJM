"""Analysis service - business logic layer"""

from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.analysis.models import Analysis
from app.modules.analysis.repository import analysis_repository
from app.modules.item.repository import item_repository
from app.modules.audit.service import action_log_service
from app.ai.analysis_service import analysis_service as mock_analysis_service
from app.common.enums import (
    AnalysisStatus, AnalysisType,
    ItemStatus, ActionType, OperatorType, BizType,
    Recommendation,
)


class AnalysisService:
    """Analysis service - 业务逻辑层"""

    async def create(
        self,
        db: AsyncSession,
        item_id: int,
        operator_ref: Optional[str] = None,
    ) -> Analysis:
        """创建 Analysis（仅允许对 confirmed 状态的 Item）"""
        from app.core.exceptions import BadRequestException

        # 1. 获取 Item
        item = await item_repository.get_by_id(db, item_id)
        if not item:
            raise BadRequestException(f"Item {item_id} not found")

        # 2. 检查 Item 状态
        if item.status != ItemStatus.CONFIRMED:
            raise BadRequestException(
                f"Item {item_id} is not in confirmed status. Current: {item.status}"
            )

        # 3. 检查是否已存在 Analysis
        existing = await analysis_repository.get_by_item_id(db, item_id)
        if existing:
            raise BadRequestException(
                f"Analysis already exists for item {item_id}"
            )

        # 4. 创建 Analysis
        analysis = await analysis_repository.create(
            db=db,
            item_id=item_id,
        )

        # 5. 更新 Item 状态为 analyzing
        from_status = item.status
        item = await item_repository.update_status(
            db=db,
            item=item,
            new_status=ItemStatus.ANALYZING,
        )

        # 6. 写入 action_logs
        await action_log_service.log(
            db=db,
            biz_type=BizType.ANALYSIS,
            biz_id=analysis.id,
            action_type=ActionType.ANALYSIS_CREATED,
            operator_type=OperatorType.USER,
            operator_ref=operator_ref or "system",
            from_status=None,
            to_status=AnalysisStatus.PENDING,
            action_payload={
                "item_id": item_id,
                "analysis_type": AnalysisType.IMPACT_ASSESSMENT,
            },
            comment="Analysis created from confirmed item",
        )

        await action_log_service.log(
            db=db,
            biz_type=BizType.ITEM,
            biz_id=item.id,
            action_type=ActionType.ITEM_STATUS_CHANGED_TO_ANALYZING,
            operator_type=OperatorType.USER,
            operator_ref=operator_ref or "system",
            from_status=from_status,
            to_status=ItemStatus.ANALYZING,
            action_payload={
                "analysis_id": analysis.id,
            },
            comment="Item status changed to analyzing (analysis created)",
        )

        await db.commit()

        return analysis

    async def run(
        self,
        db: AsyncSession,
        analysis_id: int,
    ) -> Analysis:
        """运行分析（仅允许 pending 状态）"""
        from app.core.exceptions import BadRequestException

        # 1. 获取 Analysis
        analysis = await analysis_repository.get_by_id_with_item(db, analysis_id)
        if not analysis:
            raise BadRequestException(f"Analysis {analysis_id} not found")

        # 2. 检查状态
        if analysis.status != AnalysisStatus.PENDING:
            raise BadRequestException(
                f"Analysis is not in pending status. Current: {analysis.status}"
            )

        # 3. 更新状态为 running
        from_status = analysis.status
        analysis = await analysis_repository.update_status(
            db=db,
            analysis=analysis,
            new_status=AnalysisStatus.RUNNING,
        )

        # 4. 写入 action_log: analysis_started
        await action_log_service.log(
            db=db,
            biz_type=BizType.ANALYSIS,
            biz_id=analysis.id,
            action_type=ActionType.ANALYSIS_STARTED,
            operator_type=OperatorType.AI,
            operator_ref="mock_analysis_service",
            from_status=from_status,
            to_status=AnalysisStatus.RUNNING,
            action_payload={
                "item_id": analysis.item_id,
            },
            comment="Analysis started (mock)",
        )

        await db.commit()

        # 5. 执行 Mock 分析
        ai_result = await mock_analysis_service.analyze(
            item_raw_input=analysis.item.raw_input,
            item_source_type=analysis.item.source_type,
        )

        # 6. 更新分析结果
        from_status = AnalysisStatus.RUNNING
        analysis = await analysis_repository.update_analysis_result(
            db=db,
            analysis=analysis,
            business_value_score=ai_result["business_value_score"],
            technical_impact_score=ai_result["technical_impact_score"],
            risk_level=ai_result["risk_level"],
            candidate_capabilities_json=ai_result["candidate_capabilities_json"],
            candidate_modules_json=ai_result["candidate_modules_json"],
            similar_cases_json=ai_result["similar_cases_json"],
            ai_recommendation=ai_result["ai_recommendation"],
            confidence_score=ai_result["confidence_score"],
            evidence_summary=ai_result["evidence_summary"],
            missing_information=ai_result["missing_information"],
            needs_deep_analysis=ai_result["needs_deep_analysis"],
        )

        # 7. 更新状态为 pending_review
        analysis = await analysis_repository.update_status(
            db=db,
            analysis=analysis,
            new_status=AnalysisStatus.PENDING_REVIEW,
        )

        # 8. 写入 action_log: analysis_completed
        await action_log_service.log(
            db=db,
            biz_type=BizType.ANALYSIS,
            biz_id=analysis.id,
            action_type=ActionType.ANALYSIS_COMPLETED,
            operator_type=OperatorType.AI,
            operator_ref="mock_analysis_service",
            from_status=from_status,
            to_status=AnalysisStatus.PENDING_REVIEW,
            action_payload={
                "item_id": analysis.item_id,
                "business_value_score": analysis.business_value_score,
                "technical_impact_score": analysis.technical_impact_score,
                "risk_level": analysis.risk_level,
                "ai_recommendation": analysis.ai_recommendation,
                "confidence_score": analysis.confidence_score,
            },
            comment="Analysis completed (mock)",
        )

        await db.commit()

        return analysis

    async def confirm(
        self,
        db: AsyncSession,
        analysis_id: int,
        final_recommendation: str,
        review_comment: Optional[str] = None,
        operator_ref: Optional[str] = None,
    ) -> Analysis:
        """确认分析（仅允许 pending_review 状态）"""
        from app.core.exceptions import BadRequestException

        # 1. 获取 Analysis
        analysis = await analysis_repository.get_by_id_with_item(db, analysis_id)
        if not analysis:
            raise BadRequestException(f"Analysis {analysis_id} not found")

        # 2. 检查状态
        if analysis.status != AnalysisStatus.PENDING_REVIEW:
            raise BadRequestException(
                f"Analysis is not in pending_review status. Current: {analysis.status}"
            )

        # 3. 更新最终结论
        from_status = analysis.status
        analysis = await analysis_repository.update_final_recommendation(
            db=db,
            analysis=analysis,
            final_recommendation=final_recommendation,
            review_comment=review_comment,
        )

        # 4. 更新 Analysis 状态为 confirmed
        analysis = await analysis_repository.update_status(
            db=db,
            analysis=analysis,
            new_status=AnalysisStatus.CONFIRMED,
        )

        # 5. 写入 action_log: analysis_confirmed
        await action_log_service.log(
            db=db,
            biz_type=BizType.ANALYSIS,
            biz_id=analysis.id,
            action_type=ActionType.ANALYSIS_CONFIRMED,
            operator_type=OperatorType.USER,
            operator_ref=operator_ref or "unknown_user",
            from_status=from_status,
            to_status=AnalysisStatus.CONFIRMED,
            action_payload={
                "item_id": analysis.item_id,
                "final_recommendation": final_recommendation,
                "ai_recommendation": analysis.ai_recommendation,
            },
            comment=f"User confirmed analysis (recommendation={final_recommendation})",
        )

        # 6. 更新 Item 状态为 decided
        item_from_status = analysis.item.status
        item = await item_repository.update_status(
            db=db,
            item=analysis.item,
            new_status=ItemStatus.DECIDED,
        )

        # 7. 写入 action_log: item_status_changed_to_decided
        await action_log_service.log(
            db=db,
            biz_type=BizType.ITEM,
            biz_id=item.id,
            action_type=ActionType.ITEM_STATUS_CHANGED_TO_DECIDED,
            operator_type=OperatorType.USER,
            operator_ref=operator_ref or "unknown_user",
            from_status=item_from_status,
            to_status=ItemStatus.DECIDED,
            action_payload={
                "analysis_id": analysis.id,
                "final_recommendation": final_recommendation,
            },
            comment="Item status changed to decided (analysis confirmed)",
        )

        await db.commit()

        return analysis

    async def reject(
        self,
        db: AsyncSession,
        analysis_id: int,
        review_comment: str,
        operator_ref: Optional[str] = None,
    ) -> Analysis:
        """驳回分析（回到 pending，可重新 run）"""
        from app.core.exceptions import BadRequestException

        # 1. 获取 Analysis
        analysis = await analysis_repository.get_by_id_with_item(db, analysis_id)
        if not analysis:
            raise BadRequestException(f"Analysis {analysis_id} not found")

        # 2. 检查状态
        if analysis.status != AnalysisStatus.PENDING_REVIEW:
            raise BadRequestException(
                f"Analysis is not in pending_review status. Current: {analysis.status}"
            )

        # 3. 更新复核评论
        from_status = analysis.status
        analysis = await analysis_repository.update_review_comment(
            db=db,
            analysis=analysis,
            review_comment=review_comment,
        )

        # 4. 更新状态为 pending（可重新 run）
        analysis = await analysis_repository.update_status(
            db=db,
            analysis=analysis,
            new_status=AnalysisStatus.PENDING,
        )

        # 5. 写入 action_log: analysis_rejected
        await action_log_service.log(
            db=db,
            biz_type=BizType.ANALYSIS,
            biz_id=analysis.id,
            action_type=ActionType.ANALYSIS_REJECTED,
            operator_type=OperatorType.USER,
            operator_ref=operator_ref or "unknown_user",
            from_status=from_status,
            to_status=AnalysisStatus.PENDING,  # 回到 pending
            action_payload={
                "item_id": analysis.item_id,
                "review_comment": review_comment,
            },
            comment=f"User rejected analysis, back to pending. Reason: {review_comment}",
        )

        # 注意：Item 状态保持 analyzing，不更新

        await db.commit()

        return analysis


# Global service instance
analysis_service = AnalysisService()

# Export repository for router
from app.modules.analysis.repository import analysis_repository
