"""Delivery v2 data access layer."""

from typing import Optional

from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.delivery.models import (
    CodingTask,
    DeployRecord,
    DemandItem,
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
        project_id: int | None = None,
        created_by_user_id: int | None = None,
        trace_id: str | None = None,
    ) -> DemandItem:
        demand = DemandItem(
            trace_id=trace_id or generate_delivery_trace_id(),
            project_id=project_id,
            created_by_user_id=created_by_user_id,
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

    async def list_demands(
        self,
        db: AsyncSession,
        limit: int = 30,
        offset: int = 0,
        project_ids: list[int] | None = None,
    ) -> list[DemandItem]:
        query = (
            select(DemandItem)
            .order_by(DemandItem.updated_at.desc(), DemandItem.id.desc())
            .offset(offset)
            .limit(limit)
        )
        if project_ids is not None:
            if not project_ids:
                return []
            query = query.where(DemandItem.project_id.in_(project_ids))
        result = await db.execute(
            query
        )
        return list(result.scalars().all())

    async def get_demand_detail(self, db: AsyncSession, demand_id: int) -> Optional[DemandItem]:
        result = await db.execute(
            select(DemandItem)
            .options(
                selectinload(DemandItem.spec_cards),
                selectinload(DemandItem.gate_checks),
                selectinload(DemandItem.repo_contexts),
                selectinload(DemandItem.impact_analyses),
                selectinload(DemandItem.coding_tasks)
                .selectinload(CodingTask.execution_runs)
                .selectinload(ExecutionRun.logs),
                selectinload(DemandItem.coding_tasks)
                .selectinload(CodingTask.merge_requests)
                .selectinload(MergeRequestRecord.deploy_records)
                .selectinload(DeployRecord.verification_records),
            )
            .where(DemandItem.id == demand_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def has_manual_execution_approval(self, db: AsyncSession, demand_id: int) -> bool:
        result = await db.execute(
            select(GateCheck).where(
                GateCheck.demand_id == demand_id,
                GateCheck.gate_type == "execution_allowed",
                GateCheck.status == "passed",
            )
        )
        for gate in result.scalars().all():
            evidence = gate.evidence_json or {}
            if evidence.get("approval_type") == "manual" and evidence.get("approved") is True:
                return True
        return False

    async def get_spec_card(self, db: AsyncSession, spec_card_id: int) -> Optional[SpecCard]:
        result = await db.execute(select(SpecCard).where(SpecCard.id == spec_card_id))
        return result.scalar_one_or_none()

    async def get_coding_task(self, db: AsyncSession, coding_task_id: int) -> Optional[CodingTask]:
        result = await db.execute(
            select(CodingTask)
            .options(
                selectinload(CodingTask.execution_runs).selectinload(ExecutionRun.logs),
                selectinload(CodingTask.merge_requests)
                .selectinload(MergeRequestRecord.deploy_records)
                .selectinload(DeployRecord.verification_records),
            )
            .where(CodingTask.id == coding_task_id)
        )
        return result.scalar_one_or_none()

    async def get_coding_task_detail(self, db: AsyncSession, coding_task_id: int) -> Optional[CodingTask]:
        result = await db.execute(
            select(CodingTask)
            .options(
                selectinload(CodingTask.execution_runs),
                selectinload(CodingTask.merge_requests)
                .selectinload(MergeRequestRecord.deploy_records)
                .selectinload(DeployRecord.verification_records),
            )
            .where(CodingTask.id == coding_task_id)
        )
        return result.scalar_one_or_none()

    async def get_merge_request_record(
        self,
        db: AsyncSession,
        merge_request_id: int,
    ) -> Optional[MergeRequestRecord]:
        result = await db.execute(
            select(MergeRequestRecord)
            .options(
                selectinload(MergeRequestRecord.deploy_records).selectinload(DeployRecord.verification_records),
            )
            .where(MergeRequestRecord.id == merge_request_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_deploy_record(
        self,
        db: AsyncSession,
        deploy_record_id: int,
    ) -> Optional[DeployRecord]:
        result = await db.execute(
            select(DeployRecord)
            .options(selectinload(DeployRecord.verification_records))
            .where(DeployRecord.id == deploy_record_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_latest_merge_request_for_task(
        self,
        db: AsyncSession,
        coding_task_id: int,
    ) -> Optional[MergeRequestRecord]:
        result = await db.execute(
            select(MergeRequestRecord)
            .where(MergeRequestRecord.coding_task_id == coding_task_id)
            .order_by(MergeRequestRecord.created_at.desc(), MergeRequestRecord.id.desc())
            .limit(1)
            .execution_options(populate_existing=True)
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

    async def get_latest_impact_analysis(self, db: AsyncSession, demand_id: int) -> Optional[ImpactAnalysis]:
        result = await db.execute(
            select(ImpactAnalysis)
            .where(ImpactAnalysis.demand_id == demand_id)
            .order_by(ImpactAnalysis.created_at.desc(), ImpactAnalysis.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def get_execution_run(self, db: AsyncSession, execution_run_id: int) -> Optional[ExecutionRun]:
        result = await db.execute(
            select(ExecutionRun)
            .options(selectinload(ExecutionRun.logs))
            .where(ExecutionRun.id == execution_run_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_execution_run_for_dispatch(
        self,
        db: AsyncSession,
        execution_run_id: int,
    ) -> Optional[ExecutionRun]:
        result = await db.execute(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.logs),
                selectinload(ExecutionRun.coding_task),
            )
            .where(ExecutionRun.id == execution_run_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def get_execution_run_with_task(
        self,
        db: AsyncSession,
        execution_run_id: int,
    ) -> Optional[ExecutionRun]:
        result = await db.execute(
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.logs),
                selectinload(ExecutionRun.coding_task).selectinload(CodingTask.demand),
            )
            .where(ExecutionRun.id == execution_run_id)
            .execution_options(populate_existing=True)
        )
        return result.scalar_one_or_none()

    async def list_execution_runs(
        self,
        db: AsyncSession,
        statuses: list[str] | None = None,
        executor_types: list[str] | None = None,
        limit: int = 30,
        offset: int = 0,
        project_ids: list[int] | None = None,
    ) -> list[ExecutionRun]:
        query = (
            select(ExecutionRun)
            .options(
                selectinload(ExecutionRun.logs),
                selectinload(ExecutionRun.coding_task).selectinload(CodingTask.demand),
            )
            .order_by(ExecutionRun.updated_at.desc(), ExecutionRun.id.desc())
            .offset(offset)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        if statuses:
            query = query.where(ExecutionRun.status.in_(statuses))
        if executor_types:
            query = query.where(ExecutionRun.executor_type.in_(executor_types))
        if project_ids is not None:
            if not project_ids:
                return []
            query = (
                query.join(CodingTask, CodingTask.id == ExecutionRun.coding_task_id)
                .join(DemandItem, DemandItem.id == CodingTask.demand_id)
                .where(DemandItem.project_id.in_(project_ids))
            )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def count_execution_runs(
        self,
        db: AsyncSession,
        statuses: list[str] | None = None,
        executor_types: list[str] | None = None,
        project_ids: list[int] | None = None,
    ) -> int:
        query = select(func.count(ExecutionRun.id))
        if statuses:
            query = query.where(ExecutionRun.status.in_(statuses))
        if executor_types:
            query = query.where(ExecutionRun.executor_type.in_(executor_types))
        if project_ids is not None:
            if not project_ids:
                return 0
            query = (
                query.join(CodingTask, CodingTask.id == ExecutionRun.coding_task_id)
                .join(DemandItem, DemandItem.id == CodingTask.demand_id)
                .where(DemandItem.project_id.in_(project_ids))
            )
        result = await db.execute(query)
        return int(result.scalar_one() or 0)

    async def count_running_execution_runs(
        self,
        db: AsyncSession,
        exclude_run_id: int | None = None,
    ) -> int:
        query = select(func.count(ExecutionRun.id)).where(ExecutionRun.status == "running")
        if exclude_run_id is not None:
            query = query.where(ExecutionRun.id != exclude_run_id)
        result = await db.execute(query)
        return int(result.scalar_one() or 0)

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
        provider_metadata: dict | None = None,
    ) -> SpecCard:
        trace_id = await self._trace_id_for_demand(db, demand_id)
        spec = SpecCard(
            trace_id=trace_id,
            demand_id=demand_id,
            status=status,
            title=title,
            user_story=user_story,
            scope=scope,
            acceptance_criteria_json=acceptance_criteria,
            constraints_json=constraints,
            risks_json=risks,
            open_questions_json=open_questions,
            provider_metadata_json=provider_metadata,
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
        trace_id = await self._trace_id_for_demand(db, demand_id)
        gate = GateCheck(
            trace_id=trace_id,
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
        trace_id = await self._trace_id_for_demand(db, demand_id)
        repo_context = RepoContext(
            trace_id=trace_id,
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
        trace_id = await self._trace_id_for_demand(db, demand_id)
        analysis = ImpactAnalysis(
            trace_id=trace_id,
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
        trace_id = await self._trace_id_for_demand(db, demand_id)
        task = CodingTask(
            trace_id=trace_id,
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
        trace_id = await self._trace_id_for_coding_task(db, coding_task_id)
        run = ExecutionRun(
            trace_id=trace_id,
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
        trace_id = await self._trace_id_for_execution_run(db, execution_run_id)
        log = ExecutionLog(
            trace_id=trace_id,
            execution_run_id=execution_run_id,
            level=level,
            message=message,
            event_json=event_json,
        )
        db.add(log)
        await db.flush()
        return log

    async def claim_execution_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
        started_at: datetime,
        result_summary: str,
        evidence_json: dict,
    ) -> bool:
        result = await db.execute(
            update(ExecutionRun)
            .where(
                ExecutionRun.id == execution_run_id,
                ExecutionRun.status == "queued",
            )
            .values(
                status="running",
                started_at=started_at,
                result_summary=result_summary,
                evidence_json=evidence_json,
                updated_at=started_at,
            )
        )
        await db.flush()
        return result.rowcount == 1

    async def create_merge_request_record(
        self,
        db: AsyncSession,
        coding_task_id: int,
        execution_run_id: int,
        provider: str,
        status: str,
        review_status: str,
        title: str,
        source_branch: str,
        target_branch: str,
        external_id: str | None = None,
        url: str | None = None,
        review_summary: str | None = None,
        review_comments: list[dict] | None = None,
        evidence_json: dict | None = None,
        created_by_user_id: int | None = None,
        created_by_ref: str | None = None,
    ) -> MergeRequestRecord:
        trace_id = await self._trace_id_for_coding_task(db, coding_task_id)
        record = MergeRequestRecord(
            trace_id=trace_id,
            coding_task_id=coding_task_id,
            execution_run_id=execution_run_id,
            provider=provider,
            status=status,
            review_status=review_status,
            title=title,
            source_branch=source_branch,
            target_branch=target_branch,
            external_id=external_id,
            url=url,
            review_summary=review_summary,
            review_comments_json=review_comments or [],
            evidence_json=evidence_json,
            created_by_user_id=created_by_user_id,
            created_by_ref=created_by_ref,
        )
        db.add(record)
        await db.flush()
        return record

    async def create_deploy_record(
        self,
        db: AsyncSession,
        merge_request_id: int,
        coding_task_id: int,
        provider: str,
        status: str,
        environment: str,
        url: str | None = None,
        evidence_json: dict | None = None,
        created_by_user_id: int | None = None,
        created_by_ref: str | None = None,
    ) -> DeployRecord:
        trace_id = await self._trace_id_for_coding_task(db, coding_task_id)
        record = DeployRecord(
            trace_id=trace_id,
            merge_request_id=merge_request_id,
            coding_task_id=coding_task_id,
            provider=provider,
            status=status,
            environment=environment,
            url=url,
            evidence_json=evidence_json,
            created_by_user_id=created_by_user_id,
            created_by_ref=created_by_ref,
        )
        db.add(record)
        await db.flush()
        return record

    async def create_verification_record(
        self,
        db: AsyncSession,
        deploy_record_id: int,
        status: str,
        verifier_user_id: int | None = None,
        verifier_ref: str | None = None,
        summary: str | None = None,
        evidence_links: list[str] | None = None,
        evidence_json: dict | None = None,
    ) -> VerificationRecord:
        trace_id = await self._trace_id_for_deploy_record(db, deploy_record_id)
        record = VerificationRecord(
            trace_id=trace_id,
            deploy_record_id=deploy_record_id,
            status=status,
            verifier_user_id=verifier_user_id,
            verifier_ref=verifier_ref,
            summary=summary,
            evidence_links_json=evidence_links or [],
            evidence_json=evidence_json,
        )
        db.add(record)
        await db.flush()
        return record

    async def update_execution_run(
        self,
        db: AsyncSession,
        run: ExecutionRun,
        **values,
    ) -> ExecutionRun:
        for key, value in values.items():
            setattr(run, key, value)
        await db.flush()
        return run

    async def update_coding_task_status(
        self,
        db: AsyncSession,
        task: CodingTask,
        status: str,
    ) -> CodingTask:
        task.status = status
        await db.flush()
        return task

    async def update_merge_request_record(
        self,
        db: AsyncSession,
        record: MergeRequestRecord,
        **values,
    ) -> MergeRequestRecord:
        for key, value in values.items():
            setattr(record, key, value)
        await db.flush()
        return record

    async def list_deploy_records(
        self,
        db: AsyncSession,
        statuses: list[str] | None = None,
        limit: int = 30,
        offset: int = 0,
        project_ids: list[int] | None = None,
    ) -> list[DeployRecord]:
        query = (
            select(DeployRecord)
            .options(selectinload(DeployRecord.verification_records))
            .order_by(DeployRecord.updated_at.desc(), DeployRecord.id.desc())
            .offset(offset)
            .limit(limit)
        )
        if statuses:
            query = query.where(DeployRecord.status.in_(statuses))
        if project_ids is not None:
            if not project_ids:
                return []
            query = (
                query.join(CodingTask, CodingTask.id == DeployRecord.coding_task_id)
                .join(DemandItem, DemandItem.id == CodingTask.demand_id)
                .where(DemandItem.project_id.in_(project_ids))
            )
        result = await db.execute(query)
        return list(result.scalars().all())

    async def count_deploy_records(
        self,
        db: AsyncSession,
        statuses: list[str] | None = None,
        project_ids: list[int] | None = None,
    ) -> int:
        query = select(func.count(DeployRecord.id))
        if statuses:
            query = query.where(DeployRecord.status.in_(statuses))
        if project_ids is not None:
            if not project_ids:
                return 0
            query = (
                query.join(CodingTask, CodingTask.id == DeployRecord.coding_task_id)
                .join(DemandItem, DemandItem.id == CodingTask.demand_id)
                .where(DemandItem.project_id.in_(project_ids))
            )
        result = await db.execute(query)
        return int(result.scalar_one() or 0)

    async def update_deploy_record(
        self,
        db: AsyncSession,
        record: DeployRecord,
        **values,
    ) -> DeployRecord:
        for key, value in values.items():
            setattr(record, key, value)
        await db.flush()
        return record

    async def update_spec_status(
        self,
        db: AsyncSession,
        spec: SpecCard,
        status: str,
    ) -> SpecCard:
        spec.status = status
        await db.flush()
        return spec

    async def _trace_id_for_demand(self, db: AsyncSession, demand_id: int) -> str | None:
        result = await db.execute(select(DemandItem.trace_id).where(DemandItem.id == demand_id))
        return result.scalar_one_or_none()

    async def _trace_id_for_coding_task(self, db: AsyncSession, coding_task_id: int) -> str | None:
        result = await db.execute(select(CodingTask.trace_id).where(CodingTask.id == coding_task_id))
        return result.scalar_one_or_none()

    async def _trace_id_for_execution_run(self, db: AsyncSession, execution_run_id: int) -> str | None:
        result = await db.execute(select(ExecutionRun.trace_id).where(ExecutionRun.id == execution_run_id))
        return result.scalar_one_or_none()

    async def _trace_id_for_deploy_record(self, db: AsyncSession, deploy_record_id: int) -> str | None:
        result = await db.execute(select(DeployRecord.trace_id).where(DeployRecord.id == deploy_record_id))
        return result.scalar_one_or_none()


delivery_repository = DeliveryRepository()
