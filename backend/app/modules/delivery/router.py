"""Delivery v2 API endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.core.db import get_db
from app.modules.delivery.schemas import (
    CodingTaskCreateRequest,
    CodingTaskResponse,
    DemandCreateRequest,
    DemandDetailResponse,
    DemandResponse,
    ExecutionRunCreateRequest,
    ExecutionRunResponse,
    ImpactAnalysisCreateRequest,
    ImpactAnalysisResponse,
    RepoContextCreateRequest,
    RepoContextResponse,
    SpecCardResponse,
    SpecGenerateRequest,
)
from app.modules.delivery.service import delivery_service


router = APIRouter(tags=["delivery"])


@router.post("/demands", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_demand(
    request: DemandCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    demand = await delivery_service.create_demand(
        db=db,
        raw_input=request.raw_input,
        source_type=request.source_type,
        title=request.title,
        requester_ref=request.requester_ref,
        context_payload=request.context_payload,
    )
    return success_response(
        data=DemandResponse.model_validate(demand).model_dump(),
        message="Demand created",
        code=201,
    )


@router.get("/demands/{demand_id}", response_model=dict)
async def get_demand(
    demand_id: int,
    db: AsyncSession = Depends(get_db),
):
    demand = await delivery_service.get_demand_detail(db, demand_id)
    return success_response(
        data=DemandDetailResponse.model_validate(demand).model_dump(),
        message="Success",
    )


@router.post("/demands/{demand_id}/spec", response_model=dict, status_code=status.HTTP_201_CREATED)
async def generate_spec(
    demand_id: int,
    request: SpecGenerateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = request or SpecGenerateRequest()
    spec = await delivery_service.generate_spec(
        db=db,
        demand_id=demand_id,
        auto_approve_low_risk=payload.auto_approve_low_risk,
    )
    return success_response(
        data=SpecCardResponse.model_validate(spec).model_dump(),
        message="Spec generated",
        code=201,
    )


@router.get("/spec-cards/{spec_card_id}", response_model=dict)
async def get_spec_card(
    spec_card_id: int,
    db: AsyncSession = Depends(get_db),
):
    spec = await delivery_service.get_spec_card(db, spec_card_id)
    return success_response(
        data=SpecCardResponse.model_validate(spec).model_dump(),
        message="Success",
    )


@router.post("/demands/{demand_id}/repo-context", response_model=dict, status_code=status.HTTP_201_CREATED)
async def collect_repo_context(
    demand_id: int,
    request: RepoContextCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = request or RepoContextCreateRequest()
    repo_context = await delivery_service.collect_repo_context(
        db=db,
        demand_id=demand_id,
        force_refresh=payload.force_refresh,
    )
    return success_response(
        data=RepoContextResponse.model_validate(repo_context).model_dump(),
        message="Repo context collected",
        code=201,
    )


@router.get("/repo-contexts/{repo_context_id}", response_model=dict)
async def get_repo_context(
    repo_context_id: int,
    db: AsyncSession = Depends(get_db),
):
    repo_context = await delivery_service.get_repo_context(db, repo_context_id)
    return success_response(
        data=RepoContextResponse.model_validate(repo_context).model_dump(),
        message="Success",
    )


@router.post("/demands/{demand_id}/impact-analysis", response_model=dict, status_code=status.HTTP_201_CREATED)
async def analyze_impact(
    demand_id: int,
    request: ImpactAnalysisCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = request or ImpactAnalysisCreateRequest()
    analysis = await delivery_service.analyze_impact(
        db=db,
        demand_id=demand_id,
        repo_context_id=payload.repo_context_id,
    )
    return success_response(
        data=ImpactAnalysisResponse.model_validate(analysis).model_dump(),
        message="Impact analysis created",
        code=201,
    )


@router.get("/impact-analyses/{impact_analysis_id}", response_model=dict)
async def get_impact_analysis(
    impact_analysis_id: int,
    db: AsyncSession = Depends(get_db),
):
    analysis = await delivery_service.get_impact_analysis(db, impact_analysis_id)
    return success_response(
        data=ImpactAnalysisResponse.model_validate(analysis).model_dump(),
        message="Success",
    )


@router.post("/spec-cards/{spec_card_id}/coding-task", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_coding_task(
    spec_card_id: int,
    request: CodingTaskCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = request or CodingTaskCreateRequest()
    task = await delivery_service.create_coding_task(
        db=db,
        spec_card_id=spec_card_id,
        allowed_paths=payload.allowed_paths,
        required_checks=payload.required_checks,
    )
    return success_response(
        data=CodingTaskResponse.model_validate(task).model_dump(),
        message="Coding task created",
        code=201,
    )


@router.get("/coding-tasks/{coding_task_id}", response_model=dict)
async def get_coding_task(
    coding_task_id: int,
    db: AsyncSession = Depends(get_db),
):
    task = await delivery_service.get_coding_task(db, coding_task_id)
    return success_response(
        data=CodingTaskResponse.model_validate(task).model_dump(),
        message="Success",
    )


@router.post("/coding-tasks/{coding_task_id}/runs", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_execution_run(
    coding_task_id: int,
    request: ExecutionRunCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = request or ExecutionRunCreateRequest()
    run = await delivery_service.create_execution_run(
        db=db,
        coding_task_id=coding_task_id,
        executor_type=payload.executor_type,
        trigger_mode=payload.trigger_mode,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run created",
        code=201,
    )


@router.get("/execution-runs/{execution_run_id}", response_model=dict)
async def get_execution_run(
    execution_run_id: int,
    db: AsyncSession = Depends(get_db),
):
    run = await delivery_service.get_execution_run(db, execution_run_id)
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Success",
    )


@router.post("/execution-runs/{execution_run_id}/dispatch", response_model=dict)
async def dispatch_execution_run(
    execution_run_id: int,
    db: AsyncSession = Depends(get_db),
):
    run = await delivery_service.dispatch_execution_run(db, execution_run_id)
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run dispatched",
    )
