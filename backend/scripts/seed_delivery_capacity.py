"""Seed synthetic delivery workflow data for capacity benchmarking."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.core.db import assert_database_current, async_session_maker, init_db, is_sqlite_url
from app.core.exceptions import BadRequestException
from app.modules.delivery.enums import (
    CodingTaskStatus,
    DeliveryRiskLevel,
    DemandStatus,
    DeploymentStatus,
    ExecutionRunStatus,
    MergeRequestStatus,
    ReviewStatus,
    SpecStatus,
)
from app.modules.delivery.models import (
    CodingTask,
    DemandItem,
    DeployRecord,
    ExecutionRun,
    MergeRequestRecord,
    SpecCard,
)
from app.modules.delivery.trace import generate_delivery_trace_id


def main() -> int:
    args = parse_args()
    validate_safety(confirm=args.confirm, allow_production=args.allow_production)
    summary = asyncio.run(
        run_seed(
            count=args.count,
            batch_size=args.batch_size,
            project_id=args.project_id,
            prefix=args.prefix,
            include_delivery_records=args.include_delivery_records,
        )
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True, default=str))
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed synthetic AI PJM delivery data for capacity tests.")
    parser.add_argument("--count", type=int, default=10000, help="Number of synthetic demands to create.")
    parser.add_argument("--batch-size", type=int, default=500, help="Commit interval.")
    parser.add_argument("--project-id", type=int, default=None, help="Optional existing project id.")
    parser.add_argument("--prefix", default="capacity", help="Title and branch prefix.")
    parser.add_argument(
        "--include-delivery-records",
        action="store_true",
        help="Also create local MR and deployment records for succeeded runs.",
    )
    parser.add_argument("--confirm", action="store_true", help="Required to write synthetic data.")
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Required in ENVIRONMENT=production. Use only for controlled pre-production benchmarks.",
    )
    return parser.parse_args()


def validate_safety(*, confirm: bool, allow_production: bool) -> None:
    if not confirm:
        raise BadRequestException("Capacity seed requires --confirm")
    if settings.environment.lower() == "production" and not allow_production:
        raise BadRequestException("Capacity seed refuses production without --allow-production")


async def run_seed(
    *,
    count: int,
    batch_size: int,
    project_id: int | None,
    prefix: str,
    include_delivery_records: bool,
) -> dict[str, Any]:
    await prepare_database()
    async with async_session_maker() as db:
        summary = await seed_capacity_data(
            db,
            count=count,
            batch_size=batch_size,
            project_id=project_id,
            prefix=prefix,
            include_delivery_records=include_delivery_records,
        )
        return summary


async def prepare_database() -> None:
    if is_sqlite_url(settings.database_url):
        await init_db()
        return
    await assert_database_current()


async def seed_capacity_data(
    db,
    *,
    count: int,
    batch_size: int = 500,
    project_id: int | None = None,
    prefix: str = "capacity",
    include_delivery_records: bool = False,
) -> dict[str, Any]:
    safe_count = max(count, 1)
    safe_batch_size = max(batch_size, 1)
    started_at = datetime.now(timezone.utc)
    created = {
        "demands": 0,
        "spec_cards": 0,
        "coding_tasks": 0,
        "execution_runs": 0,
        "merge_requests": 0,
        "deployments": 0,
    }

    for index in range(1, safe_count + 1):
        created_at = started_at - timedelta(seconds=safe_count - index)
        trace_id = generate_delivery_trace_id()
        status = workload_status(index)
        run_status = status["run_status"]
        task_status = status["task_status"]
        demand = DemandItem(
            trace_id=trace_id,
            project_id=project_id,
            raw_input=f"{prefix} synthetic demand #{index}: validate delivery list and queue capacity.",
            source_type="capacity_seed",
            title=f"{prefix} capacity demand #{index}",
            requester_ref="capacity-seed",
            status=DemandStatus.PLANNED,
            risk_level=DeliveryRiskLevel.L1,
            confidence_score=0.82,
            context_payload={"capacity_seed": True, "seed_index": index},
            created_at=created_at,
            updated_at=created_at,
        )
        spec = SpecCard(
            trace_id=trace_id,
            demand=demand,
            status=SpecStatus.APPROVED,
            title=f"{prefix} capacity spec #{index}",
            user_story="As an operator, I can validate delivery capacity with synthetic data.",
            scope="Synthetic capacity benchmark data only.",
            acceptance_criteria_json=[
                "Demand appears in paginated lists.",
                "Execution run appears in queue and history queries.",
            ],
            constraints_json=["Do not use synthetic data for business reporting."],
            risks_json=["Synthetic data can distort observability counts if left in a shared environment."],
            open_questions_json=[],
            created_by="capacity_seed",
            created_at=created_at,
            updated_at=created_at,
        )
        task = CodingTask(
            trace_id=trace_id,
            demand=demand,
            spec_card=spec,
            status=task_status,
            title=f"{prefix} capacity task #{index}",
            task_prompt="Synthetic task used for capacity benchmarking.",
            allowed_paths_json=["backend/app", "frontend/src/app"],
            forbidden_actions_json=["production deployment", "secret changes"],
            required_checks_json=["python -m pytest tests/test_delivery_v2.py -q"],
            expected_evidence_json=["capacity_seed"],
            created_at=created_at,
            updated_at=created_at,
        )
        run = ExecutionRun(
            trace_id=trace_id,
            coding_task=task,
            status=run_status,
            executor_type="symphony" if index % 3 == 0 else "codex",
            trigger_mode="capacity_seed",
            branch_name=f"codex/{prefix}-{index}",
            commit_sha=f"{index:040x}"[-40:] if run_status == ExecutionRunStatus.SUCCEEDED else None,
            result_summary=f"Synthetic run status: {run_status}.",
            evidence_json={"capacity_seed": True, "seed_index": index},
            started_at=created_at if run_status != ExecutionRunStatus.QUEUED else None,
            finished_at=created_at + timedelta(seconds=30) if run_status in {
                ExecutionRunStatus.SUCCEEDED,
                ExecutionRunStatus.FAILED,
                ExecutionRunStatus.BLOCKED,
            } else None,
            created_at=created_at,
            updated_at=created_at,
        )
        db.add(demand)
        created["demands"] += 1
        created["spec_cards"] += 1
        created["coding_tasks"] += 1
        created["execution_runs"] += 1

        if include_delivery_records and run_status == ExecutionRunStatus.SUCCEEDED:
            await db.flush()
            merge_request = MergeRequestRecord(
                trace_id=trace_id,
                coding_task=task,
                execution_run=run,
                provider="local",
                status=MergeRequestStatus.REVIEW_PASSED,
                review_status=ReviewStatus.PASSED,
                title=f"{prefix} capacity MR #{index}",
                source_branch=f"codex/{prefix}-{index}",
                target_branch="main",
                external_id=str(index),
                url=f"local://capacity/merge-requests/{index}",
                review_summary="Synthetic review passed.",
                review_comments_json=[],
                evidence_json={"capacity_seed": True, "seed_index": index},
                created_by_ref="capacity-seed",
                reviewed_by_ref="capacity-seed",
                reviewed_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(merge_request)
            deploy_record = DeployRecord(
                trace_id=trace_id,
                merge_request=merge_request,
                coding_task_id=task.id,
                provider="local",
                status=DeploymentStatus.DEPLOYED,
                environment="capacity",
                url=f"local://capacity/deployments/{index}",
                evidence_json={"capacity_seed": True, "seed_index": index},
                created_by_ref="capacity-seed",
                created_at=created_at,
                updated_at=created_at,
            )
            db.add(deploy_record)
            created["merge_requests"] += 1
            created["deployments"] += 1

        if index % safe_batch_size == 0:
            await db.commit()

    await db.commit()
    finished_at = datetime.now(timezone.utc)
    return {
        "state": "completed",
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": round((finished_at - started_at).total_seconds(), 3),
        "project_id": project_id,
        "prefix": prefix,
        "include_delivery_records": include_delivery_records,
        **created,
    }


def workload_status(index: int) -> dict[str, str]:
    if index % 20 == 0:
        return {
            "run_status": ExecutionRunStatus.QUEUED,
            "task_status": CodingTaskStatus.READY,
        }
    if index % 13 == 0:
        return {
            "run_status": ExecutionRunStatus.FAILED,
            "task_status": CodingTaskStatus.BLOCKED,
        }
    if index % 17 == 0:
        return {
            "run_status": ExecutionRunStatus.BLOCKED,
            "task_status": CodingTaskStatus.BLOCKED,
        }
    return {
        "run_status": ExecutionRunStatus.SUCCEEDED,
        "task_status": CodingTaskStatus.COMPLETED,
    }


if __name__ == "__main__":
    sys.exit(main())
