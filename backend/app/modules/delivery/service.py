"""Delivery v2 business logic."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utc_now
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.delivery.enums import (
    CodingTaskStatus,
    DeliveryRiskLevel,
    DemandStatus,
    ExecutionLogLevel,
    ExecutionRunStatus,
    GateStatus,
    GateType,
    ImpactAnalysisStatus,
    RepoContextStatus,
    SpecStatus,
)
from app.modules.delivery.executors import get_execution_executor
from app.modules.delivery.gates import DeliveryGateEngine, gate_engine
from app.modules.delivery.models import (
    CodingTask,
    DemandItem,
    ExecutionRun,
    ImpactAnalysis,
    RepoContext,
    SpecCard,
)
from app.modules.delivery.providers import WorkflowProvider, get_workflow_provider
from app.modules.delivery.repository import delivery_repository


class DeliveryService:
    """Service for v2 delivery workflow orchestration."""

    def __init__(
        self,
        provider: WorkflowProvider | None = None,
        gates: DeliveryGateEngine = gate_engine,
    ) -> None:
        self._provider = provider
        self.gates = gates

    @property
    def provider(self) -> WorkflowProvider:
        if self._provider is None:
            self._provider = get_workflow_provider()
        return self._provider

    async def create_demand(
        self,
        db: AsyncSession,
        raw_input: str,
        source_type: str,
        title: str | None = None,
        requester_ref: str | None = None,
        context_payload: dict | None = None,
    ) -> DemandItem:
        demand = await delivery_repository.create_demand(
            db=db,
            raw_input=raw_input,
            source_type=source_type,
            title=title or self._derive_title(raw_input),
            requester_ref=requester_ref,
            context_payload=context_payload,
        )
        await db.commit()
        return demand

    async def get_demand_detail(self, db: AsyncSession, demand_id: int) -> DemandItem:
        demand = await delivery_repository.get_demand_detail(db, demand_id)
        if not demand:
            raise NotFoundException(f"Demand {demand_id} not found")
        return demand

    async def get_spec_card(self, db: AsyncSession, spec_card_id: int) -> SpecCard:
        spec = await delivery_repository.get_spec_card(db, spec_card_id)
        if not spec:
            raise NotFoundException(f"Spec card {spec_card_id} not found")
        return spec

    async def get_repo_context(self, db: AsyncSession, repo_context_id: int) -> RepoContext:
        repo_context = await delivery_repository.get_repo_context(db, repo_context_id)
        if not repo_context:
            raise NotFoundException(f"Repo context {repo_context_id} not found")
        return repo_context

    async def get_impact_analysis(self, db: AsyncSession, impact_analysis_id: int) -> ImpactAnalysis:
        analysis = await delivery_repository.get_impact_analysis(db, impact_analysis_id)
        if not analysis:
            raise NotFoundException(f"Impact analysis {impact_analysis_id} not found")
        return analysis

    async def get_coding_task(self, db: AsyncSession, coding_task_id: int) -> CodingTask:
        task = await delivery_repository.get_coding_task(db, coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {coding_task_id} not found")
        return task

    async def get_execution_run(self, db: AsyncSession, execution_run_id: int) -> ExecutionRun:
        run = await delivery_repository.get_execution_run(db, execution_run_id)
        if not run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        return run

    async def generate_spec(
        self,
        db: AsyncSession,
        demand_id: int,
        auto_approve_low_risk: bool = True,
    ) -> SpecCard:
        demand = await delivery_repository.get_demand(db, demand_id)
        if not demand:
            raise NotFoundException(f"Demand {demand_id} not found")

        risk_level = self.gates.classify_risk(demand.raw_input)
        confidence_score = self.gates.estimate_confidence(demand.raw_input)
        spec_status = self.gates.decide_spec_status(
            risk_level=risk_level,
            confidence_score=confidence_score,
            auto_approve_low_risk=auto_approve_low_risk,
        )
        draft = await self.provider.generate_spec(demand)

        spec = await delivery_repository.create_spec_card(
            db=db,
            demand_id=demand.id,
            status=spec_status,
            title=draft.title,
            user_story=draft.user_story,
            scope=draft.scope,
            acceptance_criteria=draft.acceptance_criteria,
            constraints=draft.constraints,
            risks=self._merge_risks(draft.risks, risk_level),
            open_questions=self._merge_open_questions(
                draft.open_questions,
                risk_level,
                confidence_score,
            ),
        )

        demand.risk_level = risk_level
        demand.confidence_score = confidence_score
        demand.status = (
            DemandStatus.SPEC_APPROVED
            if spec_status == SpecStatus.APPROVED
            else DemandStatus.SPEC_MANUAL_REQUIRED
        )

        await self._record_gate(
            db,
            demand.id,
            self.gates.evaluate_spec_ready(
                spec_card_id=spec.id,
                user_story=spec.user_story,
                scope=spec.scope,
                acceptance_criteria=spec.acceptance_criteria_json,
                constraints=spec.constraints_json,
                risks=spec.risks_json,
            ),
        )
        await self._record_gate(
            db,
            demand.id,
            self.gates.evaluate_risk_classified(
                risk_level=risk_level,
                confidence_score=confidence_score,
                auto_approve_low_risk=auto_approve_low_risk,
            ),
        )

        await db.commit()
        return spec

    async def collect_repo_context(
        self,
        db: AsyncSession,
        demand_id: int,
        force_refresh: bool = False,
    ) -> RepoContext:
        demand = await delivery_repository.get_demand(db, demand_id)
        if not demand:
            raise NotFoundException(f"Demand {demand_id} not found")

        if not force_refresh:
            existing = await delivery_repository.get_latest_repo_context(db, demand_id)
            if existing:
                return existing

        draft = await self.provider.collect_repo_context(demand)
        gate = self.gates.evaluate_repo_context(
            repo_context_id=0,
            confidence_score=draft.confidence_score,
            source_refs=draft.source_refs,
        )
        status = (
            RepoContextStatus.READY
            if gate.status == GateStatus.PASSED
            else RepoContextStatus.INSUFFICIENT
        )
        repo_context = await delivery_repository.create_repo_context(
            db=db,
            demand_id=demand.id,
            status=status,
            provider=self.provider.name,
            summary=draft.summary,
            source_refs=draft.source_refs,
            discovered_files=draft.discovered_files,
            dependency_refs=draft.dependency_refs,
            confidence_score=draft.confidence_score,
            provider_metadata=draft.provider_metadata,
        )

        gate = self.gates.evaluate_repo_context(
            repo_context_id=repo_context.id,
            confidence_score=repo_context.confidence_score,
            source_refs=repo_context.source_refs_json,
        )
        await self._record_gate(db, demand.id, gate)
        if gate.status == GateStatus.PASSED and demand.status == DemandStatus.INTAKE:
            demand.status = DemandStatus.CONTEXT_READY

        await db.commit()
        return repo_context

    async def analyze_impact(
        self,
        db: AsyncSession,
        demand_id: int,
        repo_context_id: int | None = None,
    ) -> ImpactAnalysis:
        demand = await delivery_repository.get_demand(db, demand_id)
        if not demand:
            raise NotFoundException(f"Demand {demand_id} not found")

        spec = await delivery_repository.get_latest_spec_card(db, demand_id)
        repo_context = await self._resolve_repo_context(db, demand_id, repo_context_id)
        draft = await self.provider.analyze_impact(demand, spec, repo_context)
        status = (
            ImpactAnalysisStatus.MANUAL_REVIEW
            if draft.risk_level in {DeliveryRiskLevel.L2, DeliveryRiskLevel.L3}
            or draft.confidence_score < 0.7
            else ImpactAnalysisStatus.READY
        )
        analysis = await delivery_repository.create_impact_analysis(
            db=db,
            demand_id=demand.id,
            repo_context_id=repo_context.id if repo_context else None,
            status=status,
            provider=self.provider.name,
            summary=draft.summary,
            impacted_areas=draft.impacted_areas,
            affected_files=draft.affected_files,
            recommendations=draft.recommendations,
            risk_level=draft.risk_level,
            confidence_score=draft.confidence_score,
            provider_metadata=draft.provider_metadata,
        )

        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.IMPACT_ANALYZED,
            status=GateStatus.PASSED if status == ImpactAnalysisStatus.READY else GateStatus.MANUAL_REQUIRED,
            reason="Impact analysis completed.",
            evidence_json={
                "impact_analysis_id": analysis.id,
                "risk_level": analysis.risk_level,
                "confidence_score": analysis.confidence_score,
            },
        )

        await db.commit()
        return analysis

    async def create_coding_task(
        self,
        db: AsyncSession,
        spec_card_id: int,
        allowed_paths: list[str] | None = None,
        required_checks: list[str] | None = None,
    ) -> CodingTask:
        spec = await delivery_repository.get_spec_card(db, spec_card_id)
        if not spec:
            raise NotFoundException(f"Spec card {spec_card_id} not found")
        if spec.status not in {SpecStatus.APPROVED, SpecStatus.MANUAL_REVIEW}:
            raise BadRequestException(f"Spec card {spec_card_id} is not ready for coding task creation")

        demand = await delivery_repository.get_demand(db, spec.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {spec.demand_id} not found")

        checks = required_checks or ["pytest"]
        paths = allowed_paths or []
        task_status = self.gates.decide_coding_task_status(
            spec_status=spec.status,
            risk_level=demand.risk_level,
        )
        draft = await self.provider.create_coding_task(
            demand=demand,
            spec=spec,
            allowed_paths=paths,
            required_checks=checks,
        )

        task = await delivery_repository.create_coding_task(
            db=db,
            demand_id=demand.id,
            spec_card_id=spec.id,
            status=task_status,
            title=draft.title,
            task_prompt=draft.task_prompt,
            allowed_paths=paths,
            forbidden_actions=draft.forbidden_actions,
            required_checks=checks,
            expected_evidence=draft.expected_evidence,
        )
        demand.status = DemandStatus.PLANNED

        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.CODING_TASK_READY,
            status=GateStatus.PASSED if task_status == CodingTaskStatus.READY else GateStatus.MANUAL_REQUIRED,
            reason="Coding task package was created.",
            evidence_json={"coding_task_id": task.id, "status": task.status},
        )

        await db.commit()
        return task

    async def create_execution_run(
        self,
        db: AsyncSession,
        coding_task_id: int,
        executor_type: str = "codex",
        trigger_mode: str = "manual",
    ) -> ExecutionRun:
        task = await delivery_repository.get_coding_task(db, coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        gate = self.gates.evaluate_execution_allowed(
            coding_task_id=task.id,
            coding_task_status=task.status,
            risk_level=demand.risk_level,
        )
        await self._record_gate(db, demand.id, gate)

        run_status = (
            ExecutionRunStatus.QUEUED
            if gate.status == GateStatus.PASSED
            else ExecutionRunStatus.BLOCKED
        )
        run = await delivery_repository.create_execution_run(
            db=db,
            coding_task_id=task.id,
            status=run_status,
            executor_type=executor_type,
            trigger_mode=trigger_mode,
            result_summary=(
                "Execution was queued for a future worker."
                if run_status == ExecutionRunStatus.QUEUED
                else "Execution was blocked by gate checks."
            ),
            evidence_json=gate.evidence,
        )
        await delivery_repository.create_execution_log(
            db=db,
            execution_run_id=run.id,
            level=ExecutionLogLevel.INFO
            if run_status == ExecutionRunStatus.QUEUED
            else ExecutionLogLevel.WARNING,
            message=gate.reason,
            event_json=gate.evidence,
        )

        await db.commit()
        loaded_run = await delivery_repository.get_execution_run(db, run.id)
        if not loaded_run:
            raise NotFoundException(f"Execution run {run.id} not found")
        return loaded_run

    async def dispatch_execution_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
    ) -> ExecutionRun:
        run = await delivery_repository.get_execution_run_for_dispatch(db, execution_run_id)
        if not run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        if run.status != ExecutionRunStatus.QUEUED:
            raise BadRequestException(f"Execution run {execution_run_id} is not queued")

        task = run.coding_task
        if not task:
            raise NotFoundException(f"Coding task for execution run {execution_run_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        started_at = utc_now()
        await delivery_repository.update_execution_run(
            db,
            run,
            status=ExecutionRunStatus.RUNNING,
            started_at=started_at,
            result_summary="Execution dispatch started.",
        )
        await delivery_repository.update_coding_task_status(db, task, CodingTaskStatus.RUNNING)
        await delivery_repository.create_execution_log(
            db=db,
            execution_run_id=run.id,
            level=ExecutionLogLevel.INFO,
            message="Execution dispatch started.",
            event_json={
                "executor_type": run.executor_type,
                "required_checks": task.required_checks_json,
            },
        )
        await db.commit()

        executor = get_execution_executor(run.executor_type)
        result = await executor.dispatch(
            run=run,
            task=task,
            timeout_seconds=settings.execution_command_timeout_seconds,
        )

        final_status = (
            ExecutionRunStatus.SUCCEEDED
            if result.succeeded
            else ExecutionRunStatus.FAILED
        )
        task_status = (
            CodingTaskStatus.COMPLETED
            if result.succeeded
            else CodingTaskStatus.BLOCKED
        )
        existing_evidence = run.evidence_json or {}
        finished_at = utc_now()

        await delivery_repository.update_execution_run(
            db,
            run,
            status=final_status,
            finished_at=finished_at,
            worktree_path=result.evidence.get("workspace_root"),
            result_summary=result.summary,
            evidence_json={
                "execution_allowed": existing_evidence,
                "dispatch": result.evidence,
            },
        )
        await delivery_repository.update_coding_task_status(db, task, task_status)

        for level, message, event_json in result.logs:
            await delivery_repository.create_execution_log(
                db=db,
                execution_run_id=run.id,
                level=level,
                message=message,
                event_json=event_json,
            )

        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.SELF_TEST_PASSED,
            status=GateStatus.PASSED if result.succeeded else GateStatus.FAILED,
            reason=result.summary,
            evidence_json=result.evidence,
        )

        await db.commit()
        loaded_run = await delivery_repository.get_execution_run(db, run.id)
        if not loaded_run:
            raise NotFoundException(f"Execution run {run.id} not found")
        return loaded_run

    def _derive_title(self, raw_input: str) -> str:
        compact = " ".join(raw_input.split())
        return compact[:80] if compact else "Untitled demand"

    def _classify_risk(self, raw_input: str) -> str:
        return self.gates.classify_risk(raw_input)

    def _estimate_confidence(self, raw_input: str) -> float:
        return self.gates.estimate_confidence(raw_input)

    def _decide_spec_status(
        self,
        risk_level: str,
        confidence_score: float,
        auto_approve_low_risk: bool,
    ) -> str:
        return self.gates.decide_spec_status(
            risk_level=risk_level,
            confidence_score=confidence_score,
            auto_approve_low_risk=auto_approve_low_risk,
        )

    def _merge_risks(self, provider_risks: list[str], risk_level: str) -> list[str]:
        risks = list(provider_risks)
        if risk_level in {DeliveryRiskLevel.L2, DeliveryRiskLevel.L3}:
            risks.extend(
                [
                    "Potentially sensitive or high-impact change detected.",
                    "Manual review is required before execution.",
                ]
            )
        else:
            risks.append("No high-risk keyword detected in the initial intake.")
        return risks

    def _merge_open_questions(
        self,
        provider_questions: list[str],
        risk_level: str,
        confidence_score: float,
    ) -> list[str]:
        questions = list(provider_questions)
        if confidence_score < 0.7:
            questions.append("Please clarify the expected behavior and acceptance boundary.")
        if risk_level in {DeliveryRiskLevel.L2, DeliveryRiskLevel.L3}:
            questions.append("Please confirm safety, permission, data, and release constraints.")
        return questions

    async def _resolve_repo_context(
        self,
        db: AsyncSession,
        demand_id: int,
        repo_context_id: int | None,
    ) -> RepoContext | None:
        if repo_context_id is None:
            return await delivery_repository.get_latest_repo_context(db, demand_id)

        repo_context = await delivery_repository.get_repo_context(db, repo_context_id)
        if not repo_context:
            raise NotFoundException(f"Repo context {repo_context_id} not found")
        if repo_context.demand_id != demand_id:
            raise BadRequestException("Repo context does not belong to the demand")
        return repo_context

    async def _record_gate(self, db: AsyncSession, demand_id: int, decision) -> None:
        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand_id,
            gate_type=decision.gate_type,
            status=decision.status,
            reason=decision.reason,
            evidence_json=decision.evidence,
        )


delivery_service = DeliveryService()
