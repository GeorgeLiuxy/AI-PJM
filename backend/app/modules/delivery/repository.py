"""Delivery v2 data access layer."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.delivery.models import (
    CodingTask,
    DemandItem,
    ExecutionLog,
    ExecutionRun,
    GateCheck,
    ImpactAnalysis,
    RepoContext,
    SpecCard,
)


class DeliveryRepository:
    """Repository for v2 delivery entities."""

    async def create_demand(
        self,
        db: AsyncSession,
        raw_input: str,
        source_type: str,
        title: str | None = None,
        requester_ref: str | None = None,
        context_payload: dict | None = None,
    ) -> DemandItem:
        demand = DemandItem(
            raw_input=raw_input,
            source_type=source_type,
            title=title,
            requester_ref=requester_ref,
            context_payload=context_payload,
        )
        db.add(demand)
        await db.flush()
        return demand

    async def get_demand(self, db: AsyncSession, demand_id: int) -> Optional[DemandItem]:
        result = await db.execute(select(DemandItem).where(DemandItem.id == demand_id))
        return result.scalar_one_or_none()

    async def get_demand_detail(self, db: AsyncSession, demand_id: int) -> Optional[DemandItem]:
        result = await db.execute(
            select(DemandItem)
            .options(
                selectinload(DemandItem.spec_cards),
                selectinload(DemandItem.gate_checks),
                selectinload(DemandItem.repo_contexts),
                selectinload(DemandItem.impact_analyses),
                selectinload(DemandItem.coding_tasks),
            )
            .where(DemandItem.id == demand_id)
        )
        return result.scalar_one_or_none()

    async def get_spec_card(self, db: AsyncSession, spec_card_id: int) -> Optional[SpecCard]:
        result = await db.execute(select(SpecCard).where(SpecCard.id == spec_card_id))
        return result.scalar_one_or_none()

    async def get_coding_task(self, db: AsyncSession, coding_task_id: int) -> Optional[CodingTask]:
        result = await db.execute(select(CodingTask).where(CodingTask.id == coding_task_id))
        return result.scalar_one_or_none()

    async def get_coding_task_detail(self, db: AsyncSession, coding_task_id: int) -> Optional[CodingTask]:
        result = await db.execute(
            select(CodingTask)
            .options(selectinload(CodingTask.execution_runs))
            .where(CodingTask.id == coding_task_id)
        )
        return result.scalar_one_or_none()

    async def get_repo_context(self, db: AsyncSession, repo_context_id: int) -> Optional[RepoContext]:
        result = await db.execute(select(RepoContext).where(RepoContext.id == repo_context_id))
        return result.scalar_one_or_none()

    async def get_latest_repo_context(self, db: AsyncSession, demand_id: int) -> Optional[RepoContext]:
        result = await db.execute(
            select(RepoContext)
            .where(RepoContext.demand_id == demand_id)
            .order_by(RepoContext.created_at.desc(), RepoContext.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_latest_spec_card(self, db: AsyncSession, demand_id: int) -> Optional[SpecCard]:
        result = await db.execute(
            select(SpecCard)
            .where(SpecCard.demand_id == demand_id)
            .order_by(SpecCard.created_at.desc(), SpecCard.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_impact_analysis(self, db: AsyncSession, impact_analysis_id: int) -> Optional[ImpactAnalysis]:
        result = await db.execute(select(ImpactAnalysis).where(ImpactAnalysis.id == impact_analysis_id))
        return result.scalar_one_or_none()

    async def get_execution_run(self, db: AsyncSession, execution_run_id: int) -> Optional[ExecutionRun]:
        result = await db.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.logs))
            .where(ExecutionRun.id == execution_run_id)
        )
        return result.scalar_one_or_none()

    async def create_spec_card(
        self,
        db: AsyncSession,
        demand_id: int,
        status: str,
        title: str,
        user_story: str,
        scope: str,
        acceptance_criteria: list[str],
        constraints: list[str],
        risks: list[str],
        open_questions: list[str],
    ) -> SpecCard:
        spec = SpecCard(
            demand_id=demand_id,
            status=status,
            title=title,
            user_story=user_story,
            scope=scope,
            acceptance_criteria_json=acceptance_criteria,
            constraints_json=constraints,
            risks_json=risks,
            open_questions_json=open_questions,
        )
        db.add(spec)
        await db.flush()
        return spec

    async def create_gate_check(
        self,
        db: AsyncSession,
        demand_id: int,
        gate_type: str,
        status: str,
        reason: str | None = None,
        evidence_json: dict | None = None,
    ) -> GateCheck:
        gate = GateCheck(
            demand_id=demand_id,
            gate_type=gate_type,
            status=status,
            reason=reason,
            evidence_json=evidence_json,
        )
        db.add(gate)
        await db.flush()
        return gate

    async def create_repo_context(
        self,
        db: AsyncSession,
        demand_id: int,
        status: str,
        provider: str,
        summary: str,
        source_refs: list[str],
        discovered_files: list[str],
        dependency_refs: list[str],
        confidence_score: float,
        provider_metadata: dict | None = None,
    ) -> RepoContext:
        repo_context = RepoContext(
            demand_id=demand_id,
            status=status,
            provider=provider,
            summary=summary,
            source_refs_json=source_refs,
            discovered_files_json=discovered_files,
            dependency_refs_json=dependency_refs,
            confidence_score=confidence_score,
            provider_metadata_json=provider_metadata,
        )
        db.add(repo_context)
        await db.flush()
        return repo_context

    async def create_impact_analysis(
        self,
        db: AsyncSession,
        demand_id: int,
        repo_context_id: int | None,
        status: str,
        provider: str,
        summary: str,
        impacted_areas: list[str],
        affected_files: list[str],
        recommendations: list[str],
        risk_level: str,
        confidence_score: float,
        provider_metadata: dict | None = None,
    ) -> ImpactAnalysis:
        analysis = ImpactAnalysis(
            demand_id=demand_id,
            repo_context_id=repo_context_id,
            status=status,
            provider=provider,
            summary=summary,
            impacted_areas_json=impacted_areas,
            affected_files_json=affected_files,
            recommendations_json=recommendations,
            risk_level=risk_level,
            confidence_score=confidence_score,
            provider_metadata_json=provider_metadata,
        )
        db.add(analysis)
        await db.flush()
        return analysis

    async def create_coding_task(
        self,
        db: AsyncSession,
        demand_id: int,
        spec_card_id: int,
        status: str,
        title: str,
        task_prompt: str,
        allowed_paths: list[str],
        forbidden_actions: list[str],
        required_checks: list[str],
        expected_evidence: list[str],
    ) -> CodingTask:
        task = CodingTask(
            demand_id=demand_id,
            spec_card_id=spec_card_id,
            status=status,
            title=title,
            task_prompt=task_prompt,
            allowed_paths_json=allowed_paths,
            forbidden_actions_json=forbidden_actions,
            required_checks_json=required_checks,
            expected_evidence_json=expected_evidence,
        )
        db.add(task)
        await db.flush()
        return task

    async def create_execution_run(
        self,
        db: AsyncSession,
        coding_task_id: int,
        status: str,
        executor_type: str,
        trigger_mode: str,
        result_summary: str | None = None,
        evidence_json: dict | None = None,
    ) -> ExecutionRun:
        run = ExecutionRun(
            coding_task_id=coding_task_id,
            status=status,
            executor_type=executor_type,
            trigger_mode=trigger_mode,
            result_summary=result_summary,
            evidence_json=evidence_json,
        )
        db.add(run)
        await db.flush()
        return run

    async def create_execution_log(
        self,
        db: AsyncSession,
        execution_run_id: int,
        level: str,
        message: str,
        event_json: dict | None = None,
    ) -> ExecutionLog:
        log = ExecutionLog(
            execution_run_id=execution_run_id,
            level=level,
            message=message,
            event_json=event_json,
        )
        db.add(log)
        await db.flush()
        return log


delivery_repository = DeliveryRepository()
