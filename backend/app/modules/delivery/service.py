"""Delivery v2 business logic."""

import asyncio
import subprocess
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utc_now
from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.audit.repository import audit_repository
from app.modules.delivery.enums import (
    CodingTaskStatus,
    DeliveryRiskLevel,
    DemandStatus,
    DeploymentStatus,
    ExecutionLogLevel,
    ExecutionRunStatus,
    GateStatus,
    GateType,
    ImpactAnalysisStatus,
    MergeRequestStatus,
    RepoContextStatus,
    ReviewStatus,
    SpecStatus,
    VerificationStatus,
)
from app.modules.delivery.executors import get_execution_executor
from app.modules.delivery.gates import DeliveryGateEngine, gate_engine
from app.modules.delivery.deployments import get_deploy_client
from app.modules.delivery.models import (
    CodingTask,
    DeployRecord,
    DemandItem,
    ExecutionRun,
    ImpactAnalysis,
    MergeRequestRecord,
    RepoContext,
    SpecCard,
    VerificationRecord,
)
from app.modules.delivery.merge_requests import get_merge_request_client
from app.modules.delivery.provider_credentials import (
    ProviderCredential,
    require_provider_credential,
    resolve_provider_credential,
)
from app.modules.delivery.providers import WorkflowProvider, get_workflow_provider
from app.modules.delivery.providers.dify import DifyWorkflowProvider
from app.modules.delivery.redaction import redact_text, redact_value
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

    async def _provider_for_demand(self, db: AsyncSession, demand: DemandItem) -> WorkflowProvider:
        provider = self.provider
        if not isinstance(provider, DifyWorkflowProvider) or demand.project_id is None:
            return provider

        credential = await resolve_provider_credential(
            db,
            project_id=demand.project_id,
            provider="dify",
            secret_name=settings.dify_api_key_secret_name,
            settings_value=settings.dify_api_key,
        )
        if not credential or credential.source != "secret_store":
            return provider

        return DifyWorkflowProvider(
            api_key=credential.value,
            credential_source=credential.source,
            credential_project_id=credential.project_id,
            api_key_secret_name=credential.secret_name,
        )

    async def _merge_request_credential_for_provider(
        self,
        db: AsyncSession,
        demand: DemandItem,
        provider: str,
    ) -> ProviderCredential | None:
        normalized = (provider or "local").strip().lower()
        if normalized == "local":
            return None
        if normalized == "gitlab":
            credential = await resolve_provider_credential(
                db,
                project_id=demand.project_id,
                provider=normalized,
                secret_name=settings.gitlab_token_secret_name,
                settings_value=settings.gitlab_token,
            )
            return require_provider_credential(
                credential,
                provider=normalized,
                secret_name=settings.gitlab_token_secret_name,
                settings_name="GITLAB_TOKEN",
            )
        return None

    async def _deployment_credential_for_provider(
        self,
        db: AsyncSession,
        demand: DemandItem,
        provider: str,
    ) -> ProviderCredential | None:
        normalized = (provider or "local").strip().lower()
        if normalized == "local":
            return None
        if normalized == "webhook":
            credential = await resolve_provider_credential(
                db,
                project_id=demand.project_id,
                provider=normalized,
                secret_name=settings.deploy_token_secret_name,
                settings_value=settings.deploy_token,
            )
            return require_provider_credential(
                credential,
                provider=normalized,
                secret_name=settings.deploy_token_secret_name,
                settings_name="DEPLOY_TOKEN",
            )
        return None

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
        actor_ref: str | None = None,
    ) -> DemandItem:
        demand = await delivery_repository.create_demand(
            db=db,
            raw_input=raw_input,
            source_type=source_type,
            title=title or self._derive_title(raw_input),
            requester_ref=requester_ref,
            context_payload=context_payload,
            project_id=project_id,
            created_by_user_id=created_by_user_id,
        )
        await audit_repository.create_event(
            db,
            action="delivery.demand_created",
            entity_type="demand",
            entity_id=demand.id,
            project_id=demand.project_id,
            actor_user_id=created_by_user_id,
            actor_ref=actor_ref or requester_ref or "system",
            summary=f"Demand created: {demand.title}",
            metadata={
                "source_type": demand.source_type,
                "requester_ref": demand.requester_ref,
            },
        )
        await db.commit()
        return demand

    async def get_demand_detail(self, db: AsyncSession, demand_id: int) -> DemandItem:
        demand = await delivery_repository.get_demand_detail(db, demand_id)
        if not demand:
            raise NotFoundException(f"Demand {demand_id} not found")
        return demand

    async def list_demands(
        self,
        db: AsyncSession,
        limit: int = 30,
        offset: int = 0,
        project_ids: list[int] | None = None,
    ) -> list[DemandItem]:
        return await delivery_repository.list_demands(
            db=db,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
            project_ids=project_ids,
        )

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

    async def list_execution_runs(
        self,
        db: AsyncSession,
        statuses: list[str] | None = None,
        limit: int = 30,
        offset: int = 0,
        project_ids: list[int] | None = None,
    ) -> list[ExecutionRun]:
        return await delivery_repository.list_execution_runs(
            db=db,
            statuses=statuses,
            limit=min(max(limit, 1), 100),
            offset=max(offset, 0),
            project_ids=project_ids,
        )

    async def get_merge_request_record(
        self,
        db: AsyncSession,
        merge_request_id: int,
    ) -> MergeRequestRecord:
        record = await delivery_repository.get_merge_request_record(db, merge_request_id)
        if not record:
            raise NotFoundException(f"Merge request record {merge_request_id} not found")
        return record

    async def get_deploy_record(
        self,
        db: AsyncSession,
        deploy_record_id: int,
    ) -> DeployRecord:
        record = await delivery_repository.get_deploy_record(db, deploy_record_id)
        if not record:
            raise NotFoundException(f"Deploy record {deploy_record_id} not found")
        return record

    async def record_manual_approval(
        self,
        db: AsyncSession,
        demand_id: int,
        approved: bool,
        approver_ref: str | None = None,
        note: str | None = None,
        actor_user_id: int | None = None,
    ) -> DemandItem:
        demand = await delivery_repository.get_demand_detail(db, demand_id)
        if not demand:
            raise NotFoundException(f"Demand {demand_id} not found")

        latest_spec = self._latest_by_created_at(demand.spec_cards)
        latest_task = self._latest_by_created_at(demand.coding_tasks)
        risk_level = demand.risk_level
        approval_ref = approver_ref or "system"
        approval_time = utc_now()
        demand.manual_approval_status = "approved" if approved else "rejected"
        demand.manual_approval_user_id = actor_user_id
        demand.manual_approval_ref = approval_ref
        demand.manual_approval_note = note
        demand.manual_approval_at = approval_time
        evidence = {
            "approval_type": "manual",
            "approved": approved,
            "approver_ref": approval_ref,
            "approver_user_id": actor_user_id,
            "approved_at": approval_time.isoformat(),
            "note": note,
            "risk_level": risk_level,
            "spec_card_id": latest_spec.id if latest_spec else None,
            "coding_task_id": latest_task.id if latest_task else None,
        }

        if approved:
            if latest_spec:
                await delivery_repository.update_spec_status(db, latest_spec, SpecStatus.APPROVED)
            demand.status = DemandStatus.SPEC_APPROVED if latest_task is None else DemandStatus.PLANNED
            await delivery_repository.create_gate_check(
                db=db,
                demand_id=demand.id,
                gate_type=GateType.RISK_CLASSIFIED,
                status=GateStatus.PASSED,
                reason="Manual approval accepted the recorded risk and scope.",
                evidence_json=evidence,
            )
            await delivery_repository.create_gate_check(
                db=db,
                demand_id=demand.id,
                gate_type=GateType.EXECUTION_ALLOWED,
                status=GateStatus.PASSED,
                reason="Manual approval allows executor dispatch.",
                evidence_json=evidence,
            )
            if latest_task and latest_task.status == CodingTaskStatus.DRAFT:
                await delivery_repository.update_coding_task_status(db, latest_task, CodingTaskStatus.READY)
                await delivery_repository.create_gate_check(
                    db=db,
                    demand_id=demand.id,
                    gate_type=GateType.CODING_TASK_READY,
                    status=GateStatus.PASSED,
                    reason="Manual approval promoted the coding task to ready.",
                    evidence_json=evidence,
                )
        else:
            demand.status = DemandStatus.BLOCKED
            await delivery_repository.create_gate_check(
                db=db,
                demand_id=demand.id,
                gate_type=GateType.EXECUTION_ALLOWED,
                status=GateStatus.FAILED,
                reason="Manual approval rejected execution.",
                evidence_json=evidence,
            )
            if latest_task and latest_task.status in {CodingTaskStatus.DRAFT, CodingTaskStatus.READY}:
                await delivery_repository.update_coding_task_status(db, latest_task, CodingTaskStatus.BLOCKED)

        await audit_repository.create_event(
            db,
            action="delivery.manual_approval_recorded",
            entity_type="demand",
            entity_id=demand.id,
            project_id=demand.project_id,
            actor_user_id=actor_user_id,
            actor_ref=approval_ref,
            summary="Manual approval accepted." if approved else "Manual approval rejected.",
            metadata=evidence,
        )
        await db.commit()
        loaded_demand = await delivery_repository.get_demand_detail(db, demand_id)
        if not loaded_demand:
            raise NotFoundException(f"Demand {demand_id} not found")
        return loaded_demand

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
        provider = await self._provider_for_demand(db, demand)
        draft = await provider.generate_spec(demand)

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
        provider = await self._provider_for_demand(db, demand)
        draft = await provider.analyze_impact(demand, spec, repo_context)
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
            provider=provider.name,
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

        paths = allowed_paths or await self._derive_allowed_paths(db, demand.id)
        checks = required_checks or await self._derive_required_checks(db, demand.id, paths)
        manual_approved = await delivery_repository.has_manual_execution_approval(db, demand.id)
        task_status = (
            CodingTaskStatus.READY
            if spec.status == SpecStatus.APPROVED
            and (
                demand.risk_level in {DeliveryRiskLevel.L0, DeliveryRiskLevel.L1}
                or manual_approved
            )
            else CodingTaskStatus.DRAFT
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
        extra_evidence: dict | None = None,
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
            manual_approved=await delivery_repository.has_manual_execution_approval(db, demand.id),
        )
        await self._record_gate(db, demand.id, gate)

        run_status = (
            ExecutionRunStatus.QUEUED
            if gate.status == GateStatus.PASSED
            else ExecutionRunStatus.BLOCKED
        )
        active_run = self._active_execution_run(task)
        if run_status == ExecutionRunStatus.QUEUED and active_run:
            await delivery_repository.create_execution_log(
                db=db,
                execution_run_id=active_run.id,
                level=ExecutionLogLevel.INFO,
                message="Active execution run already exists; returning existing run.",
                event_json={
                    "coding_task_id": task.id,
                    "active_status": active_run.status,
                    "requested_executor_type": executor_type,
                    "requested_trigger_mode": trigger_mode,
                },
            )
            await db.commit()
            loaded_active_run = await delivery_repository.get_execution_run(db, active_run.id)
            if not loaded_active_run:
                raise NotFoundException(f"Execution run {active_run.id} not found")
            return loaded_active_run

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
            evidence_json={**gate.evidence, **(extra_evidence or {})},
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

    async def retry_coding_task_execution(
        self,
        db: AsyncSession,
        coding_task_id: int,
        executor_type: str = "codex",
        trigger_mode: str = "manual_retry",
    ) -> ExecutionRun:
        task = await delivery_repository.get_coding_task(db, coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {coding_task_id} not found")

        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        manual_approved = await delivery_repository.has_manual_execution_approval(db, demand.id)
        if demand.risk_level in {DeliveryRiskLevel.L2, DeliveryRiskLevel.L3} and not manual_approved:
            raise BadRequestException("Manual review is required before retrying high-risk execution")
        if task.status == CodingTaskStatus.RUNNING:
            raise BadRequestException(f"Coding task {coding_task_id} is already running")
        if task.status == CodingTaskStatus.DRAFT:
            raise BadRequestException(f"Coding task {coding_task_id} is not ready for execution retry")

        if task.status in {CodingTaskStatus.BLOCKED, CodingTaskStatus.COMPLETED}:
            await delivery_repository.update_coding_task_status(db, task, CodingTaskStatus.READY)
            await db.commit()

        queued_run = await self.create_execution_run(
            db=db,
            coding_task_id=coding_task_id,
            executor_type=executor_type,
            trigger_mode=trigger_mode,
        )
        if queued_run.status != ExecutionRunStatus.QUEUED:
            return queued_run
        return await self.dispatch_execution_run(db, queued_run.id)

    async def auto_repair_coding_task_execution(
        self,
        db: AsyncSession,
        coding_task_id: int,
        executor_type: str = "codex",
        max_attempts: int | None = None,
    ) -> list[ExecutionRun]:
        task = await delivery_repository.get_coding_task(db, coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {coding_task_id} not found")

        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")
        if demand.risk_level in {DeliveryRiskLevel.L2, DeliveryRiskLevel.L3}:
            raise BadRequestException("Automatic repair is blocked for L2/L3 risk tasks")
        if task.status == CodingTaskStatus.RUNNING:
            raise BadRequestException(f"Coding task {coding_task_id} is already running")
        if task.status == CodingTaskStatus.DRAFT:
            raise BadRequestException(f"Coding task {coding_task_id} is not ready for automatic repair")

        attempts_limit = max_attempts or settings.execution_auto_repair_max_attempts
        attempts_limit = min(max(attempts_limit, 1), 3)
        latest_run = self._latest_by_created_at(task.execution_runs)
        if not latest_run or latest_run.status != ExecutionRunStatus.FAILED:
            raise BadRequestException("Automatic repair requires a failed execution run")
        if self._has_changed_file_violations(latest_run):
            raise BadRequestException("Automatic repair is blocked because changed files exceeded allowed paths")
        if not self._has_failed_check_evidence(latest_run):
            raise BadRequestException("Automatic repair requires failed check evidence")

        repair_runs: list[ExecutionRun] = []
        current_failure = latest_run
        for attempt in range(1, attempts_limit + 1):
            if task.status in {CodingTaskStatus.BLOCKED, CodingTaskStatus.COMPLETED}:
                await delivery_repository.update_coding_task_status(db, task, CodingTaskStatus.READY)
                await db.commit()

            repair_context = self._build_repair_context(
                source_run=current_failure,
                attempt=attempt,
                max_attempts=attempts_limit,
            )
            queued_run = await self.create_execution_run(
                db=db,
                coding_task_id=coding_task_id,
                executor_type=executor_type,
                trigger_mode="auto_repair",
                extra_evidence={"repair_context": repair_context},
            )
            if queued_run.status != ExecutionRunStatus.QUEUED:
                repair_runs.append(queued_run)
                break

            repaired_run = await self.dispatch_execution_run(db, queued_run.id)
            repair_runs.append(repaired_run)
            if repaired_run.status == ExecutionRunStatus.SUCCEEDED:
                break
            if self._has_changed_file_violations(repaired_run) or not self._has_failed_check_evidence(repaired_run):
                break
            current_failure = repaired_run

        return repair_runs

    async def create_merge_request_record(
        self,
        db: AsyncSession,
        coding_task_id: int,
        execution_run_id: int | None = None,
        provider: str = "local",
        target_branch: str | None = None,
        title: str | None = None,
        url: str | None = None,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> MergeRequestRecord:
        task = await delivery_repository.get_coding_task(db, coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")
        if task.status != CodingTaskStatus.COMPLETED:
            raise BadRequestException("A completed coding task is required before creating a merge request")

        run = self._resolve_successful_run(task, execution_run_id)
        if not run:
            raise BadRequestException("A succeeded execution run is required before creating a merge request")

        source_branch = run.branch_name or self._dispatch_evidence_value(run, "branch_name")
        if not source_branch:
            raise BadRequestException("Execution run has no source branch for merge request creation")

        existing = await delivery_repository.get_latest_merge_request_for_task(db, coding_task_id)
        if existing and existing.execution_run_id == run.id and existing.status != MergeRequestStatus.CLOSED:
            return existing

        resolved_target_branch = target_branch or settings.merge_request_default_target_branch
        resolved_title = title or task.title
        credential = await self._merge_request_credential_for_provider(db, demand, provider)
        git_push_evidence = await self._push_source_branch_for_provider(
            provider=provider,
            run=run,
            source_branch=source_branch,
        )
        description = self._build_merge_request_description(
            demand=demand,
            task=task,
            run=run,
            source_branch=source_branch,
            target_branch=resolved_target_branch,
        )
        client = get_merge_request_client(provider, credential=credential)
        draft = await client.create_merge_request(
            task=task,
            run=run,
            title=resolved_title,
            description=description,
            source_branch=source_branch,
            target_branch=resolved_target_branch,
            url=url,
        )

        evidence = {
            "execution_run_id": run.id,
            "commit_sha": run.commit_sha,
            "source_branch": source_branch,
            "target_branch": resolved_target_branch,
            "created_by_user_id": actor_user_id,
            "created_by_ref": actor_ref or "system",
            "git_push": git_push_evidence,
            "provider_evidence": draft.evidence,
        }
        record = await delivery_repository.create_merge_request_record(
            db=db,
            coding_task_id=task.id,
            execution_run_id=run.id,
            provider=draft.provider,
            status=self._enum_or_str(draft.status),
            review_status=self._enum_or_str(draft.review_status),
            title=resolved_title,
            source_branch=source_branch,
            target_branch=resolved_target_branch,
            external_id=draft.external_id,
            url=draft.url,
            evidence_json=evidence,
            created_by_user_id=actor_user_id,
            created_by_ref=actor_ref or "system",
        )
        if draft.provider == "local" and not record.url:
            await delivery_repository.update_merge_request_record(
                db,
                record,
                external_id=str(record.id),
                url=f"local://merge-requests/{record.id}",
            )

        await audit_repository.create_event(
            db,
            action="delivery.merge_request_created",
            entity_type="merge_request",
            entity_id=record.id,
            project_id=demand.project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=f"Merge request record created: {record.title}",
            metadata={
                "coding_task_id": task.id,
                "execution_run_id": run.id,
                "provider": record.provider,
                "source_branch": record.source_branch,
                "target_branch": record.target_branch,
                "url": record.url,
            },
        )
        await db.commit()
        loaded_record = await delivery_repository.get_merge_request_record(db, record.id)
        if not loaded_record:
            raise NotFoundException(f"Merge request record {record.id} not found")
        return loaded_record

    async def record_merge_request_review(
        self,
        db: AsyncSession,
        merge_request_id: int,
        review_status: str,
        review_summary: str | None = None,
        review_comments: list[dict] | None = None,
        blocking_issues: list[str] | None = None,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> MergeRequestRecord:
        record = await delivery_repository.get_merge_request_record(db, merge_request_id)
        if not record:
            raise NotFoundException(f"Merge request record {merge_request_id} not found")

        task = await delivery_repository.get_coding_task(db, record.coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {record.coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        blockers = blocking_issues or []
        final_review_status = ReviewStatus.BLOCKING if blockers else review_status
        final_review_status_value = self._enum_or_str(final_review_status)
        final_status = (
            MergeRequestStatus.REVIEW_PASSED
            if final_review_status_value == ReviewStatus.PASSED
            else MergeRequestStatus.REVIEW_BLOCKED
        )
        final_status_value = self._enum_or_str(final_status)
        comments = review_comments or []
        reviewed_at = utc_now()
        reviewer_ref = actor_ref or "system"
        evidence = {
            **(record.evidence_json or {}),
            "review_status": final_review_status_value,
            "review_summary": review_summary,
            "review_comments": comments,
            "blocking_issues": blockers,
            "reviewed_by_user_id": actor_user_id,
            "reviewed_by_ref": reviewer_ref,
            "reviewed_at": reviewed_at.isoformat(),
        }
        await delivery_repository.update_merge_request_record(
            db,
            record,
            status=final_status_value,
            review_status=final_review_status_value,
            review_summary=review_summary,
            review_comments_json=comments,
            evidence_json=evidence,
            reviewed_by_user_id=actor_user_id,
            reviewed_by_ref=reviewer_ref,
            reviewed_at=reviewed_at,
        )
        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.REVIEW_PASSED,
            status=GateStatus.PASSED if final_review_status_value == ReviewStatus.PASSED else GateStatus.FAILED,
            reason=review_summary or (
                "Merge request review passed."
                if final_review_status_value == ReviewStatus.PASSED
                else "Merge request review has blocking issues."
            ),
            evidence_json={
                "merge_request_id": record.id,
                "review_status": final_review_status_value,
                "blocking_issues": blockers,
            },
        )

        await audit_repository.create_event(
            db,
            action="delivery.merge_request_review_recorded",
            entity_type="merge_request",
            entity_id=record.id,
            project_id=demand.project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=review_summary or f"Merge request review recorded: {final_review_status_value}",
            metadata={
                "review_status": final_review_status_value,
                "blocking_issues": blockers,
                "review_comment_count": len(comments),
            },
        )
        await db.commit()
        loaded_record = await delivery_repository.get_merge_request_record(db, record.id)
        if not loaded_record:
            raise NotFoundException(f"Merge request record {record.id} not found")
        return loaded_record

    async def sync_merge_request_remote_review(
        self,
        db: AsyncSession,
        merge_request_id: int,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> MergeRequestRecord:
        record = await delivery_repository.get_merge_request_record(db, merge_request_id)
        if not record:
            raise NotFoundException(f"Merge request record {merge_request_id} not found")

        task = await delivery_repository.get_coding_task(db, record.coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {record.coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        credential = await self._merge_request_credential_for_provider(db, demand, record.provider)
        client = get_merge_request_client(record.provider, credential=credential)
        remote_review = await client.fetch_remote_review(
            record=record,
            commit_sha=self._merge_request_commit_sha(record, task),
        )
        review_status_value = self._enum_or_str(remote_review.review_status)
        status_value = self._enum_or_str(remote_review.status)
        reviewed_at = utc_now()
        summary = redact_text(remote_review.summary)
        comments = redact_value(remote_review.comments)
        blockers = [redact_text(item) for item in remote_review.blocking_issues]
        remote_evidence = redact_value(remote_review.evidence)
        evidence = {
            **(record.evidence_json or {}),
            "remote_review": remote_evidence,
            "remote_review_synced_at": reviewed_at.isoformat(),
            "remote_review_synced_by_user_id": actor_user_id,
            "remote_review_synced_by_ref": actor_ref or "system",
        }

        await delivery_repository.update_merge_request_record(
            db,
            record,
            status=status_value,
            review_status=review_status_value,
            review_summary=summary,
            review_comments_json=comments,
            evidence_json=evidence,
            reviewed_by_user_id=actor_user_id,
            reviewed_by_ref=actor_ref or "system",
            reviewed_at=reviewed_at,
        )
        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.REVIEW_PASSED,
            status=self._review_gate_status(review_status_value),
            reason=summary,
            evidence_json={
                "merge_request_id": record.id,
                "review_status": review_status_value,
                "blocking_issues": blockers,
                "remote_review": remote_evidence,
            },
        )
        await audit_repository.create_event(
            db,
            action="delivery.merge_request_remote_review_synced",
            entity_type="merge_request",
            entity_id=record.id,
            project_id=demand.project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=summary,
            metadata={
                "review_status": review_status_value,
                "blocking_issues": blockers,
                "provider": record.provider,
            },
        )
        await db.commit()
        loaded_record = await delivery_repository.get_merge_request_record(db, record.id)
        if not loaded_record:
            raise NotFoundException(f"Merge request record {record.id} not found")
        return loaded_record

    async def create_deploy_record(
        self,
        db: AsyncSession,
        merge_request_id: int,
        provider: str = "local",
        environment: str = "test",
        url: str | None = None,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> DeployRecord:
        merge_request = await delivery_repository.get_merge_request_record(db, merge_request_id)
        if not merge_request:
            raise NotFoundException(f"Merge request record {merge_request_id} not found")
        if merge_request.review_status != ReviewStatus.PASSED:
            raise BadRequestException("A passed merge request review is required before test deployment")

        task = await delivery_repository.get_coding_task(db, merge_request.coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {merge_request.coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        credential = await self._deployment_credential_for_provider(db, demand, provider)
        client = get_deploy_client(provider, credential=credential)
        draft = await client.create_deployment(
            task=task,
            merge_request=merge_request,
            environment=environment,
            url=url,
        )
        status = self._enum_or_str(draft.status)
        evidence = {
            "merge_request_id": merge_request.id,
            "coding_task_id": task.id,
            "environment": environment,
            "provider": draft.provider,
            "created_by_user_id": actor_user_id,
            "created_by_ref": actor_ref or "system",
            "provider_evidence": draft.evidence,
        }
        deploy_record = await delivery_repository.create_deploy_record(
            db=db,
            merge_request_id=merge_request.id,
            coding_task_id=task.id,
            provider=draft.provider,
            status=status,
            environment=environment,
            url=draft.url,
            evidence_json=evidence,
            created_by_user_id=actor_user_id,
            created_by_ref=actor_ref or "system",
        )
        if draft.provider == "local" and not deploy_record.url:
            await delivery_repository.update_deploy_record(
                db,
                deploy_record,
                url=f"local://deployments/{deploy_record.id}",
            )

        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.TEST_DEPLOYED,
            status=GateStatus.PASSED if status == self._enum_or_str(DeploymentStatus.DEPLOYED) else GateStatus.FAILED,
            reason=(
                "Test deployment record was created."
                if status == self._enum_or_str(DeploymentStatus.DEPLOYED)
                else "Test deployment provider reported failure."
            ),
            evidence_json={
                "deploy_record_id": deploy_record.id,
                "merge_request_id": merge_request.id,
                "environment": environment,
                "url": deploy_record.url,
            },
        )
        await audit_repository.create_event(
            db,
            action="delivery.test_deployment_created",
            entity_type="deployment",
            entity_id=deploy_record.id,
            project_id=demand.project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=f"Test deployment record created: {deploy_record.environment}",
            metadata={
                "merge_request_id": merge_request.id,
                "coding_task_id": task.id,
                "provider": deploy_record.provider,
                "environment": deploy_record.environment,
                "url": deploy_record.url,
            },
        )
        await db.commit()

        loaded_record = await delivery_repository.get_deploy_record(db, deploy_record.id)
        if not loaded_record:
            raise NotFoundException(f"Deploy record {deploy_record.id} not found")
        return loaded_record

    async def record_verification(
        self,
        db: AsyncSession,
        deploy_record_id: int,
        status: str,
        verifier_ref: str | None = None,
        summary: str | None = None,
        evidence_links: list[str] | None = None,
        actor_user_id: int | None = None,
    ) -> VerificationRecord:
        deploy_record = await delivery_repository.get_deploy_record(db, deploy_record_id)
        if not deploy_record:
            raise NotFoundException(f"Deploy record {deploy_record_id} not found")

        task = await delivery_repository.get_coding_task(db, deploy_record.coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {deploy_record.coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        status_value = self._enum_or_str(status)
        verification = await delivery_repository.create_verification_record(
            db=db,
            deploy_record_id=deploy_record.id,
            status=status_value,
            verifier_user_id=actor_user_id,
            verifier_ref=verifier_ref,
            summary=summary,
            evidence_links=evidence_links,
            evidence_json={
                "deploy_record_id": deploy_record.id,
                "status": status_value,
                "verifier_ref": verifier_ref,
                "evidence_links": evidence_links or [],
            },
        )
        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.VERIFICATION_PASSED,
            status=GateStatus.PASSED if status_value == VerificationStatus.PASSED else GateStatus.FAILED,
            reason=summary or (
                "Test deployment verification passed."
                if status_value == VerificationStatus.PASSED
                else "Test deployment verification failed."
            ),
            evidence_json={
                "verification_record_id": verification.id,
                "deploy_record_id": deploy_record.id,
                "status": status_value,
            },
        )
        await audit_repository.create_event(
            db,
            action="delivery.verification_recorded",
            entity_type="verification",
            entity_id=verification.id,
            project_id=demand.project_id,
            actor_user_id=actor_user_id,
            actor_ref=verifier_ref or "system",
            summary=summary or f"Verification recorded: {status_value}",
            metadata={
                "deploy_record_id": deploy_record.id,
                "status": status_value,
                "evidence_links": evidence_links or [],
            },
        )
        await db.commit()
        return verification

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

        executor = get_execution_executor(run.executor_type)
        if getattr(executor, "deferred", False):
            return await self._dispatch_deferred_execution_run(
                db=db,
                run=run,
                task=task,
                executor=executor,
            )

        running_count = await delivery_repository.count_running_execution_runs(
            db,
            exclude_run_id=run.id,
        )
        if running_count >= settings.execution_max_concurrency:
            await delivery_repository.create_execution_log(
                db=db,
                execution_run_id=run.id,
                level=ExecutionLogLevel.WARNING,
                message="Execution concurrency limit reached; run remains queued.",
                event_json={
                    "running_count": running_count,
                    "max_concurrency": settings.execution_max_concurrency,
                },
            )
            await db.commit()
            raise BadRequestException("Execution concurrency limit reached; run remains queued")

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
                "required_checks": redact_value(task.required_checks_json),
            },
        )
        await db.commit()

        result = await executor.dispatch(
            run=run,
            task=task,
            timeout_seconds=settings.execution_command_timeout_seconds,
        )
        await db.refresh(run)
        if run.status == ExecutionRunStatus.CANCELLED:
            loaded_run = await delivery_repository.get_execution_run(db, run.id)
            if not loaded_run:
                raise NotFoundException(f"Execution run {run.id} not found")
            return loaded_run

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
        safe_summary = redact_text(result.summary)
        safe_evidence = redact_value(result.evidence)
        safe_existing_evidence = redact_value(existing_evidence)
        finished_at = utc_now()

        await delivery_repository.update_execution_run(
            db,
            run,
            status=final_status,
            finished_at=finished_at,
            worktree_path=result.evidence.get("workspace_root"),
            branch_name=result.evidence.get("branch_name"),
            commit_sha=result.evidence.get("commit_sha"),
            result_summary=safe_summary,
            evidence_json={
                "execution_allowed": safe_existing_evidence,
                "dispatch": safe_evidence,
            },
        )
        await delivery_repository.update_coding_task_status(db, task, task_status)

        for level, message, event_json in result.logs:
            await delivery_repository.create_execution_log(
                db=db,
                execution_run_id=run.id,
                level=level,
                message=redact_text(message),
                event_json=redact_value(event_json) if event_json is not None else None,
            )

        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.SELF_TEST_PASSED,
            status=GateStatus.PASSED if result.succeeded else GateStatus.FAILED,
            reason=safe_summary,
            evidence_json=safe_evidence,
        )

        await db.commit()
        loaded_run = await delivery_repository.get_execution_run(db, run.id)
        if not loaded_run:
            raise NotFoundException(f"Execution run {run.id} not found")
        return loaded_run

    async def _dispatch_deferred_execution_run(
        self,
        *,
        db: AsyncSession,
        run: ExecutionRun,
        task: CodingTask,
        executor,
    ) -> ExecutionRun:
        result = await executor.dispatch(
            run=run,
            task=task,
            timeout_seconds=settings.execution_command_timeout_seconds,
        )
        existing_evidence = run.evidence_json or {}
        safe_summary = redact_text(result.summary)
        safe_evidence = redact_value(result.evidence)

        await delivery_repository.update_execution_run(
            db,
            run,
            status=ExecutionRunStatus.QUEUED,
            result_summary=safe_summary,
            evidence_json={
                "execution_allowed": self._execution_allowed_evidence(existing_evidence),
                "dispatch": safe_evidence,
            },
        )

        for level, message, event_json in result.logs:
            await delivery_repository.create_execution_log(
                db=db,
                execution_run_id=run.id,
                level=level,
                message=redact_text(message),
                event_json=redact_value(event_json) if event_json is not None else None,
            )

        await db.commit()
        loaded_run = await delivery_repository.get_execution_run(db, run.id)
        if not loaded_run:
            raise NotFoundException(f"Execution run {run.id} not found")
        return loaded_run

    async def pause_execution_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
        reason: str | None = None,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> ExecutionRun:
        run = await delivery_repository.get_execution_run_with_task(db, execution_run_id)
        if not run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        if run.status != ExecutionRunStatus.QUEUED:
            raise BadRequestException("Only queued execution runs can be paused")

        summary = "Execution run paused by operator."
        evidence_json = self._control_evidence(
            run,
            action="paused",
            reason=reason,
            actor_ref=actor_ref,
        )
        await delivery_repository.update_execution_run(
            db,
            run,
            status=ExecutionRunStatus.PAUSED,
            result_summary=summary,
            evidence_json=evidence_json,
        )
        if run.coding_task:
            await delivery_repository.update_coding_task_status(db, run.coding_task, CodingTaskStatus.READY)
        await self._record_execution_control(
            db=db,
            run=run,
            action="paused",
            summary=summary,
            reason=reason,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref,
            level=ExecutionLogLevel.INFO,
        )
        await db.commit()
        return await self._reload_execution_run(db, run.id)

    async def resume_execution_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
        reason: str | None = None,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> ExecutionRun:
        run = await delivery_repository.get_execution_run_with_task(db, execution_run_id)
        if not run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        if run.status != ExecutionRunStatus.PAUSED:
            raise BadRequestException("Only paused execution runs can be resumed")

        summary = "Execution run resumed and returned to queue."
        evidence_json = self._control_evidence(
            run,
            action="resumed",
            reason=reason,
            actor_ref=actor_ref,
        )
        await delivery_repository.update_execution_run(
            db,
            run,
            status=ExecutionRunStatus.QUEUED,
            result_summary=summary,
            evidence_json=evidence_json,
        )
        if run.coding_task:
            await delivery_repository.update_coding_task_status(db, run.coding_task, CodingTaskStatus.READY)
        await self._record_execution_control(
            db=db,
            run=run,
            action="resumed",
            summary=summary,
            reason=reason,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref,
            level=ExecutionLogLevel.INFO,
        )
        await db.commit()
        return await self._reload_execution_run(db, run.id)

    async def cancel_execution_run(
        self,
        db: AsyncSession,
        execution_run_id: int,
        reason: str | None = None,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> ExecutionRun:
        run = await delivery_repository.get_execution_run_with_task(db, execution_run_id)
        if not run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        if run.status not in {
            ExecutionRunStatus.QUEUED,
            ExecutionRunStatus.PAUSED,
            ExecutionRunStatus.RUNNING,
        }:
            raise BadRequestException("Only queued, paused or running execution runs can be cancelled")

        previous_status = run.status
        summary = "Execution run cancelled by operator."
        evidence_json = self._control_evidence(
            run,
            action="cancelled",
            reason=reason,
            actor_ref=actor_ref,
        )
        await delivery_repository.update_execution_run(
            db,
            run,
            status=ExecutionRunStatus.CANCELLED,
            finished_at=utc_now(),
            result_summary=summary,
            evidence_json=evidence_json,
        )
        if run.coding_task:
            next_task_status = (
                CodingTaskStatus.BLOCKED
                if previous_status == ExecutionRunStatus.RUNNING
                else CodingTaskStatus.READY
            )
            await delivery_repository.update_coding_task_status(db, run.coding_task, next_task_status)
            if previous_status == ExecutionRunStatus.RUNNING:
                await delivery_repository.create_gate_check(
                    db=db,
                    demand_id=run.coding_task.demand_id,
                    gate_type=GateType.SELF_TEST_PASSED,
                    status=GateStatus.FAILED,
                    reason=summary,
                    evidence_json={
                        "execution_run_id": run.id,
                        "previous_status": previous_status,
                        "reason": reason,
                    },
                )
        await self._record_execution_control(
            db=db,
            run=run,
            action="cancelled",
            summary=summary,
            reason=reason,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref,
            level=ExecutionLogLevel.WARNING,
            extra={"previous_status": previous_status},
        )
        await db.commit()
        return await self._reload_execution_run(db, run.id)

    async def _reload_execution_run(self, db: AsyncSession, execution_run_id: int) -> ExecutionRun:
        loaded_run = await delivery_repository.get_execution_run(db, execution_run_id)
        if not loaded_run:
            raise NotFoundException(f"Execution run {execution_run_id} not found")
        return loaded_run

    def _control_evidence(
        self,
        run: ExecutionRun,
        *,
        action: str,
        reason: str | None,
        actor_ref: str | None,
    ) -> dict:
        evidence = dict(run.evidence_json or {})
        controls = list(evidence.get("controls") or [])
        controls.append(
            redact_value(
                {
                    "action": action,
                    "reason": reason,
                    "actor_ref": actor_ref or "system",
                    "recorded_at": utc_now().isoformat(),
                }
            )
        )
        evidence["controls"] = controls
        evidence["last_control"] = controls[-1]
        return redact_value(evidence)

    async def _record_execution_control(
        self,
        *,
        db: AsyncSession,
        run: ExecutionRun,
        action: str,
        summary: str,
        reason: str | None,
        actor_user_id: int | None,
        actor_ref: str | None,
        level: str,
        extra: dict | None = None,
    ) -> None:
        event_json = redact_value(
            {
                "action": action,
                "reason": reason,
                "actor_ref": actor_ref or "system",
                **(extra or {}),
            }
        )
        await delivery_repository.create_execution_log(
            db=db,
            execution_run_id=run.id,
            level=level,
            message=summary,
            event_json=event_json,
        )
        task = run.coding_task
        demand = task.demand if task else None
        await audit_repository.create_event(
            db,
            action=f"delivery.execution_{action}",
            entity_type="execution_run",
            entity_id=run.id,
            project_id=demand.project_id if demand else None,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=summary,
            metadata=event_json,
        )

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

    async def _derive_allowed_paths(self, db: AsyncSession, demand_id: int) -> list[str]:
        impact = await delivery_repository.get_latest_impact_analysis(db, demand_id)
        repo_context = await delivery_repository.get_latest_repo_context(db, demand_id)
        candidate_files = []
        if impact and impact.affected_files_json:
            candidate_files.extend(impact.affected_files_json or [])
        elif repo_context:
            candidate_files.extend(repo_context.discovered_files_json or [])

        paths: list[str] = []
        for file_path in candidate_files:
            normalized = file_path.replace("\\", "/").strip("/")
            if not normalized:
                continue
            parts = normalized.split("/")
            if normalized.startswith("frontend/src/app/") and len(parts) >= 4:
                paths.append("/".join(parts[:4]))
            elif normalized.startswith("backend/app/modules/") and len(parts) >= 4:
                paths.append("/".join(parts[:4]))
            elif normalized.startswith("backend/tests/"):
                paths.append("backend/tests")
            elif normalized.startswith("docs/"):
                paths.append("docs")
            elif len(parts) >= 2:
                paths.append("/".join(parts[:2]))
            else:
                paths.append(normalized)

        return self._dedupe(paths)[:12]

    async def _derive_required_checks(
        self,
        db: AsyncSession,
        demand_id: int,
        allowed_paths: list[str],
    ) -> list[str]:
        repo_context = await delivery_repository.get_latest_repo_context(db, demand_id)
        dependency_refs = repo_context.dependency_refs_json if repo_context else []
        checks: list[str] = []

        touches_frontend = any(path.startswith("frontend/") for path in allowed_paths)
        touches_backend = any(path.startswith("backend/") for path in allowed_paths)

        if touches_frontend and "frontend/package.json:scripts.build" in dependency_refs:
            checks.append("npm run build")
        if touches_backend and "backend/tests" in dependency_refs:
            checks.append("python -m pytest")
        if not checks and "frontend/package.json:scripts.build" in dependency_refs:
            checks.append("npm run build")
        if not checks:
            checks.append("pytest")

        return checks

    def _dedupe(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            result.append(normalized)
        return result

    def _resolve_successful_run(
        self,
        task: CodingTask,
        execution_run_id: int | None,
    ) -> ExecutionRun | None:
        runs = task.execution_runs or []
        if execution_run_id is not None:
            selected = next((run for run in runs if run.id == execution_run_id), None)
            if selected and selected.status == ExecutionRunStatus.SUCCEEDED:
                return selected
            return None
        succeeded = [run for run in runs if run.status == ExecutionRunStatus.SUCCEEDED]
        return self._latest_by_created_at(succeeded)

    def _dispatch_evidence_value(self, run: ExecutionRun, key: str) -> str | None:
        evidence = run.evidence_json or {}
        dispatch = evidence.get("dispatch") if isinstance(evidence, dict) else {}
        if not isinstance(dispatch, dict):
            return None
        value = dispatch.get(key)
        return str(value) if value else None

    def _merge_request_commit_sha(self, record: MergeRequestRecord, task: CodingTask) -> str | None:
        evidence = record.evidence_json or {}
        if isinstance(evidence, dict):
            value = evidence.get("commit_sha")
            if value:
                return str(value)
            provider_evidence = evidence.get("provider_evidence")
            if isinstance(provider_evidence, dict):
                value = provider_evidence.get("commit_sha")
                if value:
                    return str(value)

        for run in task.execution_runs or []:
            if run.id == record.execution_run_id:
                return run.commit_sha or self._dispatch_evidence_value(run, "commit_sha")
        return None

    def _review_gate_status(self, review_status: str) -> GateStatus:
        if review_status == self._enum_or_str(ReviewStatus.PASSED):
            return GateStatus.PASSED
        if review_status == self._enum_or_str(ReviewStatus.BLOCKING):
            return GateStatus.FAILED
        return GateStatus.MANUAL_REQUIRED

    async def _push_source_branch_for_provider(
        self,
        *,
        provider: str,
        run: ExecutionRun,
        source_branch: str,
    ) -> dict:
        normalized_provider = (provider or "local").strip().lower()
        if normalized_provider == "local":
            return {"enabled": False, "reason": "local_provider"}
        if normalized_provider != "gitlab":
            return {"enabled": False, "reason": "provider_not_supported", "provider": normalized_provider}
        if not settings.merge_request_auto_push_enabled:
            return {"enabled": False, "reason": "disabled"}

        remote = settings.merge_request_git_remote.strip()
        if not remote:
            raise BadRequestException("MERGE_REQUEST_GIT_REMOTE is required when auto push is enabled")
        if not run.worktree_path:
            raise BadRequestException("Execution run has no worktree path for remote branch push")

        worktree_path = Path(run.worktree_path).expanduser()
        if not worktree_path.exists() or not worktree_path.is_dir():
            raise BadRequestException(f"Execution worktree does not exist: {run.worktree_path}")

        try:
            completed = await asyncio.to_thread(
                self._run_git_push,
                worktree_path,
                remote,
                source_branch,
            )
        except subprocess.TimeoutExpired as exc:
            raise BadRequestException(
                "Git push timed out before merge request creation: "
                f"{self._safe_tail(exc.stderr) or self._safe_tail(exc.stdout)}"
            ) from exc
        stdout_tail = self._safe_tail(completed.stdout)
        stderr_tail = self._safe_tail(completed.stderr)
        if completed.returncode != 0:
            detail = stderr_tail or stdout_tail or "git push failed"
            raise BadRequestException(f"Git push failed before merge request creation: {detail}")

        return {
            "enabled": True,
            "provider": normalized_provider,
            "remote": remote,
            "branch": source_branch,
            "timeout_seconds": settings.merge_request_push_timeout_seconds,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }

    def _run_git_push(
        self,
        worktree_path: Path,
        remote: str,
        source_branch: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "git",
                "-C",
                str(worktree_path),
                "push",
                "--set-upstream",
                remote,
                f"{source_branch}:{source_branch}",
            ],
            capture_output=True,
            text=True,
            timeout=settings.merge_request_push_timeout_seconds,
            check=False,
        )

    def _safe_tail(self, value: str | bytes | None, limit: int = 2000) -> str:
        if value is None:
            return ""
        text = value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value)
        text = redact_text(text).strip()
        if len(text) <= limit:
            return text
        return text[-limit:]

    def _build_merge_request_description(
        self,
        *,
        demand: DemandItem,
        task: CodingTask,
        run: ExecutionRun,
        source_branch: str,
        target_branch: str,
    ) -> str:
        evidence = run.evidence_json or {}
        dispatch = evidence.get("dispatch") if isinstance(evidence, dict) else {}
        if not isinstance(dispatch, dict):
            dispatch = {}

        changed_files = self._string_items(dispatch.get("changed_files"))
        check_results = self._check_result_lines(dispatch)
        lines = [
            "## AI PJM Delivery Summary",
            "",
            "### Demand",
            f"- Demand ID: {demand.id}",
            f"- Title: {demand.title or task.title}",
            f"- Risk level: {demand.risk_level or 'unknown'}",
            "",
            "### Task",
            f"- Task ID: {task.id}",
            f"- Execution run ID: {run.id}",
            f"- Source branch: {source_branch}",
            f"- Target branch: {target_branch}",
            f"- Commit: {run.commit_sha or self._dispatch_evidence_value(run, 'commit_sha') or 'unknown'}",
            f"- Result: {run.result_summary or 'No execution summary recorded.'}",
            "",
            "### Required Checks",
        ]
        lines.extend(self._markdown_items(task.required_checks_json or [], empty="No required checks recorded."))
        lines.extend(["", "### Check Results"])
        lines.extend(self._markdown_items(check_results, empty="No check results recorded."))
        lines.extend(["", "### Changed Files"])
        lines.extend(self._markdown_items(changed_files, empty="No changed files recorded."))
        lines.extend(["", "### Allowed Paths"])
        lines.extend(self._markdown_items(task.allowed_paths_json or [], empty="No allowed paths recorded."))
        return redact_text("\n".join(lines))

    def _check_result_lines(self, dispatch: dict) -> list[str]:
        raw_results = dispatch.get("check_results")
        if not isinstance(raw_results, list):
            raw_results = dispatch.get("command_results")
        if not isinstance(raw_results, list):
            return []
        results: list[str] = []
        for raw_result in raw_results:
            if not isinstance(raw_result, dict):
                continue
            command = str(raw_result.get("command") or raw_result.get("name") or "unknown")
            status = str(raw_result.get("status") or "unknown")
            exit_code = raw_result.get("exit_code")
            suffix = f", exit {exit_code}" if exit_code is not None else ""
            results.append(f"{command}: {status}{suffix}")
        return results

    def _string_items(self, value) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _markdown_items(self, values: list[str], *, empty: str) -> list[str]:
        items = [str(value).strip() for value in values if str(value).strip()]
        if not items:
            return [f"- {empty}"]
        return [f"- {item}" for item in items]

    def _execution_allowed_evidence(self, evidence: dict) -> dict:
        if "execution_allowed" in evidence and isinstance(evidence["execution_allowed"], dict):
            return redact_value(evidence["execution_allowed"])
        return redact_value({key: value for key, value in evidence.items() if key != "dispatch"})

    def _active_execution_run(self, task: CodingTask) -> ExecutionRun | None:
        active_statuses = {
            ExecutionRunStatus.QUEUED,
            ExecutionRunStatus.RUNNING,
            ExecutionRunStatus.PAUSED,
        }
        active_runs = [
            run for run in (task.execution_runs or [])
            if run.status in active_statuses
        ]
        return self._latest_by_created_at(active_runs)

    def _enum_or_str(self, value) -> str:
        return str(value.value) if hasattr(value, "value") else str(value)

    def _build_repair_context(
        self,
        *,
        source_run: ExecutionRun,
        attempt: int,
        max_attempts: int,
    ) -> dict:
        source_evidence = source_run.evidence_json or {}
        dispatch = source_evidence.get("dispatch") if isinstance(source_evidence, dict) else {}
        if not isinstance(dispatch, dict):
            dispatch = {}
        failed_checks = [
            {
                "command": check.get("command"),
                "status": check.get("status"),
                "exit_code": check.get("exit_code"),
                "error": check.get("error"),
                "stdout_tail": check.get("stdout_tail"),
                "stderr_tail": check.get("stderr_tail"),
            }
            for check in dispatch.get("check_results", [])
            if isinstance(check, dict) and check.get("status") != "passed"
        ]
        execution_allowed = source_evidence.get("execution_allowed")
        previous_context = execution_allowed.get("repair_context") if isinstance(execution_allowed, dict) else None
        previous_chain = []
        if isinstance(previous_context, dict) and isinstance(previous_context.get("repair_chain"), list):
            previous_chain = [item for item in previous_context["repair_chain"] if isinstance(item, int)]

        return {
            "source_run_id": source_run.id,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "failure_summary": source_run.result_summary,
            "failed_checks": failed_checks,
            "repair_chain": [*previous_chain, source_run.id],
        }

    def _has_failed_check_evidence(self, run: ExecutionRun) -> bool:
        evidence = run.evidence_json or {}
        dispatch = evidence.get("dispatch") if isinstance(evidence, dict) else {}
        if not isinstance(dispatch, dict):
            return False
        return any(
            isinstance(check, dict) and check.get("status") != "passed"
            for check in dispatch.get("check_results", [])
        )

    def _has_changed_file_violations(self, run: ExecutionRun) -> bool:
        evidence = run.evidence_json or {}
        dispatch = evidence.get("dispatch") if isinstance(evidence, dict) else {}
        if not isinstance(dispatch, dict):
            return False
        invocation = dispatch.get("codex_invocation")
        if isinstance(invocation, dict) and invocation.get("changed_file_violations"):
            return True
        return bool(dispatch.get("changed_file_violations"))

    async def _record_gate(self, db: AsyncSession, demand_id: int, decision) -> None:
        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand_id,
            gate_type=decision.gate_type,
            status=decision.status,
            reason=decision.reason,
            evidence_json=decision.evidence,
        )

    def _latest_by_created_at(self, items):
        if not items:
            return None
        return sorted(items, key=lambda item: (item.created_at, item.id), reverse=True)[0]


delivery_service = DeliveryService()
