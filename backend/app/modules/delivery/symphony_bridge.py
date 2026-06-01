"""Internal Symphony bridge service.

The bridge lets an external execution daemon consume AI PJM execution runs
without taking ownership of delivery gates or final business state.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utc_now
from app.core.exceptions import BadRequestException, ConflictException, ForbiddenException, NotFoundException
from app.modules.delivery.enums import (
    CodingTaskStatus,
    ExecutionLogLevel,
    ExecutionRunStatus,
    GateStatus,
    GateType,
)
from app.modules.delivery.models import DemandItem, ExecutionRun
from app.modules.delivery.redaction import redact_text, redact_value
from app.modules.delivery.repository import delivery_repository


SYMPHONY_EXECUTOR_TYPE = "symphony"
SYMPHONY_EVIDENCE_KEY = "symphony_bridge"


class SymphonyBridgeService:
    """Business operations for worker claim, lease, event and completion."""

    async def list_claimable_runs(
        self,
        db: AsyncSession,
        limit: int = 10,
    ) -> list[ExecutionRun]:
        return await delivery_repository.list_execution_runs(
            db=db,
            statuses=[ExecutionRunStatus.QUEUED],
            executor_types=[SYMPHONY_EXECUTOR_TYPE],
            limit=min(max(limit, 1), 50),
        )

    async def get_task_package(self, db: AsyncSession, execution_run_id: int) -> dict[str, Any]:
        run = await delivery_repository.get_execution_run_for_dispatch(db, execution_run_id)
        if not run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        if run.executor_type != SYMPHONY_EXECUTOR_TYPE:
            raise BadRequestException("Execution run is not configured for Symphony")

        task = run.coding_task
        if not task:
            raise NotFoundException(f"Coding task for execution run {execution_run_id} not found")
        demand = await self._get_demand(db, task.demand_id)
        spec = await delivery_repository.get_latest_spec_card(db, demand.id)
        repo_context = await delivery_repository.get_latest_repo_context(db, demand.id)
        impact = await delivery_repository.get_latest_impact_analysis(db, demand.id)

        return redact_value(
            {
                "run_id": run.id,
                "coding_task_id": task.id,
                "demand_id": demand.id,
                "demand_title": demand.title,
                "risk_level": demand.risk_level,
                "task_title": task.title,
                "task_prompt": task.task_prompt,
                "allowed_paths": task.allowed_paths_json or [],
                "forbidden_actions": task.forbidden_actions_json or [],
                "required_checks": task.required_checks_json or [],
                "expected_evidence": task.expected_evidence_json or [],
                "acceptance_criteria": spec.acceptance_criteria_json if spec else [],
                "repo_context_summary": repo_context.summary if repo_context else None,
                "impact_summary": impact.summary if impact else None,
                "execution_evidence": run.evidence_json or {},
            }
        )

    async def claim_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
        worker_id: str,
        lease_seconds: int | None = None,
    ) -> ExecutionRun:
        run = await delivery_repository.get_execution_run_for_dispatch(db, execution_run_id)
        if not run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        self._ensure_symphony_run(run)

        if run.status != ExecutionRunStatus.QUEUED:
            raise ConflictException(f"Execution run {execution_run_id} is not queued")

        running_count = await delivery_repository.count_running_execution_runs(db, exclude_run_id=run.id)
        if running_count >= settings.execution_max_concurrency:
            raise ConflictException("Execution concurrency limit reached; run remains queued")

        task = run.coding_task
        if not task:
            raise NotFoundException(f"Coding task for execution run {execution_run_id} not found")

        now = utc_now()
        bridge_evidence = self._bridge_evidence(
            run,
            worker_id=worker_id,
            status="claimed",
            claimed_at=now,
            lease_seconds=lease_seconds,
        )
        claimed = await delivery_repository.claim_execution_run(
            db=db,
            execution_run_id=run.id,
            started_at=run.started_at or now,
            result_summary="Symphony worker claimed execution run.",
            evidence_json=bridge_evidence,
        )
        if not claimed:
            await db.rollback()
            raise ConflictException(f"Execution run {execution_run_id} is not queued")
        await delivery_repository.update_coding_task_status(db, task, CodingTaskStatus.RUNNING)
        await delivery_repository.create_execution_log(
            db=db,
            execution_run_id=run.id,
            level=ExecutionLogLevel.INFO,
            message="Symphony worker claimed execution run.",
            event_json=redact_value(
                {
                    "worker_id": worker_id,
                    "lease_expires_at": bridge_evidence[SYMPHONY_EVIDENCE_KEY]["lease_expires_at"],
                }
            ),
        )
        await db.commit()
        return await self._reload_run(db, run.id)

    async def heartbeat_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
        worker_id: str,
        lease_seconds: int | None = None,
    ) -> ExecutionRun:
        run = await self._get_owned_running_run(db, execution_run_id, worker_id)
        now = utc_now()
        bridge_evidence = self._bridge_evidence(
            run,
            worker_id=worker_id,
            status="running",
            heartbeat_at=now,
            lease_seconds=lease_seconds,
        )
        await delivery_repository.update_execution_run(
            db,
            run,
            result_summary="Symphony worker heartbeat received.",
            evidence_json=bridge_evidence,
        )
        await db.commit()
        return await self._reload_run(db, run.id)

    async def record_event(
        self,
        db: AsyncSession,
        execution_run_id: int,
        worker_id: str,
        level: str,
        message: str,
        event_json: dict[str, Any] | None = None,
    ) -> ExecutionRun:
        run = await self._get_owned_running_run(db, execution_run_id, worker_id)
        await delivery_repository.create_execution_log(
            db=db,
            execution_run_id=run.id,
            level=level,
            message=redact_text(message),
            event_json=redact_value({"worker_id": worker_id, **(event_json or {})}),
        )
        await db.commit()
        return await self._reload_run(db, run.id)

    async def complete_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
        worker_id: str,
        status: str,
        summary: str,
        evidence: dict[str, Any] | None = None,
        worktree_path: str | None = None,
        branch_name: str | None = None,
        commit_sha: str | None = None,
    ) -> ExecutionRun:
        run = await self._get_owned_running_run(db, execution_run_id, worker_id)
        task = run.coding_task
        if not task:
            raise NotFoundException(f"Coding task for execution run {execution_run_id} not found")
        demand = await self._get_demand(db, task.demand_id)

        if status not in {ExecutionRunStatus.SUCCEEDED, ExecutionRunStatus.FAILED}:
            raise BadRequestException("Symphony completion status must be succeeded or failed")

        final_status = ExecutionRunStatus.SUCCEEDED if status == ExecutionRunStatus.SUCCEEDED else ExecutionRunStatus.FAILED
        task_status = CodingTaskStatus.COMPLETED if final_status == ExecutionRunStatus.SUCCEEDED else CodingTaskStatus.BLOCKED
        existing_evidence = run.evidence_json or {}
        bridge_metadata = existing_evidence.get(SYMPHONY_EVIDENCE_KEY) or {}
        safe_summary = redact_text(summary)
        safe_evidence = redact_value(evidence or {})
        finished_at = utc_now()

        await delivery_repository.update_execution_run(
            db,
            run,
            status=final_status,
            finished_at=finished_at,
            worktree_path=worktree_path,
            branch_name=branch_name,
            commit_sha=commit_sha,
            result_summary=safe_summary,
            evidence_json={
                "execution_allowed": redact_value(self._execution_allowed_evidence(existing_evidence)),
                "dispatch": {
                    "executor_type": SYMPHONY_EXECUTOR_TYPE,
                    "worker_id": redact_text(worker_id),
                    "status": final_status,
                    "summary": safe_summary,
                    **safe_evidence,
                },
                SYMPHONY_EVIDENCE_KEY: {
                    **redact_value(bridge_metadata),
                    "status": "completed",
                    "completed_at": finished_at.isoformat(),
                },
            },
        )
        await delivery_repository.update_coding_task_status(db, task, task_status)
        await delivery_repository.create_execution_log(
            db=db,
            execution_run_id=run.id,
            level=ExecutionLogLevel.INFO if final_status == ExecutionRunStatus.SUCCEEDED else ExecutionLogLevel.ERROR,
            message=safe_summary,
            event_json={
                "worker_id": redact_text(worker_id),
                "status": final_status,
                "evidence": safe_evidence,
            },
        )
        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.SELF_TEST_PASSED,
            status=GateStatus.PASSED if final_status == ExecutionRunStatus.SUCCEEDED else GateStatus.FAILED,
            reason=safe_summary,
            evidence_json=safe_evidence,
        )
        await db.commit()
        return await self._reload_run(db, run.id)

    async def _get_owned_running_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
        worker_id: str,
    ) -> ExecutionRun:
        run = await delivery_repository.get_execution_run_for_dispatch(db, execution_run_id)
        if not run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        self._ensure_symphony_run(run)
        if run.status != ExecutionRunStatus.RUNNING:
            raise ConflictException(f"Execution run {execution_run_id} is not running")

        bridge_metadata = (run.evidence_json or {}).get(SYMPHONY_EVIDENCE_KEY) or {}
        owner = bridge_metadata.get("worker_id")
        if owner != worker_id:
            raise ForbiddenException("Symphony worker does not own this execution run")
        return run

    async def _get_demand(self, db: AsyncSession, demand_id: int) -> DemandItem:
        demand = await delivery_repository.get_demand(db, demand_id)
        if not demand:
            raise NotFoundException(f"Demand {demand_id} not found")
        return demand

    async def _reload_run(self, db: AsyncSession, execution_run_id: int) -> ExecutionRun:
        loaded_run = await delivery_repository.get_execution_run(db, execution_run_id)
        if not loaded_run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        return loaded_run

    def _ensure_symphony_run(self, run: ExecutionRun) -> None:
        if run.executor_type != SYMPHONY_EXECUTOR_TYPE:
            raise BadRequestException("Execution run is not configured for Symphony")

    def _bridge_evidence(
        self,
        run: ExecutionRun,
        *,
        worker_id: str,
        status: str,
        lease_seconds: int | None,
        claimed_at: datetime | None = None,
        heartbeat_at: datetime | None = None,
    ) -> dict[str, Any]:
        now = heartbeat_at or claimed_at or utc_now()
        lease = lease_seconds or settings.symphony_bridge_default_lease_seconds
        current = dict(run.evidence_json or {})
        current_bridge = dict(current.get(SYMPHONY_EVIDENCE_KEY) or {})
        current_bridge.update(
            {
                "worker_id": worker_id,
                "status": status,
                "lease_seconds": lease,
                "lease_expires_at": (now + timedelta(seconds=lease)).isoformat(),
            }
        )
        if claimed_at is not None:
            current_bridge["claimed_at"] = claimed_at.isoformat()
        if heartbeat_at is not None:
            current_bridge["heartbeat_at"] = heartbeat_at.isoformat()
        current[SYMPHONY_EVIDENCE_KEY] = current_bridge
        return redact_value(current)

    def _execution_allowed_evidence(self, evidence: dict[str, Any]) -> dict[str, Any]:
        if "execution_allowed" in evidence and isinstance(evidence["execution_allowed"], dict):
            return evidence["execution_allowed"]
        return {key: value for key, value in evidence.items() if key != SYMPHONY_EVIDENCE_KEY}


symphony_bridge_service = SymphonyBridgeService()
