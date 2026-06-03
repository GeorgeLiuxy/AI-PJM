"""Delivery v2 API endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.core.db import get_db
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.auth.dependencies import get_current_principal, require_capability
from app.modules.auth.service import AuthPrincipal
from app.modules.delivery.repository import delivery_repository
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
    ExecutionRunControlRequest,
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "read")
    demands = await delivery_service.list_demands(
        db,
        limit=limit,
        offset=offset,
        project_ids=principal.accessible_project_ids,
    )
    return success_response(
        data=[DemandResponse.model_validate(demand).model_dump() for demand in demands],
        message="Success",
    )


@router.post("/demands", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_demand(
    request: DemandCreateRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    project_id = _resolve_create_project_id(principal, request.project_id)
    require_capability(principal, "operate", project_id)
    demand = await delivery_service.create_demand(
        db=db,
        raw_input=request.raw_input,
        source_type=request.source_type,
        title=request.title,
        requester_ref=request.requester_ref or principal.username,
        context_payload=request.context_payload,
        project_id=project_id,
        created_by_user_id=principal.user_id,
        actor_ref=principal.username,
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    demand = await delivery_service.get_demand_detail(db, demand_id)
    require_capability(principal, "read", demand.project_id)
    return success_response(
        data=DemandDetailResponse.model_validate(demand).model_dump(),
        message="Success",
    )


@router.post("/demands/{demand_id}/manual-approval", response_model=dict)
async def record_manual_approval(
    demand_id: int,
    request: ManualApprovalRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_demand_permission(db, demand_id, principal, "review")
    demand = await delivery_service.record_manual_approval(
        db=db,
        demand_id=demand_id,
        approved=request.approved,
        approver_ref=request.approver_ref or principal.username,
        note=request.note,
        actor_user_id=principal.user_id,
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_demand_permission(db, demand_id, principal, "operate")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_spec_permission(db, spec_card_id, principal, "read")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_demand_permission(db, demand_id, principal, "operate")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_repo_context_permission(db, repo_context_id, principal, "read")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_demand_permission(db, demand_id, principal, "operate")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_impact_permission(db, impact_analysis_id, principal, "read")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_spec_permission(db, spec_card_id, principal, "operate")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_coding_task_permission(db, coding_task_id, principal, "read")
    task = await delivery_service.get_coding_task(db, coding_task_id)
    return success_response(
        data=CodingTaskDetailResponse.model_validate(task).model_dump(),
        message="Success",
    )


@router.post("/coding-tasks/{coding_task_id}/retry", response_model=dict)
async def retry_coding_task_execution(
    coding_task_id: int,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_coding_task_permission(db, coding_task_id, principal, "operate")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_coding_task_permission(db, coding_task_id, principal, "operate")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_coding_task_permission(db, coding_task_id, principal, "operate")
    payload = request or MergeRequestCreateRequest()
    record = await delivery_service.create_merge_request_record(
        db=db,
        coding_task_id=coding_task_id,
        execution_run_id=payload.execution_run_id,
        provider=payload.provider,
        target_branch=payload.target_branch,
        title=payload.title,
        url=payload.url,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_coding_task_permission(db, coding_task_id, principal, "operate")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "read")
    status_filters = [item.strip() for item in statuses.split(",") if item.strip()] if statuses else None
    runs = await delivery_service.list_execution_runs(
        db=db,
        statuses=status_filters,
        limit=limit,
        offset=offset,
        project_ids=principal.accessible_project_ids,
    )
    return success_response(
        data=[_execution_queue_item(run) for run in runs],
        message="Success",
    )


@router.get("/execution-runs/{execution_run_id}", response_model=dict)
async def get_execution_run(
    execution_run_id: int,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_execution_run_permission(db, execution_run_id, principal, "read")
    run = await delivery_service.get_execution_run(db, execution_run_id)
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Success",
    )


@router.get("/merge-requests/{merge_request_id}", response_model=dict)
async def get_merge_request_record(
    merge_request_id: int,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_merge_request_permission(db, merge_request_id, principal, "read")
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_merge_request_permission(db, merge_request_id, principal, "review")
    record = await delivery_service.record_merge_request_review(
        db=db,
        merge_request_id=merge_request_id,
        review_status=request.review_status,
        review_summary=request.review_summary,
        review_comments=request.review_comments,
        blocking_issues=request.blocking_issues,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=MergeRequestRecordResponse.model_validate(record).model_dump(),
        message="Merge request review recorded",
    )


@router.post("/merge-requests/{merge_request_id}/sync-review", response_model=dict)
async def sync_merge_request_remote_review(
    merge_request_id: int,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_merge_request_permission(db, merge_request_id, principal, "review")
    record = await delivery_service.sync_merge_request_remote_review(
        db=db,
        merge_request_id=merge_request_id,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=MergeRequestRecordResponse.model_validate(record).model_dump(),
        message="Merge request remote review synced",
    )


@router.post("/merge-requests/{merge_request_id}/auto-repair", response_model=dict)
async def auto_repair_merge_request_review(
    merge_request_id: int,
    request: AutoRepairExecutionRequest | None = None,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_merge_request_permission(db, merge_request_id, principal, "operate")
    payload = request or AutoRepairExecutionRequest()
    runs = await delivery_service.auto_repair_merge_request_review(
        db=db,
        merge_request_id=merge_request_id,
        executor_type=payload.executor_type,
        max_attempts=payload.max_attempts,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=[ExecutionRunResponse.model_validate(run).model_dump() for run in runs],
        message="Merge request review repair completed",
    )


@router.post("/merge-requests/{merge_request_id}/deployments", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_deploy_record(
    merge_request_id: int,
    request: DeployRecordCreateRequest | None = None,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_merge_request_permission(db, merge_request_id, principal, "operate")
    payload = request or DeployRecordCreateRequest()
    record = await delivery_service.create_deploy_record(
        db=db,
        merge_request_id=merge_request_id,
        provider=payload.provider,
        environment=payload.environment,
        url=payload.url,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_deploy_record_permission(db, deploy_record_id, principal, "read")
    record = await delivery_service.get_deploy_record(db, deploy_record_id)
    return success_response(
        data=DeployRecordResponse.model_validate(record).model_dump(),
        message="Success",
    )


@router.post("/deployments/{deploy_record_id}/sync-status", response_model=dict)
async def sync_deploy_record_status(
    deploy_record_id: int,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_deploy_record_permission(db, deploy_record_id, principal, "operate")
    record = await delivery_service.sync_deploy_record_status(
        db=db,
        deploy_record_id=deploy_record_id,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=DeployRecordResponse.model_validate(record).model_dump(),
        message="Deployment status synced",
    )


@router.post("/deployments/{deploy_record_id}/redeploy", response_model=dict, status_code=status.HTTP_201_CREATED)
async def redeploy_deploy_record(
    deploy_record_id: int,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_deploy_record_permission(db, deploy_record_id, principal, "operate")
    record = await delivery_service.redeploy_deploy_record(
        db=db,
        deploy_record_id=deploy_record_id,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=DeployRecordResponse.model_validate(record).model_dump(),
        message="Deployment redeployed",
        code=201,
    )


@router.post("/deployments/{deploy_record_id}/verification", response_model=dict, status_code=status.HTTP_201_CREATED)
async def record_verification(
    deploy_record_id: int,
    request: VerificationRecordCreateRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_deploy_record_permission(db, deploy_record_id, principal, "review")
    record = await delivery_service.record_verification(
        db=db,
        deploy_record_id=deploy_record_id,
        status=request.status,
        verifier_ref=request.verifier_ref or principal.username,
        summary=request.summary,
        evidence_links=request.evidence_links,
        actor_user_id=principal.user_id,
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
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_execution_run_permission(db, execution_run_id, principal, "operate")
    run = await delivery_service.dispatch_execution_run(db, execution_run_id)
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run dispatched",
    )


@router.post("/execution-runs/{execution_run_id}/pause", response_model=dict)
async def pause_execution_run(
    execution_run_id: int,
    request: ExecutionRunControlRequest | None = None,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_execution_run_permission(db, execution_run_id, principal, "operate")
    payload = request or ExecutionRunControlRequest()
    run = await delivery_service.pause_execution_run(
        db=db,
        execution_run_id=execution_run_id,
        reason=payload.reason,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run paused",
    )


@router.post("/execution-runs/{execution_run_id}/resume", response_model=dict)
async def resume_execution_run(
    execution_run_id: int,
    request: ExecutionRunControlRequest | None = None,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_execution_run_permission(db, execution_run_id, principal, "operate")
    payload = request or ExecutionRunControlRequest()
    run = await delivery_service.resume_execution_run(
        db=db,
        execution_run_id=execution_run_id,
        reason=payload.reason,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run resumed",
    )


@router.post("/execution-runs/{execution_run_id}/cancel", response_model=dict)
async def cancel_execution_run(
    execution_run_id: int,
    request: ExecutionRunControlRequest | None = None,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    await _require_execution_run_permission(db, execution_run_id, principal, "operate")
    payload = request or ExecutionRunControlRequest()
    run = await delivery_service.cancel_execution_run(
        db=db,
        execution_run_id=execution_run_id,
        reason=payload.reason,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run cancelled",
    )


def _resolve_create_project_id(principal: AuthPrincipal, requested_project_id: int | None) -> int | None:
    if not principal.auth_enabled:
        return requested_project_id
    project_id = requested_project_id or principal.default_project_id
    if project_id is None:
        raise BadRequestException("A project is required before creating delivery work")
    return project_id


async def _require_demand_permission(
    db: AsyncSession,
    demand_id: int,
    principal: AuthPrincipal,
    capability: str,
):
    demand = await delivery_repository.get_demand(db, demand_id)
    if not demand:
        raise NotFoundException(f"Demand {demand_id} not found")
    require_capability(principal, capability, demand.project_id)
    return demand


async def _require_spec_permission(
    db: AsyncSession,
    spec_card_id: int,
    principal: AuthPrincipal,
    capability: str,
):
    spec = await delivery_repository.get_spec_card(db, spec_card_id)
    if not spec:
        raise NotFoundException(f"Spec card {spec_card_id} not found")
    await _require_demand_permission(db, spec.demand_id, principal, capability)
    return spec


async def _require_repo_context_permission(
    db: AsyncSession,
    repo_context_id: int,
    principal: AuthPrincipal,
    capability: str,
):
    repo_context = await delivery_repository.get_repo_context(db, repo_context_id)
    if not repo_context:
        raise NotFoundException(f"Repo context {repo_context_id} not found")
    await _require_demand_permission(db, repo_context.demand_id, principal, capability)
    return repo_context


async def _require_impact_permission(
    db: AsyncSession,
    impact_analysis_id: int,
    principal: AuthPrincipal,
    capability: str,
):
    impact = await delivery_repository.get_impact_analysis(db, impact_analysis_id)
    if not impact:
        raise NotFoundException(f"Impact analysis {impact_analysis_id} not found")
    await _require_demand_permission(db, impact.demand_id, principal, capability)
    return impact


async def _require_coding_task_permission(
    db: AsyncSession,
    coding_task_id: int,
    principal: AuthPrincipal,
    capability: str,
):
    task = await delivery_repository.get_coding_task(db, coding_task_id)
    if not task:
        raise NotFoundException(f"Coding task {coding_task_id} not found")
    await _require_demand_permission(db, task.demand_id, principal, capability)
    return task


async def _require_execution_run_permission(
    db: AsyncSession,
    execution_run_id: int,
    principal: AuthPrincipal,
    capability: str,
):
    run = await delivery_repository.get_execution_run(db, execution_run_id)
    if not run:
        raise NotFoundException(f"Execution run {execution_run_id} not found")
    await _require_coding_task_permission(db, run.coding_task_id, principal, capability)
    return run


async def _require_merge_request_permission(
    db: AsyncSession,
    merge_request_id: int,
    principal: AuthPrincipal,
    capability: str,
):
    record = await delivery_repository.get_merge_request_record(db, merge_request_id)
    if not record:
        raise NotFoundException(f"Merge request record {merge_request_id} not found")
    await _require_coding_task_permission(db, record.coding_task_id, principal, capability)
    return record


async def _require_deploy_record_permission(
    db: AsyncSession,
    deploy_record_id: int,
    principal: AuthPrincipal,
    capability: str,
):
    record = await delivery_repository.get_deploy_record(db, deploy_record_id)
    if not record:
        raise NotFoundException(f"Deploy record {deploy_record_id} not found")
    await _require_coding_task_permission(db, record.coding_task_id, principal, capability)
    return record


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
