"""Internal Symphony bridge API."""

from hmac import compare_digest

from fastapi import APIRouter, Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.core.config import settings
from app.core.db import get_db
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.modules.delivery.schemas import (
    ExecutionRunQueueItemResponse,
    ExecutionRunResponse,
    SymphonyBridgeClaimRequest,
    SymphonyBridgeCompleteRequest,
    SymphonyBridgeEventRequest,
    SymphonyBridgeHeartbeatRequest,
    SymphonyBridgeTaskPackageResponse,
)
from app.modules.delivery.symphony_bridge import symphony_bridge_service


router = APIRouter(
    prefix="/internal/symphony",
    tags=["symphony-bridge"],
)


async def require_symphony_bridge_token(
    x_symphony_bridge_token: str | None = Header(default=None, alias="X-Symphony-Bridge-Token"),
) -> None:
    expected = settings.symphony_bridge_token.strip()
    if not expected:
        raise ForbiddenException("Symphony bridge token is not configured")
    if not x_symphony_bridge_token or not compare_digest(x_symphony_bridge_token, expected):
        raise UnauthorizedException("Invalid Symphony bridge token")


@router.get("/execution-runs", response_model=dict, dependencies=[Depends(require_symphony_bridge_token)])
async def list_symphony_execution_runs(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
):
    runs = await symphony_bridge_service.list_claimable_runs(db, limit=limit)
    return success_response(
        data=[ExecutionRunQueueItemResponse.model_validate(_queue_item(run)).model_dump() for run in runs],
        message="Success",
    )


@router.get(
    "/execution-runs/{execution_run_id}/task-package",
    response_model=dict,
    dependencies=[Depends(require_symphony_bridge_token)],
)
async def get_symphony_task_package(
    execution_run_id: int,
    db: AsyncSession = Depends(get_db),
):
    package = await symphony_bridge_service.get_task_package(db, execution_run_id)
    return success_response(
        data=SymphonyBridgeTaskPackageResponse.model_validate(package).model_dump(),
        message="Success",
    )


@router.post(
    "/execution-runs/{execution_run_id}/claim",
    response_model=dict,
    dependencies=[Depends(require_symphony_bridge_token)],
)
async def claim_symphony_execution_run(
    execution_run_id: int,
    request: SymphonyBridgeClaimRequest,
    db: AsyncSession = Depends(get_db),
):
    run = await symphony_bridge_service.claim_run(
        db=db,
        execution_run_id=execution_run_id,
        worker_id=request.worker_id,
        lease_seconds=request.lease_seconds,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run claimed",
    )


@router.post(
    "/execution-runs/{execution_run_id}/heartbeat",
    response_model=dict,
    dependencies=[Depends(require_symphony_bridge_token)],
)
async def heartbeat_symphony_execution_run(
    execution_run_id: int,
    request: SymphonyBridgeHeartbeatRequest,
    db: AsyncSession = Depends(get_db),
):
    run = await symphony_bridge_service.heartbeat_run(
        db=db,
        execution_run_id=execution_run_id,
        worker_id=request.worker_id,
        lease_seconds=request.lease_seconds,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run heartbeat recorded",
    )


@router.post(
    "/execution-runs/{execution_run_id}/events",
    response_model=dict,
    dependencies=[Depends(require_symphony_bridge_token)],
)
async def record_symphony_execution_event(
    execution_run_id: int,
    request: SymphonyBridgeEventRequest,
    db: AsyncSession = Depends(get_db),
):
    run = await symphony_bridge_service.record_event(
        db=db,
        execution_run_id=execution_run_id,
        worker_id=request.worker_id,
        level=request.level,
        message=request.message,
        event_json=request.event_json,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run event recorded",
    )


@router.post(
    "/execution-runs/{execution_run_id}/complete",
    response_model=dict,
    dependencies=[Depends(require_symphony_bridge_token)],
)
async def complete_symphony_execution_run(
    execution_run_id: int,
    request: SymphonyBridgeCompleteRequest,
    db: AsyncSession = Depends(get_db),
):
    run = await symphony_bridge_service.complete_run(
        db=db,
        execution_run_id=execution_run_id,
        worker_id=request.worker_id,
        status=request.status,
        summary=request.summary,
        evidence=request.evidence,
        worktree_path=request.worktree_path,
        branch_name=request.branch_name,
        commit_sha=request.commit_sha,
    )
    return success_response(
        data=ExecutionRunResponse.model_validate(run).model_dump(),
        message="Execution run completed",
    )


def _queue_item(run):
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
    return data
