"""Backfill delivery trace ids for records created before trace support."""

from __future__ import annotations

from dataclasses import dataclass, field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.delivery.models import (
    CodingTask,
    DemandItem,
    DeployRecord,
    ExecutionLog,
    ExecutionRun,
    GateCheck,
    ImpactAnalysis,
    MergeRequestRecord,
    RepoContext,
    SpecCard,
    VerificationRecord,
)
from app.modules.delivery.trace import generate_delivery_trace_id


@dataclass
class TraceBackfillResult:
    """Summary for a trace id backfill pass."""

    dry_run: bool
    updated: dict[str, int] = field(default_factory=dict)

    @property
    def total_updated(self) -> int:
        return sum(self.updated.values())


async def backfill_delivery_trace_ids(db: AsyncSession, *, dry_run: bool = False) -> TraceBackfillResult:
    """Populate missing trace ids across the delivery workflow graph."""

    result = TraceBackfillResult(dry_run=dry_run)
    demand_trace_ids = await _ensure_demand_trace_map(db, result, dry_run=dry_run)
    await _copy_from_map(db, result, SpecCard, "demand_id", demand_trace_ids, dry_run=dry_run)
    await _copy_from_map(db, result, GateCheck, "demand_id", demand_trace_ids, dry_run=dry_run)
    await _copy_from_map(db, result, RepoContext, "demand_id", demand_trace_ids, dry_run=dry_run)
    await _copy_from_map(db, result, ImpactAnalysis, "demand_id", demand_trace_ids, dry_run=dry_run)
    task_trace_ids = await _copy_from_map(db, result, CodingTask, "demand_id", demand_trace_ids, dry_run=dry_run)

    run_trace_ids = await _copy_from_map(db, result, ExecutionRun, "coding_task_id", task_trace_ids, dry_run=dry_run)
    await _copy_from_map(db, result, MergeRequestRecord, "coding_task_id", task_trace_ids, dry_run=dry_run)
    deploy_trace_ids = await _copy_from_map(db, result, DeployRecord, "coding_task_id", task_trace_ids, dry_run=dry_run)

    await _copy_from_map(db, result, ExecutionLog, "execution_run_id", run_trace_ids, dry_run=dry_run)
    await _copy_from_map(db, result, VerificationRecord, "deploy_record_id", deploy_trace_ids, dry_run=dry_run)
    return result


async def _ensure_demand_trace_map(
    db: AsyncSession,
    result: TraceBackfillResult,
    *,
    dry_run: bool,
) -> dict[int, str]:
    demand_result = await db.execute(select(DemandItem))
    demands = list(demand_result.scalars().all())
    updated = 0
    trace_ids: dict[int, str] = {}
    for demand in demands:
        trace_id = demand.trace_id
        if not trace_id:
            updated += 1
            trace_id = generate_delivery_trace_id()
            if not dry_run:
                demand.trace_id = trace_id
        trace_ids[demand.id] = trace_id
    result.updated[DemandItem.__tablename__] = updated
    if not dry_run:
        await db.flush()
    return trace_ids


async def _copy_from_map(
    db: AsyncSession,
    result: TraceBackfillResult,
    model,
    source_id_attr: str,
    source_trace_ids: dict[int, str],
    *,
    dry_run: bool,
) -> dict[int, str]:
    rows_result = await db.execute(select(model))
    rows = list(rows_result.scalars().all())
    updates = 0
    effective_trace_ids: dict[int, str] = {}
    for row in rows:
        trace_id = row.trace_id
        if trace_id:
            effective_trace_ids[row.id] = trace_id
            continue
        source_id = getattr(row, source_id_attr)
        trace_id = source_trace_ids.get(source_id)
        if not trace_id:
            continue
        updates += 1
        if not dry_run:
            row.trace_id = trace_id
        effective_trace_ids[row.id] = trace_id
    result.updated[model.__tablename__] = updates
    if not dry_run:
        await db.flush()
    return effective_trace_ids


def _missing_trace_id(model):
    return or_(model.trace_id.is_(None), model.trace_id == "")
