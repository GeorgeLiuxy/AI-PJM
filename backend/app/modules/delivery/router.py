"""Delivery v2 API endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.core.db import get_db
from app.modules.delivery.schemas import (
    AutoRepairExecutionRequest,
    CodingTaskCreateRequest,
    CodingTaskDetailResponse,
    CodingTaskResponse,
    DemandCreateRequest,
    DemandDetailResponse,
    DemandResponse,
    DeployRecordCreateRequest,
    DeployRecordResponse,
    ExecutionRunCreateRequest,
    ExecutionRunQueueItemResponse,
    ExecutionRunResponse,
    ImpactAnalysisCreateRequest,
    ImpactAnalysisResponse,
    ManualApprovalRequest,
    MergeRequestCreateRequest,
    MergeRequestRecordResponse,
    MergeRequestReviewRequest,
    RepoContextCreateRequest,
    RepoContextResponse,
    SpecCardResponse,
    SpecGenerateRequest,
    VerificationRecordCreateRequest,
    VerificationRecordResponse,
)
from app.modules.delivery.service import delivery_service


router = APIRouter(tags=["delivery"])


@router.get("/demands", response_model=dict)
async def list_demands(
    limit: int = 30,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    demands = await delivery_service.list_demands(db, limit=limit, offset=offset)
    return success_response(
        data=[DemandResponse.model_validate(demand).model_dump() for demand in demands],
        message="Success",
    )


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


@router.post("/demands/{demand_id}/manual-approval", response_model=dict)
async def record_manual_approval(
    demand_id: int,
    request: ManualApprovalRequest,
    db: AsyncSession = Depends(get_db),
):
    demand = await delivery_service.record_manual_approval(
        db=db,
        demand_id=demand_id,
        approved=request.approved,
        approver_ref=request.approver_ref,
        note=request.note,
    )
    return success_response(
        data=DemandDetailResponse.model_validate(demand).model_dump(),
        message="Manual approval recorded",
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
        data=CodingTaskDetailResponse.model_validate(task).model_dump(),
        message="Success",
    )


@router.post("/coding-tasks/{coding_task_id}/retry", response_model=dict)
async def retry_coding_task_execution(
    coding_task_id: int,
    db: AsyncSession = Depends(get_db),
):
    run = await delivery_service.retry_coding_task_execution(
        db=db,
        coding_task_id=coding_task_id,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution retry completed",
    )


@router.post("/coding-tasks/{coding_task_id}/auto-repair", response_model=dict)
async def auto_repair_coding_task_execution(
    coding_task_id: int,
    request: AutoRepairExecutionRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = request or AutoRepairExecutionRequest()
    runs = await delivery_service.auto_repair_coding_task_execution(
        db=db,
        coding_task_id=coding_task_id,
        executor_type=payload.executor_type,
        max_attempts=payload.max_attempts,
    )
    return success_response(
        data=[ExecutionRunResponse.model_validate(run).model_dump() for run in runs],
        message="Automatic repair completed",
    )


@router.post("/coding-tasks/{coding_task_id}/merge-request", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_merge_request_record(
    coding_task_id: int,
    request: MergeRequestCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = request or MergeRequestCreateRequest()
    record = await delivery_service.create_merge_request_record(
        db=db,
        coding_task_id=coding_task_id,
        execution_run_id=payload.execution_run_id,
        provider=payload.provider,
        target_branch=payload.target_branch,
        title=payload.title,
        url=payload.url,
    )
    return success_response(
        data=MergeRequestRecordResponse.model_validate(record).model_dump(),
        message="Merge request record created",
        code=201,
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


@router.get("/execution-runs", response_model=dict)
async def list_execution_runs(
    statuses: str | None = None,
    limit: int = 30,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    status_filters = [item.strip() for item in statuses.split(",") if item.strip()] if statuses else None
    runs = await delivery_service.list_execution_runs(
        db=db,
        statuses=status_filters,
        limit=limit,
        offset=offset,
    )
    return success_response(
        data=[_execution_queue_item(run) for run in runs],
        message="Success",
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


@router.get("/merge-requests/{merge_request_id}", response_model=dict)
async def get_merge_request_record(
    merge_request_id: int,
    db: AsyncSession = Depends(get_db),
):
    record = await delivery_service.get_merge_request_record(db, merge_request_id)
    return success_response(
        data=MergeRequestRecordResponse.model_validate(record).model_dump(),
        message="Success",
    )


@router.post("/merge-requests/{merge_request_id}/review", response_model=dict)
async def record_merge_request_review(
    merge_request_id: int,
    request: MergeRequestReviewRequest,
    db: AsyncSession = Depends(get_db),
):
    record = await delivery_service.record_merge_request_review(
        db=db,
        merge_request_id=merge_request_id,
        review_status=request.review_status,
        review_summary=request.review_summary,
        review_comments=request.review_comments,
        blocking_issues=request.blocking_issues,
    )
    return success_response(
        data=MergeRequestRecordResponse.model_validate(record).model_dump(),
        message="Merge request review recorded",
    )


@router.post("/merge-requests/{merge_request_id}/deployments", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_deploy_record(
    merge_request_id: int,
    request: DeployRecordCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    payload = request or DeployRecordCreateRequest()
    record = await delivery_service.create_deploy_record(
        db=db,
        merge_request_id=merge_request_id,
        provider=payload.provider,
        environment=payload.environment,
        url=payload.url,
    )
    return success_response(
        data=DeployRecordResponse.model_validate(record).model_dump(),
        message="Deployment record created",
        code=201,
    )


@router.get("/deployments/{deploy_record_id}", response_model=dict)
async def get_deploy_record(
    deploy_record_id: int,
    db: AsyncSession = Depends(get_db),
):
    record = await delivery_service.get_deploy_record(db, deploy_record_id)
    return success_response(
        data=DeployRecordResponse.model_validate(record).model_dump(),
        message="Success",
    )


@router.post("/deployments/{deploy_record_id}/verification", response_model=dict, status_code=status.HTTP_201_CREATED)
async def record_verification(
    deploy_record_id: int,
    request: VerificationRecordCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    record = await delivery_service.record_verification(
        db=db,
        deploy_record_id=deploy_record_id,
        status=request.status,
        verifier_ref=request.verifier_ref,
        summary=request.summary,
        evidence_links=request.evidence_links,
    )
    return success_response(
        data=VerificationRecordResponse.model_validate(record).model_dump(),
        message="Verification record created",
        code=201,
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


def _execution_queue_item(run):
    data = ExecutionRunResponse.model_validate(run).model_dump()
    task = run.coding_task
    demand = task.demand if task else None
    data.update(
        {
            "coding_task_title": task.title if task else "",
            "demand_id": task.demand_id if task else 0,
            "demand_title": demand.title if demand else None,
            "risk_level": demand.risk_level if demand else None,
        }
    )
    return ExecutionRunQueueItemResponse.model_validate(data).model_dump()
