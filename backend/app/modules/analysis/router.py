"""Analysis router - API endpoints"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.deps import get_operator_ref
from app.modules.analysis.service import analysis_service
from app.modules.analysis.schemas import (
    AnalysisCreateRequest,
    AnalysisCreateResponse,
    AnalysisRunResponse,
    AnalysisResponse,
    AnalysisConfirmRequest,
    AnalysisConfirmRejectResponse,
    AnalysisRejectRequest,
)
from app.common.responses import success_response


router = APIRouter(tags=["Analysis"])


@router.post(
    "/items/{item_id}/analysis",
    response_model=dict,
    status_code=status.HTTP_201_CREATED,
    summary="创建 Analysis",
    description="为已确认的 Item 创建影响评估分析（analysis_type 固定为 impact_assessment）"
)
async def create_analysis(
    item_id: int,
    db: AsyncSession = Depends(get_db),
    operator_ref: str = Depends(get_operator_ref),
):
    """创建 Analysis（不需要请求体）"""
    analysis = await analysis_service.create(
        db=db,
        item_id=item_id,
        operator_ref=operator_ref,
    )
    return success_response(
        data=AnalysisCreateResponse.model_validate(analysis),
        message="Analysis created",
        code=201,
    )


@router.post(
    "/analysis/{analysis_id}/run",
    response_model=dict,
    summary="运行分析",
    description="执行分析（仅允许 pending 状态）"
)
async def run_analysis(
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
):
    """运行分析"""
    analysis = await analysis_service.run(
        db=db,
        analysis_id=analysis_id,
    )
    return success_response(
        data=AnalysisRunResponse.model_validate(analysis),
        message="Analysis completed",
    )


@router.get(
    "/analysis/{analysis_id}",
    response_model=dict,
    summary="查询 Analysis",
    description="获取 Analysis 详情"
)
async def get_analysis(
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
):
    """查询 Analysis"""
    from app.modules.analysis.repository import analysis_repository

    analysis = await analysis_repository.get_by_id_with_item(db, analysis_id)
    if not analysis:
        from app.core.exceptions import NotFoundException
        raise NotFoundException(f"Analysis {analysis_id} not found")

    return success_response(
        data=AnalysisResponse.model_validate(analysis),
        message="Success",
    )


@router.post(
    "/analysis/{analysis_id}/confirm",
    response_model=dict,
    summary="确认分析",
    description="确认分析结论（仅允许 pending_review 状态）"
)
async def confirm_analysis(
    analysis_id: int,
    request: AnalysisConfirmRequest,
    db: AsyncSession = Depends(get_db),
    operator_ref: str = Depends(get_operator_ref),
):
    """确认分析"""
    analysis = await analysis_service.confirm(
        db=db,
        analysis_id=analysis_id,
        final_recommendation=request.final_recommendation,
        review_comment=request.review_comment,
        operator_ref=operator_ref,
    )
    return success_response(
        data=AnalysisConfirmRejectResponse.model_validate(analysis),
        message="Analysis confirmed",
    )


@router.post(
    "/analysis/{analysis_id}/reject",
    response_model=dict,
    summary="驳回分析",
    description="驳回分析结论，回到 pending 状态可重新运行"
)
async def reject_analysis(
    analysis_id: int,
    request: AnalysisRejectRequest,
    db: AsyncSession = Depends(get_db),
    operator_ref: str = Depends(get_operator_ref),
):
    """驳回分析"""
    analysis = await analysis_service.reject(
        db=db,
        analysis_id=analysis_id,
        review_comment=request.review_comment,
        operator_ref=operator_ref,
    )
    return success_response(
        data=AnalysisConfirmRejectResponse.model_validate(analysis),
        message="Analysis rejected, back to pending",
    )
