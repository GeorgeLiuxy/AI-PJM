"""Delivery v2 business logic."""

import asyncio
import hashlib
import hmac
import json
import re
import shutil
import subprocess
from collections import Counter
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utc_now
from app.core.exceptions import AIServiceException, BadRequestException, NotFoundException
from app.modules.audit.repository import audit_repository
from app.modules.auth.repository import auth_repository
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
from app.modules.delivery.gates import DeliveryGateEngine, GateDecision, gate_engine
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
from app.modules.delivery.providers.local import LocalWorkflowProvider
from app.modules.delivery.providers.openai import OpenAIWorkflowProvider
from app.modules.delivery.providers.quality import evaluate_impact_draft, evaluate_spec_draft
from app.modules.delivery.redaction import has_unredacted_sensitive_data, redact_text, redact_value
from app.modules.delivery.repository import delivery_repository
from app.modules.secrets.repository import secret_repository
from app.modules.secrets.service import secret_store_service


ProviderDraftT = TypeVar("ProviderDraftT")


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
        if demand.project_id is None:
            return provider

        if isinstance(provider, OpenAIWorkflowProvider):
            credential = await resolve_provider_credential(
                db,
                project_id=demand.project_id,
                provider="openai",
                secret_name=settings.openai_api_key_secret_name,
                settings_value=settings.openai_api_key,
            )
            if not credential or credential.source != "secret_store":
                return provider

            return OpenAIWorkflowProvider(
                api_key=credential.value,
                credential_source=credential.source,
                credential_project_id=credential.project_id,
                api_key_secret_name=credential.secret_name,
            )

        if not isinstance(provider, DifyWorkflowProvider):
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
        if normalized == "github":
            credential = await resolve_provider_credential(
                db,
                project_id=demand.project_id,
                provider=normalized,
                secret_name=settings.github_token_secret_name,
                settings_value=settings.github_token,
            )
            return require_provider_credential(
                credential,
                provider=normalized,
                secret_name=settings.github_token_secret_name,
                settings_name="GITHUB_TOKEN",
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
        demand_title = title or self._derive_title(raw_input)
        enriched_context_payload = await self._context_payload_with_similar_demands(
            db=db,
            raw_input=raw_input,
            title=demand_title,
            project_id=project_id,
            context_payload=context_payload,
        )
        demand = await delivery_repository.create_demand(
            db=db,
            raw_input=raw_input,
            source_type=source_type,
            title=demand_title,
            requester_ref=requester_ref,
            context_payload=enriched_context_payload,
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

    async def get_observability_summary(
        self,
        db: AsyncSession,
        project_ids: list[int] | None = None,
    ) -> dict:
        sample_limit = max(1, min(settings.observability_alert_sample_limit, 20))
        now = utc_now()

        queued_count = await delivery_repository.count_execution_runs(
            db,
            statuses=["queued"],
            project_ids=project_ids,
        )
        running_count = await delivery_repository.count_execution_runs(
            db,
            statuses=["running"],
            project_ids=project_ids,
        )
        running_symphony = await delivery_repository.list_execution_runs(
            db,
            statuses=["running"],
            executor_types=["symphony"],
            limit=100,
            project_ids=project_ids,
        )
        expired_worker_runs = [
            run for run in running_symphony
            if self._symphony_lease_expired(run, now)
        ]

        failed_deploy_count = await delivery_repository.count_deploy_records(
            db,
            statuses=["failed"],
            project_ids=project_ids,
        )
        failed_deploys = await delivery_repository.list_deploy_records(
            db,
            statuses=["failed"],
            limit=sample_limit,
            project_ids=project_ids,
        )
        terminal_statuses = ["succeeded", "failed", "blocked", "cancelled"]
        failed_execution_statuses = ["failed", "blocked", "cancelled"]
        failure_rate_window_minutes = max(1, settings.observability_failure_rate_window_minutes)
        failure_rate_since = now - timedelta(minutes=failure_rate_window_minutes)
        recent_execution_count = await delivery_repository.count_execution_runs(
            db,
            statuses=terminal_statuses,
            project_ids=project_ids,
            updated_since=failure_rate_since,
        )
        recent_failed_execution_count = await delivery_repository.count_execution_runs(
            db,
            statuses=failed_execution_statuses,
            project_ids=project_ids,
            updated_since=failure_rate_since,
        )
        recent_failure_rate_percent = (
            int(round((recent_failed_execution_count / recent_execution_count) * 100))
            if recent_execution_count
            else 0
        )
        sensitive_scan_limit = min(max(sample_limit * 5, 20), 100)
        sensitive_scan_runs = await delivery_repository.list_execution_runs(
            db,
            limit=sensitive_scan_limit,
            project_ids=project_ids,
        )
        sensitive_evidence_runs = [
            run for run in sensitive_scan_runs
            if self._run_has_unredacted_sensitive_evidence(run)
        ]

        secrets = await secret_repository.list_secrets(
            db,
            project_ids=project_ids,
            limit=1000,
        )
        unhealthy_secrets = []
        unknown_secrets = []
        expiring_secrets = []
        secret_health_statuses: dict[int, str] = {}
        secret_health_reasons: dict[int, str] = {}
        for secret in secrets:
            health = secret_store_service.to_response(secret, verify_decrypt=False)
            secret_health_statuses[secret.id] = health.health_status
            if health.health_reason:
                secret_health_reasons[secret.id] = health.health_reason
            if health.health_status in {"expired", "invalid", "disabled"}:
                unhealthy_secrets.append(secret)
            elif health.health_status == "unknown":
                unknown_secrets.append(secret)
            elif health.health_status == "expiring_soon":
                expiring_secrets.append(secret)

        alerts = []
        if expired_worker_runs:
            alerts.append({
                "id": "worker-lease-expired",
                "category": "worker",
                "severity": "critical",
                "title": "Worker 心跳异常",
                "summary": f"{len(expired_worker_runs)} 个 Symphony 执行已超过 lease，需要检查 worker 或触发恢复。",
                "count": len(expired_worker_runs),
                "entity_type": "execution_run",
                "entity_ids": [run.id for run in expired_worker_runs[:sample_limit]],
            })

        if queued_count >= settings.observability_queue_backlog_threshold:
            queued_samples = await delivery_repository.list_execution_runs(
                db,
                statuses=["queued"],
                limit=sample_limit,
                project_ids=project_ids,
            )
            alerts.append({
                "id": "queue-backlog",
                "category": "queue",
                "severity": "warning",
                "title": "执行队列积压",
                "summary": (
                    f"当前有 {queued_count} 个执行排队，已达到阈值 "
                    f"{settings.observability_queue_backlog_threshold}。"
                ),
                "count": queued_count,
                "entity_type": "execution_run",
                "entity_ids": [run.id for run in queued_samples],
            })

        if unhealthy_secrets:
            alerts.append({
                "id": "secret-unhealthy",
                "category": "secret",
                "severity": "critical",
                "title": "凭证不可用",
                "summary": (
                    f"{len(unhealthy_secrets)} 个项目凭证已过期、禁用或不可用。"
                    f"{self._secret_health_breakdown(unhealthy_secrets, secret_health_statuses, secret_health_reasons)}"
                ),
                "count": len(unhealthy_secrets),
                "entity_type": "secret",
                "entity_ids": [secret.id for secret in unhealthy_secrets[:sample_limit]],
            })
        elif unknown_secrets:
            alerts.append({
                "id": "secret-health-unknown",
                "category": "secret",
                "severity": "warning",
                "title": "凭证健康状态未知",
                "summary": (
                    f"{len(unknown_secrets)} 个项目凭证远端可用性暂无法确认。"
                    f"{self._secret_health_breakdown(unknown_secrets, secret_health_statuses, secret_health_reasons)}"
                ),
                "count": len(unknown_secrets),
                "entity_type": "secret",
                "entity_ids": [secret.id for secret in unknown_secrets[:sample_limit]],
            })
        elif expiring_secrets:
            alerts.append({
                "id": "secret-expiring",
                "category": "secret",
                "severity": "warning",
                "title": "凭证即将过期",
                "summary": f"{len(expiring_secrets)} 个项目凭证将在近期过期。",
                "count": len(expiring_secrets),
                "entity_type": "secret",
                "entity_ids": [secret.id for secret in expiring_secrets[:sample_limit]],
            })

        if failed_deploy_count:
            alerts.append({
                "id": "deployment-failed",
                "category": "deployment",
                "severity": "critical",
                "title": "测试部署失败",
                "summary": f"{failed_deploy_count} 个测试部署处于失败状态，需要重新部署或检查部署系统。",
                "count": failed_deploy_count,
                "entity_type": "deployment",
                "entity_ids": [record.id for record in failed_deploys],
            })

        if (
            recent_execution_count >= settings.observability_failure_rate_min_runs
            and recent_failure_rate_percent >= settings.observability_failure_rate_threshold_percent
        ):
            failed_run_samples = await delivery_repository.list_execution_runs(
                db,
                statuses=failed_execution_statuses,
                limit=sample_limit,
                project_ids=project_ids,
                updated_since=failure_rate_since,
            )
            alerts.append({
                "id": "execution-failure-rate",
                "category": "execution",
                "severity": "critical",
                "title": "执行失败率异常",
                "summary": (
                    f"近 {failure_rate_window_minutes} 分钟 {recent_execution_count} 次执行中 "
                    f"{recent_failed_execution_count} 次失败，失败率 {recent_failure_rate_percent}%，"
                    f"已达到阈值 {settings.observability_failure_rate_threshold_percent}%。"
                ),
                "count": recent_failed_execution_count,
                "entity_type": "execution_run",
                "entity_ids": [run.id for run in failed_run_samples],
            })

        if sensitive_evidence_runs:
            alerts.append({
                "id": "sensitive-evidence-leak",
                "category": "secret",
                "severity": "critical",
                "title": "证据疑似包含明文凭证",
                "summary": (
                    f"最近扫描的 {len(sensitive_scan_runs)} 个执行中有 "
                    f"{len(sensitive_evidence_runs)} 个疑似包含未脱敏凭证，请检查执行日志和证据。"
                ),
                "count": len(sensitive_evidence_runs),
                "entity_type": "execution_run",
                "entity_ids": [run.id for run in sensitive_evidence_runs[:sample_limit]],
            })

        status_value = "healthy"
        if any(alert["severity"] == "critical" for alert in alerts):
            status_value = "critical"
        elif alerts:
            status_value = "warning"

        return {
            "generated_at": now,
            "status": status_value,
            "metrics": {
                "queued_runs": queued_count,
                "running_runs": running_count,
                "expired_worker_runs": len(expired_worker_runs),
                "failed_deployments": failed_deploy_count,
                "unhealthy_secrets": len(unhealthy_secrets),
                "invalid_secrets": sum(1 for status in secret_health_statuses.values() if status == "invalid"),
                "expired_secrets": sum(1 for status in secret_health_statuses.values() if status == "expired"),
                "disabled_secrets": sum(1 for status in secret_health_statuses.values() if status == "disabled"),
                "unknown_secrets": len(unknown_secrets),
                "expiring_secrets": len(expiring_secrets),
                "recent_execution_runs": recent_execution_count,
                "recent_failed_execution_runs": recent_failed_execution_count,
                "recent_execution_failure_rate_percent": recent_failure_rate_percent,
                "sensitive_evidence_runs": len(sensitive_evidence_runs),
            },
            "alerts": alerts,
        }

    async def get_project_observability_summaries(
        self,
        db: AsyncSession,
        project_ids: list[int] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        if project_ids is not None and not project_ids:
            return []

        if project_ids is None:
            projects = await auth_repository.list_projects(
                db,
                limit=min(max(limit, 1), 200),
                offset=max(offset, 0),
            )
        else:
            projects = []
            for project_id in project_ids:
                project = await auth_repository.get_project(db, project_id)
                if project:
                    projects.append(project)

        summaries = []
        for project in projects:
            summary = await self.get_observability_summary(db, project_ids=[project.id])
            alerts = summary["alerts"]
            summaries.append({
                "project_id": project.id,
                "project_key": project.key,
                "project_name": project.name,
                "status": summary["status"],
                "generated_at": summary["generated_at"],
                "alert_count": len(alerts),
                "critical_alerts": len([alert for alert in alerts if alert["severity"] == "critical"]),
                "warning_alerts": len([alert for alert in alerts if alert["severity"] == "warning"]),
                "metrics": summary["metrics"],
                "top_alerts": alerts[:3],
            })
        return summaries

    async def get_config_health(self, db: AsyncSession) -> dict:
        checks: list[dict[str, Any]] = []
        checks.append(await self._database_config_check(db))
        checks.extend(
            [
                self._workspace_config_check(),
                self._git_config_check(),
                self._codex_config_check(),
                self._secret_store_config_check(),
                self._workflow_provider_config_check(),
                self._merge_request_config_check(),
                self._deployment_config_check(),
                self._worker_script_config_check(),
            ]
        )

        status_value = "healthy"
        if any(check["status"] == "critical" for check in checks):
            status_value = "critical"
        elif any(check["status"] == "warning" for check in checks):
            status_value = "warning"

        return {
            "generated_at": utc_now(),
            "status": status_value,
            "checks": checks,
        }

    async def get_project_onboarding(self, db: AsyncSession, project_id: int) -> dict:
        project = await auth_repository.get_project(db, project_id)
        if not project:
            raise NotFoundException(f"Project {project_id} not found")

        secrets = await secret_repository.list_secrets(
            db,
            project_ids=[project_id],
            limit=100,
        )
        provider_names = sorted({secret.provider for secret in secrets if secret.status == "active"})
        unhealthy_secret_count = len(
            [
                secret for secret in secrets
                if secret_store_service.to_response(secret, verify_decrypt=False).health_status
                in {"expired", "invalid", "disabled"}
            ]
        )
        steps = [
            self._project_repository_onboarding_step(project),
            self._project_deployment_onboarding_step(project),
            self._project_secret_onboarding_step(provider_names, unhealthy_secret_count),
            self._project_workflow_provider_onboarding_step(provider_names),
            self._project_merge_request_onboarding_step(provider_names),
            self._project_execution_onboarding_step(),
            self._project_config_health_onboarding_step(await self.get_config_health(db)),
        ]

        status_value = "ready"
        if any(step["status"] == "blocked" for step in steps):
            status_value = "blocked"
        elif any(step["status"] == "warning" for step in steps):
            status_value = "needs_attention"

        done_count = len([step for step in steps if step["status"] == "done"])
        completion_percent = int(round((done_count / len(steps)) * 100)) if steps else 0

        return {
            "project_id": project.id,
            "project_key": project.key,
            "project_name": project.name,
            "generated_at": utc_now(),
            "status": status_value,
            "completion_percent": completion_percent,
            "steps": steps,
        }

    async def get_trace_detail(
        self,
        db: AsyncSession,
        trace_id: str,
        project_ids: list[int] | None = None,
    ) -> dict:
        normalized_trace_id = " ".join(trace_id.split())
        if not normalized_trace_id:
            raise BadRequestException("Trace id is required")

        demand = await delivery_repository.get_demand_by_trace_id(
            db,
            normalized_trace_id,
            project_ids=project_ids,
        )
        if not demand:
            raise NotFoundException(f"Trace {normalized_trace_id} not found")

        detail = await delivery_repository.get_demand_detail(db, demand.id)
        if not detail:
            raise NotFoundException(f"Trace {normalized_trace_id} not found")

        return self._trace_detail_payload(detail)

    def demand_next_actions(self, demand: DemandItem) -> list[dict]:
        latest_spec = self._latest_entity(demand.spec_cards)
        if not latest_spec:
            return [
                self._next_action(
                    "generate_spec",
                    "生成 Spec",
                    "根据需求生成规格、验收标准和风险边界。",
                    "POST",
                    f"/api/v2/demands/{demand.id}/spec",
                    capability="operate",
                )
            ]

        if latest_spec.status == SpecStatus.MANUAL_REVIEW and demand.manual_approval_status != "approved":
            return [
                self._next_action(
                    "approve_spec",
                    "人工确认 Spec",
                    "当前需求需要人工确认边界后才能继续自动执行。",
                    "POST",
                    f"/api/v2/demands/{demand.id}/manual-approval",
                    capability="review",
                    requires_human=True,
                    reason="spec_manual_review",
                )
            ]

        if latest_spec.status != SpecStatus.APPROVED:
            return [
                self._next_action(
                    "wait_for_spec",
                    "等待 Spec 完成",
                    "Spec 尚未达到 approved 状态，后续动作暂不应推进。",
                    capability="read",
                    priority="blocked",
                    reason=f"spec_status:{latest_spec.status}",
                )
            ]

        latest_repo_context = self._latest_entity(demand.repo_contexts)
        if not latest_repo_context or latest_repo_context.status != RepoContextStatus.READY:
            return [
                self._next_action(
                    "collect_repo_context",
                    "收集代码上下文",
                    "扫描仓库、文档、历史需求和依赖信息，形成实现范围依据。",
                    "POST",
                    f"/api/v2/demands/{demand.id}/repo-context",
                    capability="operate",
                )
            ]

        latest_impact = self._latest_entity(demand.impact_analyses)
        if not latest_impact:
            return [
                self._next_action(
                    "analyze_impact",
                    "生成影响分析",
                    "基于需求和仓库上下文推导影响范围、风险和建议检查项。",
                    "POST",
                    f"/api/v2/demands/{demand.id}/impact-analysis",
                    capability="operate",
                )
            ]
        if latest_impact.status == ImpactAnalysisStatus.MANUAL_REVIEW:
            return [
                self._next_action(
                    "review_impact",
                    "人工确认影响范围",
                    "影响分析要求人工复核，确认后再生成任务包。",
                    capability="review",
                    priority="blocked",
                    requires_human=True,
                    reason="impact_manual_review",
                )
            ]

        latest_task = self._latest_entity(demand.coding_tasks)
        if not latest_task:
            return [
                self._next_action(
                    "create_coding_task",
                    "生成任务包",
                    "生成 Codex 可执行的任务提示、允许路径和必跑检查。",
                    "POST",
                    f"/api/v2/spec-cards/{latest_spec.id}/coding-task",
                    capability="operate",
                )
            ]

        latest_run = self._latest_entity(latest_task.execution_runs)
        if not latest_run:
            return [
                self._next_action(
                    "create_execution_run",
                    "创建执行记录",
                    "为当前任务包创建一次受控执行 run。",
                    "POST",
                    f"/api/v2/coding-tasks/{latest_task.id}/runs",
                    capability="operate",
                )
            ]

        if latest_run.status == ExecutionRunStatus.QUEUED:
            return [
                self._next_action(
                    "dispatch_execution_run",
                    "执行任务",
                    "分发当前 queued run，由执行器完成代码修改和自测。",
                    "POST",
                    f"/api/v2/execution-runs/{latest_run.id}/dispatch",
                    capability="operate",
                )
            ]
        if latest_run.status == ExecutionRunStatus.PAUSED:
            return [
                self._next_action(
                    "resume_execution_run",
                    "恢复执行",
                    "当前 run 已暂停，恢复后再进入执行队列。",
                    "POST",
                    f"/api/v2/execution-runs/{latest_run.id}/resume",
                    capability="operate",
                )
            ]
        if latest_run.status == ExecutionRunStatus.RUNNING:
            return [
                self._next_action(
                    "wait_for_execution",
                    "等待执行完成",
                    "执行器仍在运行，等待结果或必要时人工暂停/取消。",
                    capability="read",
                    priority="secondary",
                    reason="execution_running",
                )
            ]
        if latest_run.status in {
            ExecutionRunStatus.FAILED,
            ExecutionRunStatus.BLOCKED,
            ExecutionRunStatus.CANCELLED,
        }:
            return [
                self._next_action(
                    "auto_repair_task",
                    "自动修复失败",
                    "根据失败证据生成受控修复 run。",
                    "POST",
                    f"/api/v2/coding-tasks/{latest_task.id}/auto-repair",
                    capability="operate",
                    reason=f"execution_status:{latest_run.status}",
                ),
                self._next_action(
                    "retry_task",
                    "重新执行任务",
                    "保留 retry chain 证据，重新创建一次执行 run。",
                    "POST",
                    f"/api/v2/coding-tasks/{latest_task.id}/retry",
                    capability="operate",
                    priority="secondary",
                    reason=f"execution_status:{latest_run.status}",
                ),
            ]

        if latest_run.status != ExecutionRunStatus.SUCCEEDED:
            return [
                self._next_action(
                    "wait_for_execution_result",
                    "等待执行结果",
                    "执行 run 尚未进入可交付状态。",
                    capability="read",
                    priority="blocked",
                    reason=f"execution_status:{latest_run.status}",
                )
            ]

        latest_merge_request = self._latest_entity(latest_task.merge_requests)
        if not latest_merge_request:
            return [
                self._next_action(
                    "create_merge_request",
                    "创建 MR/PR",
                    "将已通过自测的变更创建或登记为 MR/PR。",
                    "POST",
                    f"/api/v2/coding-tasks/{latest_task.id}/merge-request",
                    capability="operate",
                )
            ]

        if (
            latest_merge_request.review_status == ReviewStatus.BLOCKING
            or latest_merge_request.status == MergeRequestStatus.REVIEW_BLOCKED
        ):
            return [
                self._next_action(
                    "repair_merge_request",
                    "修复评审阻塞",
                    "根据 MR/PR 阻塞意见创建修复 run，并推回原源分支。",
                    "POST",
                    f"/api/v2/merge-requests/{latest_merge_request.id}/auto-repair",
                    capability="operate",
                    reason="review_blocking",
                )
            ]

        if latest_merge_request.review_status != ReviewStatus.PASSED:
            if latest_merge_request.provider == "local":
                return [
                    self._next_action(
                        "record_local_review",
                        "记录本地评审",
                        "本地 MR 需要记录评审通过或阻塞结果。",
                        "POST",
                        f"/api/v2/merge-requests/{latest_merge_request.id}/review",
                        capability="review",
                        requires_human=True,
                    )
                ]
            return [
                self._next_action(
                    "sync_remote_review",
                    "同步远端评审",
                    "从 GitLab/GitHub 拉取评审和 CI/check 状态并更新门禁。",
                    "POST",
                    f"/api/v2/merge-requests/{latest_merge_request.id}/sync-review",
                    capability="operate",
                )
            ]

        latest_deploy = self._latest_entity(latest_merge_request.deploy_records)
        if not latest_deploy:
            return [
                self._next_action(
                    "create_deployment",
                    "部署测试环境",
                    "将已评审通过的 MR/PR 部署到测试环境并记录证据。",
                    "POST",
                    f"/api/v2/merge-requests/{latest_merge_request.id}/deployments",
                    capability="operate",
                )
            ]

        if latest_deploy.status == DeploymentStatus.PENDING:
            return [
                self._next_action(
                    "sync_deployment",
                    "同步部署状态",
                    "拉取测试环境部署状态并回写部署门禁。",
                    "POST",
                    f"/api/v2/deployments/{latest_deploy.id}/sync-status",
                    capability="operate",
                )
            ]
        if latest_deploy.status == DeploymentStatus.FAILED:
            return [
                self._next_action(
                    "redeploy",
                    "重新部署",
                    "基于失败部署记录创建新的测试环境部署。",
                    "POST",
                    f"/api/v2/deployments/{latest_deploy.id}/redeploy",
                    capability="operate",
                    reason="deployment_failed",
                )
            ]

        latest_verification = self._latest_entity(latest_deploy.verification_records)
        if not latest_verification:
            return [
                self._next_action(
                    "record_verification",
                    "记录验收",
                    "记录测试环境人工或自动验收结果。",
                    "POST",
                    f"/api/v2/deployments/{latest_deploy.id}/verification",
                    capability="review",
                    requires_human=True,
                )
            ]
        if latest_verification.status == VerificationStatus.FAILED:
            return [
                self._next_action(
                    "redeploy_after_failed_verification",
                    "验收失败后重新部署",
                    "验收失败，需要修复或重新部署后再次验证。",
                    "POST",
                    f"/api/v2/deployments/{latest_deploy.id}/redeploy",
                    capability="operate",
                    reason="verification_failed",
                )
            ]

        return [
            self._next_action(
                "delivery_completed",
                "交付已完成",
                "需求已完成测试环境验收，等待人工决定是否合并或发布。",
                capability="read",
                priority="done",
            )
        ]

    async def get_project_deployment_environment_config(
        self,
        db: AsyncSession,
        project_id: int,
    ) -> dict:
        project = await auth_repository.get_project(db, project_id)
        if not project:
            raise NotFoundException(f"Project {project_id} not found")
        return {
            "project_id": project.id,
            "environments": self._project_deployment_environments(project.settings_json),
        }

    async def update_project_deployment_environment_config(
        self,
        db: AsyncSession,
        project_id: int,
        environments: dict,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> dict:
        project = await auth_repository.get_project(db, project_id)
        if not project:
            raise NotFoundException(f"Project {project_id} not found")

        normalized_environments = self._normalize_deployment_environment_config(environments)
        settings_json = dict(project.settings_json or {})
        delivery_settings = settings_json.get("delivery")
        if delivery_settings is None:
            delivery_settings = {}
        if not isinstance(delivery_settings, dict):
            raise BadRequestException("Project delivery settings must be a JSON object")
        delivery_settings = dict(delivery_settings)
        delivery_settings["deployment_environments"] = normalized_environments
        settings_json["delivery"] = delivery_settings

        await auth_repository.update_project(db, project, settings_json=settings_json)
        await audit_repository.create_event(
            db,
            action="delivery.project_deployment_environments_updated",
            entity_type="project",
            entity_id=project.id,
            project_id=project.id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=f"Project deployment environments updated: {project.name}",
            metadata={"environments": sorted(normalized_environments.keys())},
        )
        await db.commit()

        loaded_project = await auth_repository.get_project(db, project.id)
        if not loaded_project:
            raise NotFoundException(f"Project {project_id} not found")
        return {
            "project_id": loaded_project.id,
            "environments": self._project_deployment_environments(loaded_project.settings_json),
        }

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
        draft, provider = await self._run_provider_operation(
            operation="generate_spec",
            provider=provider,
            call=lambda selected_provider: selected_provider.generate_spec(demand),
        )
        draft = self._annotate_provider_draft(
            draft,
            {
                "quality_evaluation": evaluate_spec_draft(
                    draft,
                    settings.ai_workflow_provider_quality_min_score,
                )
            },
        )
        provider_metadata = draft.provider_metadata or {}
        open_questions = self._merge_open_questions(
            draft.open_questions,
            risk_level,
            confidence_score,
        )
        if self._provider_fallback_used(provider_metadata):
            open_questions = self._dedupe(
                [
                    "External AI provider failed; local rule fallback was used. Review provider recovery evidence before relying on this draft.",
                    *open_questions,
                ]
            )

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
            open_questions=open_questions,
            provider_metadata=provider_metadata,
        )

        demand.risk_level = risk_level
        demand.confidence_score = confidence_score
        demand.status = (
            DemandStatus.SPEC_APPROVED
            if spec_status == SpecStatus.APPROVED
            else DemandStatus.SPEC_MANUAL_REQUIRED
        )

        spec_ready_gate = self.gates.evaluate_spec_ready(
            spec_card_id=spec.id,
            user_story=spec.user_story,
            scope=spec.scope,
            acceptance_criteria=spec.acceptance_criteria_json,
            constraints=spec.constraints_json,
            risks=spec.risks_json,
        )
        await self._record_gate(
            db,
            demand.id,
            self._with_provider_evidence(spec_ready_gate, provider_metadata),
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
        draft, provider = await self._run_provider_operation(
            operation="analyze_impact",
            provider=provider,
            call=lambda selected_provider: selected_provider.analyze_impact(
                demand,
                spec,
                repo_context,
            ),
        )
        draft = self._annotate_provider_draft(
            draft,
            {
                "quality_evaluation": evaluate_impact_draft(
                    draft,
                    settings.ai_workflow_provider_quality_min_score,
                )
            },
        )
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
                "provider_metadata": redact_value(analysis.provider_metadata_json or {}),
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

        retry_context = self._build_retry_context(task)
        queued_run = await self.create_execution_run(
            db=db,
            coding_task_id=coding_task_id,
            executor_type=executor_type,
            trigger_mode=trigger_mode,
            extra_evidence={"retry_context": retry_context} if retry_context else None,
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

    async def auto_repair_merge_request_review(
        self,
        db: AsyncSession,
        merge_request_id: int,
        executor_type: str = "codex",
        max_attempts: int | None = None,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> list[ExecutionRun]:
        record = await delivery_repository.get_merge_request_record(db, merge_request_id)
        if not record:
            raise NotFoundException(f"Merge request record {merge_request_id} not found")

        task = await delivery_repository.get_coding_task(db, record.coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {record.coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        if record.review_status != ReviewStatus.BLOCKING and record.status != MergeRequestStatus.REVIEW_BLOCKED:
            raise BadRequestException("Merge request review repair requires blocking review status")
        if demand.risk_level in {DeliveryRiskLevel.L2, DeliveryRiskLevel.L3}:
            raise BadRequestException("Automatic review repair is blocked for L2/L3 risk tasks")
        if task.status == CodingTaskStatus.RUNNING:
            raise BadRequestException(f"Coding task {task.id} is already running")
        if task.status == CodingTaskStatus.DRAFT:
            raise BadRequestException(f"Coding task {task.id} is not ready for review repair")

        source_run = self._merge_request_source_run(record, task)
        if not source_run:
            raise BadRequestException("Merge request review repair requires the source execution run")
        review_issues = self._merge_request_review_issues(record)
        if not review_issues:
            raise BadRequestException("Merge request review repair requires blocking review evidence")

        attempts_limit = max_attempts or settings.execution_auto_repair_max_attempts
        attempts_limit = min(max(attempts_limit, 1), 3)
        repair_runs: list[ExecutionRun] = []
        current_failure: ExecutionRun | None = None

        for attempt in range(1, attempts_limit + 1):
            if task.status in {CodingTaskStatus.BLOCKED, CodingTaskStatus.COMPLETED}:
                await delivery_repository.update_coding_task_status(db, task, CodingTaskStatus.READY)
                await db.commit()

            if current_failure and self._has_failed_check_evidence(current_failure):
                repair_context = self._build_repair_context(
                    source_run=current_failure,
                    attempt=attempt,
                    max_attempts=attempts_limit,
                )
            else:
                repair_context = self._build_review_repair_context(
                    record=record,
                    source_run=source_run,
                    review_issues=review_issues,
                    attempt=attempt,
                    max_attempts=attempts_limit,
                )

            queued_run = await self.create_execution_run(
                db=db,
                coding_task_id=task.id,
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
                push_evidence = await self._push_repair_run_to_merge_request(
                    provider=record.provider,
                    record=record,
                    run=repaired_run,
                )
                await self._mark_merge_request_repair_pushed(
                    db=db,
                    record=record,
                    repaired_run=repaired_run,
                    push_evidence=push_evidence,
                    project_id=demand.project_id,
                    actor_user_id=actor_user_id,
                    actor_ref=actor_ref,
                )
                break
            if self._has_changed_file_violations(repaired_run) or not self._has_failed_check_evidence(repaired_run):
                break
            current_failure = repaired_run

        await audit_repository.create_event(
            db,
            action="delivery.merge_request_review_repair_started",
            entity_type="merge_request",
            entity_id=record.id,
            project_id=demand.project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=f"Merge request review repair started: {len(repair_runs)} run(s)",
            metadata={
                "coding_task_id": task.id,
                "merge_request_id": record.id,
                "execution_run_ids": [run.id for run in repair_runs],
                "review_issue_count": len(review_issues),
            },
        )
        await db.commit()
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
        evidence_links = self._merge_request_evidence_links(demand=demand, task=task, run=run)
        description = self._build_merge_request_description(
            demand=demand,
            task=task,
            run=run,
            source_branch=source_branch,
            target_branch=resolved_target_branch,
            evidence_links=evidence_links,
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
            "evidence_links": evidence_links,
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

    async def handle_gitlab_webhook(
        self,
        db: AsyncSession,
        payload: dict,
        token: str | None,
    ) -> dict:
        expected_token = settings.gitlab_webhook_secret_token.strip()
        if not expected_token:
            raise BadRequestException("GitLab webhook is not configured: GITLAB_WEBHOOK_SECRET_TOKEN")
        if not token or not hmac.compare_digest(token, expected_token):
            raise BadRequestException("Invalid GitLab webhook token")
        if not isinstance(payload, dict):
            raise BadRequestException("GitLab webhook payload must be a JSON object")

        iid = self._gitlab_webhook_iid(payload)
        object_kind = self._str_value(payload.get("object_kind")) or self._str_value(payload.get("event_type"))
        if not iid:
            return {
                "processed": False,
                "reason": "merge_request_iid_not_found",
                "object_kind": object_kind,
            }

        record = await delivery_repository.get_merge_request_by_provider_external_id(db, "gitlab", iid)
        if not record:
            return {
                "processed": False,
                "reason": "merge_request_record_not_found",
                "object_kind": object_kind,
                "external_id": iid,
            }

        task = await delivery_repository.get_coding_task(db, record.coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {record.coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        update = self._gitlab_webhook_review_update(payload)
        reviewed_at = utc_now()
        review_status_value = self._enum_or_str(update["review_status"])
        status_value = self._enum_or_str(update["status"])
        summary = redact_text(update["summary"])
        comments = redact_value(update["comments"])
        blockers = [redact_text(item) for item in update["blocking_issues"]]
        webhook_event = redact_value(update["event"])
        existing_evidence = record.evidence_json or {}
        if not isinstance(existing_evidence, dict):
            existing_evidence = {}
        gitlab_webhook_evidence = (
            existing_evidence.get("gitlab_webhook") if isinstance(existing_evidence, dict) else {}
        )
        if not isinstance(gitlab_webhook_evidence, dict):
            gitlab_webhook_evidence = {}
        events = gitlab_webhook_evidence.get("events")
        if not isinstance(events, list):
            events = []
        events = [*events, webhook_event][-20:]
        evidence = {
            **existing_evidence,
            "gitlab_webhook": {
                "last_event": webhook_event,
                "events": events,
            },
            "remote_review_synced_at": reviewed_at.isoformat(),
            "remote_review_synced_by_ref": "gitlab-webhook",
        }
        existing_comments = record.review_comments_json or []
        merged_comments = [*existing_comments, *comments][-50:] if comments else existing_comments

        await delivery_repository.update_merge_request_record(
            db,
            record,
            status=status_value,
            review_status=review_status_value,
            review_summary=summary,
            review_comments_json=merged_comments,
            evidence_json=evidence,
            reviewed_by_ref="gitlab-webhook",
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
                "gitlab_webhook": webhook_event,
            },
        )
        await audit_repository.create_event(
            db,
            action="delivery.merge_request_gitlab_webhook_received",
            entity_type="merge_request",
            entity_id=record.id,
            project_id=demand.project_id,
            actor_ref="gitlab-webhook",
            summary=summary,
            metadata={
                "review_status": review_status_value,
                "provider": record.provider,
                "object_kind": object_kind,
                "external_id": iid,
            },
        )
        await db.commit()
        loaded_record = await delivery_repository.get_merge_request_record(db, record.id)
        if not loaded_record:
            raise NotFoundException(f"Merge request record {record.id} not found")
        return {
            "processed": True,
            "reason": "updated",
            "object_kind": object_kind,
            "external_id": iid,
            "merge_request": loaded_record,
        }

    async def handle_github_webhook(
        self,
        db: AsyncSession,
        payload: dict,
        signature: str | None,
        event_type: str | None,
        body: bytes,
    ) -> dict:
        expected_secret = settings.github_webhook_secret.strip()
        if not expected_secret:
            raise BadRequestException("GitHub webhook is not configured: GITHUB_WEBHOOK_SECRET")
        if not signature or not self._github_webhook_signature_valid(signature, body, expected_secret):
            raise BadRequestException("Invalid GitHub webhook signature")
        if not isinstance(payload, dict):
            raise BadRequestException("GitHub webhook payload must be a JSON object")

        normalized_event_type = self._str_value(event_type) or self._str_value(payload.get("event_type")) or "unknown"
        number = self._github_webhook_number(payload)
        if not number:
            return {
                "processed": False,
                "reason": "pull_request_number_not_found",
                "event_type": normalized_event_type,
            }

        record = await delivery_repository.get_merge_request_by_provider_external_id(db, "github", number)
        if not record:
            return {
                "processed": False,
                "reason": "pull_request_record_not_found",
                "event_type": normalized_event_type,
                "external_id": number,
            }

        task = await delivery_repository.get_coding_task(db, record.coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {record.coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        update = self._github_webhook_review_update(payload, normalized_event_type)
        reviewed_at = utc_now()
        review_status_value = self._enum_or_str(update["review_status"])
        status_value = self._enum_or_str(update["status"])
        summary = redact_text(update["summary"])
        comments = redact_value(update["comments"])
        blockers = [redact_text(item) for item in update["blocking_issues"]]
        webhook_event = redact_value(update["event"])
        existing_evidence = record.evidence_json or {}
        if not isinstance(existing_evidence, dict):
            existing_evidence = {}
        github_webhook_evidence = existing_evidence.get("github_webhook")
        if not isinstance(github_webhook_evidence, dict):
            github_webhook_evidence = {}
        events = github_webhook_evidence.get("events")
        if not isinstance(events, list):
            events = []
        events = [*events, webhook_event][-20:]
        evidence = {
            **existing_evidence,
            "github_webhook": {
                "last_event": webhook_event,
                "events": events,
            },
            "remote_review_synced_at": reviewed_at.isoformat(),
            "remote_review_synced_by_ref": "github-webhook",
        }
        existing_comments = record.review_comments_json or []
        merged_comments = [*existing_comments, *comments][-50:] if comments else existing_comments

        await delivery_repository.update_merge_request_record(
            db,
            record,
            status=status_value,
            review_status=review_status_value,
            review_summary=summary,
            review_comments_json=merged_comments,
            evidence_json=evidence,
            reviewed_by_ref="github-webhook",
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
                "github_webhook": webhook_event,
            },
        )
        await audit_repository.create_event(
            db,
            action="delivery.merge_request_github_webhook_received",
            entity_type="merge_request",
            entity_id=record.id,
            project_id=demand.project_id,
            actor_ref="github-webhook",
            summary=summary,
            metadata={
                "review_status": review_status_value,
                "provider": record.provider,
                "event_type": normalized_event_type,
                "external_id": number,
            },
        )
        await db.commit()
        loaded_record = await delivery_repository.get_merge_request_record(db, record.id)
        if not loaded_record:
            raise NotFoundException(f"Merge request record {record.id} not found")
        return {
            "processed": True,
            "reason": "updated",
            "event_type": normalized_event_type,
            "external_id": number,
            "merge_request": loaded_record,
        }

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

        project_settings = None
        if demand.project_id is not None:
            project = await auth_repository.get_project(db, demand.project_id)
            if not project:
                raise NotFoundException(f"Project {demand.project_id} not found")
            project_settings = project.settings_json

        configured_url, environment_config = self._deployment_environment_settings(
            environment,
            project_settings=project_settings,
        )
        requested_url = url or configured_url
        credential = await self._deployment_credential_for_provider(db, demand, provider)
        client = get_deploy_client(provider, credential=credential)
        draft = await client.create_deployment(
            task=task,
            merge_request=merge_request,
            environment=environment,
            url=requested_url,
        )
        status = self._enum_or_str(draft.status)
        provider_evidence = redact_value(draft.evidence)
        deployment_logs = self._deployment_log_evidence(provider_evidence, environment_config)
        evidence = {
            "merge_request_id": merge_request.id,
            "coding_task_id": task.id,
            "environment": environment,
            "deployment_config": environment_config,
            "provider": draft.provider,
            "created_by_user_id": actor_user_id,
            "created_by_ref": actor_ref or "system",
            "provider_evidence": provider_evidence,
        }
        if deployment_logs:
            evidence["deployment_logs"] = deployment_logs
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
            status=self._deployment_gate_status(status),
            reason=self._deployment_gate_reason(status),
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

    async def redeploy_deploy_record(
        self,
        db: AsyncSession,
        deploy_record_id: int,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> DeployRecord:
        source_record = await delivery_repository.get_deploy_record(db, deploy_record_id)
        if not source_record:
            raise NotFoundException(f"Deploy record {deploy_record_id} not found")
        if source_record.status == DeploymentStatus.PENDING:
            raise BadRequestException("Pending deployment must be synced or completed before redeploying")

        redeployed = await self.create_deploy_record(
            db=db,
            merge_request_id=source_record.merge_request_id,
            provider=source_record.provider,
            environment=source_record.environment,
            url=None,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref,
        )
        evidence = {
            **(redeployed.evidence_json or {}),
            "redeploy_from_deploy_record_id": source_record.id,
            "redeployed_by_user_id": actor_user_id,
            "redeployed_by_ref": actor_ref or "system",
            "redeployed_at": utc_now().isoformat(),
        }
        await delivery_repository.update_deploy_record(
            db,
            redeployed,
            evidence_json=evidence,
        )

        task = await delivery_repository.get_coding_task(db, redeployed.coding_task_id)
        demand = await delivery_repository.get_demand(db, task.demand_id) if task else None
        await audit_repository.create_event(
            db,
            action="delivery.test_deployment_redeployed",
            entity_type="deployment",
            entity_id=redeployed.id,
            project_id=demand.project_id if demand else None,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=f"Test deployment redeployed: {redeployed.environment}",
            metadata={
                "source_deploy_record_id": source_record.id,
                "new_deploy_record_id": redeployed.id,
                "merge_request_id": redeployed.merge_request_id,
                "provider": redeployed.provider,
                "environment": redeployed.environment,
            },
        )
        await db.commit()
        loaded_record = await delivery_repository.get_deploy_record(db, redeployed.id)
        if not loaded_record:
            raise NotFoundException(f"Deploy record {redeployed.id} not found")
        return loaded_record

    async def sync_deploy_record_status(
        self,
        db: AsyncSession,
        deploy_record_id: int,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> DeployRecord:
        deploy_record = await delivery_repository.get_deploy_record(db, deploy_record_id)
        if not deploy_record:
            raise NotFoundException(f"Deploy record {deploy_record_id} not found")
        merge_request = await delivery_repository.get_merge_request_record(db, deploy_record.merge_request_id)
        if not merge_request:
            raise NotFoundException(f"Merge request record {deploy_record.merge_request_id} not found")
        task = await delivery_repository.get_coding_task(db, deploy_record.coding_task_id)
        if not task:
            raise NotFoundException(f"Coding task {deploy_record.coding_task_id} not found")
        demand = await delivery_repository.get_demand(db, task.demand_id)
        if not demand:
            raise NotFoundException(f"Demand {task.demand_id} not found")

        credential = await self._deployment_credential_for_provider(db, demand, deploy_record.provider)
        client = get_deploy_client(deploy_record.provider, credential=credential)
        remote_status = await client.fetch_deployment_status(deploy_record=deploy_record)
        status = self._enum_or_str(remote_status.status)
        remote_evidence = redact_value(remote_status.evidence)
        evidence = {
            **(deploy_record.evidence_json or {}),
            "remote_status": remote_evidence,
            "remote_status_synced_by_user_id": actor_user_id,
            "remote_status_synced_by_ref": actor_ref or "system",
            "remote_status_synced_at": utc_now().isoformat(),
        }
        deployment_logs = self._deployment_log_evidence(
            remote_evidence,
            evidence.get("deployment_config") if isinstance(evidence.get("deployment_config"), dict) else {},
        )
        if deployment_logs:
            evidence["deployment_logs"] = deployment_logs
        await delivery_repository.update_deploy_record(
            db,
            deploy_record,
            status=status,
            url=remote_status.url or deploy_record.url,
            evidence_json=evidence,
        )
        await delivery_repository.create_gate_check(
            db=db,
            demand_id=demand.id,
            gate_type=GateType.TEST_DEPLOYED,
            status=self._deployment_gate_status(status),
            reason=remote_status.summary or self._deployment_gate_reason(status),
            evidence_json={
                "deploy_record_id": deploy_record.id,
                "merge_request_id": merge_request.id,
                "environment": deploy_record.environment,
                "url": deploy_record.url,
                "remote_status": remote_evidence,
            },
        )
        await audit_repository.create_event(
            db,
            action="delivery.test_deployment_status_synced",
            entity_type="deployment",
            entity_id=deploy_record.id,
            project_id=demand.project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary=remote_status.summary or f"Test deployment status synced: {status}",
            metadata={
                "status": status,
                "merge_request_id": merge_request.id,
                "environment": deploy_record.environment,
            },
        )
        await db.commit()
        loaded_record = await delivery_repository.get_deploy_record(db, deploy_record.id)
        if not loaded_record:
            raise NotFoundException(f"Deploy record {deploy_record.id} not found")
        return loaded_record

    async def sync_pending_deploy_records(
        self,
        db: AsyncSession,
        *,
        limit: int = 20,
        project_ids: list[int] | None = None,
        actor_user_id: int | None = None,
        actor_ref: str | None = None,
    ) -> dict:
        records = await delivery_repository.list_deploy_records(
            db,
            statuses=[DeploymentStatus.PENDING],
            limit=min(max(limit, 1), 100),
            project_ids=project_ids,
        )
        synced: list[DeployRecord] = []
        errors: list[dict] = []
        for record in records:
            try:
                synced.append(
                    await self.sync_deploy_record_status(
                        db,
                        record.id,
                        actor_user_id=actor_user_id,
                        actor_ref=actor_ref or "system",
                    )
                )
            except (BadRequestException, NotFoundException) as exc:
                errors.append(
                    {
                        "deploy_record_id": record.id,
                        "provider": record.provider,
                        "error_type": exc.__class__.__name__,
                        "message": redact_text(str(exc))[:1000],
                    }
                )
        return {
            "scanned": len(records),
            "synced_count": len(synced),
            "error_count": len(errors),
            "synced": synced,
            "errors": errors,
        }

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

    def _trace_detail_payload(self, demand: DemandItem) -> dict:
        timeline: list[dict[str, Any]] = [
            self._trace_event(
                at=demand.created_at,
                stage="demand",
                entity_type="demand",
                entity_id=demand.id,
                status=demand.status,
                title=demand.title,
                summary=demand.raw_input,
                metadata={
                    "source_type": demand.source_type,
                    "requester_ref": demand.requester_ref,
                    "manual_approval_status": demand.manual_approval_status,
                },
            )
        ]

        for spec in demand.spec_cards:
            timeline.append(
                self._trace_event(
                    at=spec.created_at,
                    stage="spec",
                    entity_type="spec_card",
                    entity_id=spec.id,
                    status=spec.status,
                    title=spec.title,
                    summary=spec.scope,
                    metadata={
                        "created_by": spec.created_by,
                        "acceptance_criteria": spec.acceptance_criteria_json,
                        "open_questions": spec.open_questions_json,
                    },
                )
            )

        for gate in demand.gate_checks:
            timeline.append(
                self._trace_event(
                    at=gate.created_at,
                    stage="gate",
                    entity_type="gate_check",
                    entity_id=gate.id,
                    status=gate.status,
                    title=gate.gate_type,
                    summary=gate.reason,
                    metadata={"evidence": gate.evidence_json or {}},
                )
            )

        for repo_context in demand.repo_contexts:
            timeline.append(
                self._trace_event(
                    at=repo_context.created_at,
                    stage="context",
                    entity_type="repo_context",
                    entity_id=repo_context.id,
                    status=repo_context.status,
                    title=repo_context.provider,
                    summary=repo_context.summary,
                    metadata={
                        "confidence_score": repo_context.confidence_score,
                        "source_refs": repo_context.source_refs_json[:20],
                        "discovered_files": repo_context.discovered_files_json[:40],
                        "dependency_refs": repo_context.dependency_refs_json[:20],
                        "provider_metadata": repo_context.provider_metadata_json or {},
                    },
                )
            )

        for impact in demand.impact_analyses:
            timeline.append(
                self._trace_event(
                    at=impact.created_at,
                    stage="impact",
                    entity_type="impact_analysis",
                    entity_id=impact.id,
                    status=impact.status,
                    title=impact.provider,
                    summary=impact.summary,
                    metadata={
                        "repo_context_id": impact.repo_context_id,
                        "risk_level": impact.risk_level,
                        "confidence_score": impact.confidence_score,
                        "impacted_areas": impact.impacted_areas_json,
                        "affected_files": impact.affected_files_json,
                        "recommendations": impact.recommendations_json,
                    },
                )
            )

        for task in demand.coding_tasks:
            timeline.append(
                self._trace_event(
                    at=task.created_at,
                    stage="task",
                    entity_type="coding_task",
                    entity_id=task.id,
                    status=task.status,
                    title=task.title,
                    summary=task.task_prompt,
                    metadata={
                        "spec_card_id": task.spec_card_id,
                        "allowed_paths": task.allowed_paths_json,
                        "forbidden_actions": task.forbidden_actions_json,
                        "required_checks": task.required_checks_json,
                        "expected_evidence": task.expected_evidence_json,
                    },
                )
            )
            for run in task.execution_runs:
                timeline.append(
                    self._trace_event(
                        at=run.created_at,
                        stage="execution",
                        entity_type="execution_run",
                        entity_id=run.id,
                        status=run.status,
                        title=run.executor_type,
                        summary=run.result_summary,
                        metadata={
                            "trigger_mode": run.trigger_mode,
                            "worktree_path": run.worktree_path,
                            "branch_name": run.branch_name,
                            "commit_sha": run.commit_sha,
                            "started_at": run.started_at.isoformat() if run.started_at else None,
                            "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                            "evidence": run.evidence_json or {},
                        },
                    )
                )
                for log in run.logs:
                    timeline.append(
                        self._trace_event(
                            at=log.created_at,
                            stage="execution_log",
                            entity_type="execution_log",
                            entity_id=log.id,
                            status=log.level,
                            title=f"run #{run.id}",
                            summary=log.message,
                            metadata={"event": log.event_json or {}},
                        )
                    )

            for record in task.merge_requests:
                timeline.append(
                    self._trace_event(
                        at=record.created_at,
                        stage="merge_request",
                        entity_type="merge_request",
                        entity_id=record.id,
                        status=record.status,
                        title=record.title,
                        summary=record.review_summary,
                        metadata={
                            "provider": record.provider,
                            "review_status": record.review_status,
                            "source_branch": record.source_branch,
                            "target_branch": record.target_branch,
                            "external_id": record.external_id,
                            "url": record.url,
                            "review_comments": record.review_comments_json,
                            "evidence": record.evidence_json or {},
                        },
                    )
                )
                for deploy_record in record.deploy_records:
                    timeline.append(
                        self._trace_event(
                            at=deploy_record.created_at,
                            stage="deployment",
                            entity_type="deploy_record",
                            entity_id=deploy_record.id,
                            status=deploy_record.status,
                            title=deploy_record.environment,
                            summary=deploy_record.url,
                            metadata={
                                "provider": deploy_record.provider,
                                "merge_request_id": deploy_record.merge_request_id,
                                "coding_task_id": deploy_record.coding_task_id,
                                "created_by_ref": deploy_record.created_by_ref,
                                "evidence": deploy_record.evidence_json or {},
                            },
                        )
                    )
                    for verification in deploy_record.verification_records:
                        timeline.append(
                            self._trace_event(
                                at=verification.created_at,
                                stage="verification",
                                entity_type="verification_record",
                                entity_id=verification.id,
                                status=verification.status,
                                title=verification.verifier_ref,
                                summary=verification.summary,
                                metadata={
                                    "evidence_links": verification.evidence_links_json,
                                    "evidence": verification.evidence_json or {},
                                },
                            )
                        )

        timeline.sort(
            key=lambda item: (
                item["at"] or datetime.min.replace(tzinfo=timezone.utc),
                self._trace_stage_order(item["stage"]),
                item["entity_id"],
            )
        )

        counts = {
            "spec_cards": len(demand.spec_cards),
            "gate_checks": len(demand.gate_checks),
            "repo_contexts": len(demand.repo_contexts),
            "impact_analyses": len(demand.impact_analyses),
            "coding_tasks": len(demand.coding_tasks),
            "execution_runs": sum(len(task.execution_runs) for task in demand.coding_tasks),
            "execution_logs": sum(
                len(run.logs)
                for task in demand.coding_tasks
                for run in task.execution_runs
            ),
            "merge_requests": sum(len(task.merge_requests) for task in demand.coding_tasks),
            "deployments": sum(
                len(record.deploy_records)
                for task in demand.coding_tasks
                for record in task.merge_requests
            ),
            "verifications": sum(
                len(deploy_record.verification_records)
                for task in demand.coding_tasks
                for record in task.merge_requests
                for deploy_record in record.deploy_records
            ),
            "timeline_events": len(timeline),
        }

        return {
            "trace_id": demand.trace_id,
            "project_id": demand.project_id,
            "demand_id": demand.id,
            "demand_title": demand.title,
            "current_status": demand.status,
            "risk_level": demand.risk_level,
            "counts": counts,
            "timeline": timeline,
        }

    def _trace_event(
        self,
        *,
        at: datetime | None,
        stage: str,
        entity_type: str,
        entity_id: int,
        status: str | None = None,
        title: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_metadata = redact_value(metadata or {})
        return {
            "at": at,
            "stage": stage,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "status": status,
            "title": redact_text(title) if title else None,
            "summary": redact_text(summary)[:1200] if summary else None,
            "metadata": safe_metadata if isinstance(safe_metadata, dict) else {"value": safe_metadata},
        }

    def _trace_stage_order(self, stage: str) -> int:
        order = {
            "demand": 10,
            "spec": 20,
            "gate": 30,
            "context": 40,
            "impact": 50,
            "task": 60,
            "execution": 70,
            "execution_log": 80,
            "merge_request": 90,
            "deployment": 100,
            "verification": 110,
        }
        return order.get(stage, 999)

    def _latest_entity(self, items: list) -> Any | None:
        if not items:
            return None
        return sorted(
            items,
            key=lambda item: (
                getattr(item, "updated_at", None)
                or getattr(item, "created_at", None)
                or datetime.min.replace(tzinfo=timezone.utc),
                getattr(item, "id", 0),
            ),
            reverse=True,
        )[0]

    def _next_action(
        self,
        action_id: str,
        label: str,
        description: str,
        method: str | None = None,
        endpoint: str | None = None,
        *,
        capability: str = "read",
        priority: str = "primary",
        requires_human: bool = False,
        reason: str | None = None,
    ) -> dict:
        return {
            "id": action_id,
            "label": label,
            "description": description,
            "method": method,
            "endpoint": endpoint,
            "capability": capability,
            "priority": priority,
            "requires_human": requires_human,
            "reason": reason,
        }

    async def _database_config_check(self, db: AsyncSession) -> dict[str, Any]:
        try:
            await db.execute(text("SELECT 1"))
        except Exception as exc:  # pragma: no cover - defensive path depends on database failure mode
            return self._config_check(
                "database",
                "database",
                "critical",
                "Database connection failed",
                "Backend cannot query the configured database.",
                evidence={
                    "database_url_scheme": settings.database_url.split(":", 1)[0],
                    "error": redact_text(str(exc))[:500],
                },
                next_action="Verify DATABASE_URL and run database migration before operating delivery tasks.",
            )

        return self._config_check(
            "database",
            "database",
            "healthy",
            "Database connection is ready",
            "Backend can query the configured database.",
            evidence={"database_url_scheme": settings.database_url.split(":", 1)[0]},
        )

    def _workspace_config_check(self) -> dict[str, Any]:
        root = self._configured_workspace_root()
        expected_paths = ["backend", "frontend", "docs"]
        missing = [path for path in expected_paths if not (root / path).exists()]
        if not root.exists():
            return self._config_check(
                "workspace_root",
                "workspace",
                "critical",
                "Workspace root does not exist",
                "Delivery cannot collect repository context or run checks without a valid workspace.",
                evidence={"workspace_root": str(root), "configured": bool(settings.workspace_root.strip())},
                next_action="Set WORKSPACE_ROOT to the AI PJM project root.",
            )
        if missing:
            return self._config_check(
                "workspace_root",
                "workspace",
                "warning",
                "Workspace root is incomplete",
                "Workspace exists but expected project directories are missing.",
                evidence={
                    "workspace_root": str(root),
                    "missing": missing,
                    "configured": bool(settings.workspace_root.strip()),
                },
                next_action="Point WORKSPACE_ROOT at the project root that contains backend, frontend, and docs.",
            )
        return self._config_check(
            "workspace_root",
            "workspace",
            "healthy",
            "Workspace root is ready",
            "Workspace contains the expected project directories.",
            evidence={"workspace_root": str(root), "configured": bool(settings.workspace_root.strip())},
        )

    def _git_config_check(self) -> dict[str, Any]:
        root = self._configured_workspace_root()
        git_version = self._command_output(["git", "--version"])
        if not git_version:
            return self._config_check(
                "git",
                "workspace",
                "critical",
                "Git is unavailable",
                "Git is required for worktree isolation, changed-file detection, and MR/PR push.",
                evidence={"workspace_root": str(root), "git_path": shutil.which("git")},
                next_action="Install Git and make sure it is available on PATH.",
            )

        git_root = self._command_output(["git", "rev-parse", "--show-toplevel"], cwd=root)
        if not git_root:
            return self._config_check(
                "git",
                "workspace",
                "warning",
                "Workspace is not a Git repository",
                "Local checks can run, but worktree isolation and remote push need a Git repository.",
                evidence={"workspace_root": str(root), "git_version": git_version},
                next_action="Run from a Git repository or set WORKSPACE_ROOT to the repository root.",
            )

        return self._config_check(
            "git",
            "workspace",
            "healthy",
            "Git is ready",
            "Git is available and the workspace is inside a repository.",
            evidence={"workspace_root": str(root), "git_root": git_root, "git_version": git_version},
        )

    def _codex_config_check(self) -> dict[str, Any]:
        if not settings.execution_codex_enabled:
            return self._config_check(
                "codex_execution",
                "execution",
                "warning",
                "Codex execution is disabled",
                "The platform can still create task packages, but automated code execution will not run.",
                evidence={"execution_codex_enabled": False},
                next_action="Set EXECUTION_CODEX_ENABLED=true and configure EXECUTION_CODEX_COMMAND_TEMPLATE when ready.",
            )
        if not settings.execution_codex_command_template.strip():
            return self._config_check(
                "codex_execution",
                "execution",
                "critical",
                "Codex command template is missing",
                "Codex execution is enabled but has no command template.",
                evidence={"execution_codex_enabled": True},
                next_action="Set EXECUTION_CODEX_COMMAND_TEMPLATE to the command used to invoke Codex.",
            )
        return self._config_check(
            "codex_execution",
            "execution",
            "healthy",
            "Codex execution is configured",
            "Codex execution is enabled and has a command template.",
            evidence={
                "execution_codex_enabled": True,
                "has_preflight": bool(settings.execution_codex_preflight_command.strip()),
                "timeout_seconds": settings.execution_codex_timeout_seconds,
            },
        )

    def _secret_store_config_check(self) -> dict[str, Any]:
        has_master_key = bool(settings.secret_store_master_key.strip())
        if has_master_key:
            return self._config_check(
                "secret_store",
                "secrets",
                "healthy",
                "SecretStore is writable",
                "Project-scoped credentials can be encrypted and stored.",
                evidence={"key_id": settings.secret_store_key_id, "environment": settings.environment},
            )
        status_value = "critical" if settings.environment == "production" else "warning"
        return self._config_check(
            "secret_store",
            "secrets",
            status_value,
            "SecretStore master key is missing",
            "Project-scoped credentials cannot be written without SECRET_STORE_MASTER_KEY.",
            evidence={"key_id": settings.secret_store_key_id, "environment": settings.environment},
            next_action="Set SECRET_STORE_MASTER_KEY before storing provider tokens.",
        )

    def _workflow_provider_config_check(self) -> dict[str, Any]:
        provider = settings.ai_workflow_provider.strip().lower() or "local"
        if provider == "local":
            return self._config_check(
                "workflow_provider",
                "provider",
                "healthy",
                "Local workflow provider is active",
                "Spec and impact drafts use deterministic local rules.",
                evidence={"provider": provider},
            )
        if provider == "openai":
            missing = []
            if not settings.openai_api_base_url.strip():
                missing.append("OPENAI_API_BASE_URL")
            if not settings.openai_model.strip():
                missing.append("OPENAI_MODEL")
            if not settings.openai_api_key.strip() and not settings.openai_api_key_secret_name.strip():
                missing.append("OPENAI_API_KEY or project secret")
            return self._provider_config_result(provider, missing)
        if provider == "dify":
            missing = []
            if not settings.dify_api_base_url.strip():
                missing.append("DIFY_API_BASE_URL")
            if not settings.dify_spec_workflow_id.strip():
                missing.append("DIFY_SPEC_WORKFLOW_ID")
            if not settings.dify_impact_workflow_id.strip():
                missing.append("DIFY_IMPACT_WORKFLOW_ID")
            if not settings.dify_api_key.strip() and not settings.dify_api_key_secret_name.strip():
                missing.append("DIFY_API_KEY or project secret")
            return self._provider_config_result(provider, missing)
        return self._config_check(
            "workflow_provider",
            "provider",
            "critical",
            "Unknown workflow provider",
            "AI_WORKFLOW_PROVIDER must be local, dify, or openai.",
            evidence={"provider": provider},
            next_action="Set AI_WORKFLOW_PROVIDER to local, dify, or openai.",
        )

    def _provider_config_result(self, provider: str, missing: list[str]) -> dict[str, Any]:
        if missing:
            return self._config_check(
                "workflow_provider",
                "provider",
                "warning",
                f"{provider} provider needs configuration",
                "The provider is selected but some global settings are missing. Project secrets may still supply credentials.",
                evidence={"provider": provider, "missing": missing},
                next_action=f"Configure {', '.join(missing)} or set project-scoped provider secrets.",
            )
        return self._config_check(
            "workflow_provider",
            "provider",
            "healthy",
            f"{provider} provider is configured",
            "Selected workflow provider has the required static settings.",
            evidence={"provider": provider},
        )

    def _merge_request_config_check(self) -> dict[str, Any]:
        gitlab_ready = bool(settings.gitlab_api_base_url.strip() and settings.gitlab_project_id.strip())
        github_ready = bool(settings.github_api_base_url.strip() and settings.github_repository.strip())
        if gitlab_ready or github_ready:
            return self._config_check(
                "merge_request_provider",
                "merge_request",
                "healthy",
                "Remote MR/PR provider is configured",
                "At least one remote merge request provider has static repository settings.",
                evidence={"gitlab_ready": gitlab_ready, "github_ready": github_ready},
            )
        return self._config_check(
            "merge_request_provider",
            "merge_request",
            "warning",
            "Remote MR/PR provider is not configured",
            "Local MR records can be created, but remote GitLab/GitHub creation needs repository settings.",
            evidence={"gitlab_ready": gitlab_ready, "github_ready": github_ready},
            next_action="Configure GitLab or GitHub repository settings before creating remote MR/PR.",
        )

    def _deployment_config_check(self) -> dict[str, Any]:
        webhook_ready = bool(settings.deploy_webhook_url.strip())
        environment_fallback_ready = bool(settings.deploy_environment_config_json.strip())
        if webhook_ready or environment_fallback_ready:
            return self._config_check(
                "deployment_provider",
                "deployment",
                "healthy",
                "Deployment configuration is present",
                "Deployment has a webhook provider or fallback environment configuration.",
                evidence={
                    "webhook_ready": webhook_ready,
                    "environment_fallback_ready": environment_fallback_ready,
                },
            )
        return self._config_check(
            "deployment_provider",
            "deployment",
            "warning",
            "Deployment provider is not configured",
            "Local deployment records can be created, but real test environment deployment needs configuration.",
            evidence={
                "webhook_ready": webhook_ready,
                "environment_fallback_ready": environment_fallback_ready,
            },
            next_action="Configure DEPLOY_WEBHOOK_URL or project deployment environments.",
        )

    def _worker_script_config_check(self) -> dict[str, Any]:
        root = self._configured_workspace_root()
        script_paths = [
            "scripts/start-symphony-worker.ps1",
            "scripts/start-deployment-sync-worker.ps1",
            "scripts/start-observability-alert-worker.ps1",
        ]
        missing = [path for path in script_paths if not (root / path).is_file()]
        if missing:
            return self._config_check(
                "worker_scripts",
                "operations",
                "warning",
                "Worker scripts are incomplete",
                "Some local worker entrypoints are missing.",
                evidence={"workspace_root": str(root), "missing": missing},
                next_action="Restore the missing scripts before relying on local background workers.",
            )
        return self._config_check(
            "worker_scripts",
            "operations",
            "healthy",
            "Worker scripts are available",
            "Local worker entrypoints are present for execution, deployment sync, and observability alerts.",
            evidence={"workspace_root": str(root), "scripts": script_paths},
        )

    def _configured_workspace_root(self) -> Path:
        if settings.workspace_root.strip():
            return Path(settings.workspace_root).expanduser().resolve()
        return Path(__file__).resolve().parents[4]

    def _command_output(self, args: list[str], cwd: Path | None = None, timeout: int = 3) -> str | None:
        try:
            completed = subprocess.run(
                args,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        if completed.returncode != 0:
            return None
        return completed.stdout.strip() or None

    def _config_check(
        self,
        check_id: str,
        category: str,
        status: str,
        title: str,
        summary: str,
        *,
        evidence: dict[str, Any] | None = None,
        next_action: str | None = None,
    ) -> dict[str, Any]:
        safe_evidence = redact_value(evidence or {})
        return {
            "id": check_id,
            "category": category,
            "status": status,
            "title": title,
            "summary": summary,
            "evidence": safe_evidence if isinstance(safe_evidence, dict) else {},
            "next_action": next_action,
        }

    def _project_repository_onboarding_step(self, project) -> dict[str, Any]:
        root_value = project.repository_root or settings.workspace_root or str(self._configured_workspace_root())
        root = Path(root_value).expanduser().resolve()
        evidence = {
            "repository_root": str(root),
            "project_repository_root_configured": bool(project.repository_root),
            "default_branch": project.default_branch,
        }
        if not root.exists():
            return self._onboarding_step(
                "repository",
                "blocked",
                "配置项目仓库",
                "项目仓库目录不存在，无法收集上下文或执行检查。",
                "在项目设置中配置有效的 repository_root。",
                evidence,
            )
        if not (root / ".git").exists() and not self._command_output(["git", "rev-parse", "--show-toplevel"], cwd=root):
            return self._onboarding_step(
                "repository",
                "warning",
                "确认 Git 仓库",
                "项目目录存在，但未确认是 Git 仓库。",
                "把 repository_root 指向 Git 仓库根目录。",
                evidence,
            )
        return self._onboarding_step(
            "repository",
            "done",
            "项目仓库已就绪",
            "项目仓库目录存在并可用于上下文收集。",
            evidence=evidence,
        )

    def _project_deployment_onboarding_step(self, project) -> dict[str, Any]:
        environments = self._project_deployment_environments(project.settings_json)
        configured_envs = [
            name for name, value in environments.items()
            if value.get("url") or value.get("environment_name") or value.get("log_url")
        ]
        fallback_ready = bool(settings.deploy_environment_config_json.strip())
        webhook_ready = bool(settings.deploy_webhook_url.strip())
        evidence = {
            "configured_environments": configured_envs,
            "fallback_environment_configured": fallback_ready,
            "deploy_webhook_configured": webhook_ready,
        }
        if configured_envs or fallback_ready or webhook_ready:
            return self._onboarding_step(
                "deployment_environment",
                "done",
                "测试环境配置已就绪",
                "项目或全局配置中已有测试环境或部署入口。",
                evidence=evidence,
            )
        return self._onboarding_step(
            "deployment_environment",
            "warning",
            "配置测试环境",
            "当前只能记录本地部署，尚未配置真实测试环境入口。",
            "在访问管理页配置项目测试环境，或设置 DEPLOY_WEBHOOK_URL。",
            evidence,
        )

    def _project_secret_onboarding_step(
        self,
        provider_names: list[str],
        unhealthy_secret_count: int,
    ) -> dict[str, Any]:
        evidence = {
            "active_secret_providers": provider_names,
            "unhealthy_secret_count": unhealthy_secret_count,
        }
        if unhealthy_secret_count:
            return self._onboarding_step(
                "project_secrets",
                "blocked",
                "修复项目凭证",
                "存在过期、禁用或不可用的项目凭证。",
                "在访问管理页轮换或启用异常凭证。",
                evidence,
            )
        if provider_names:
            return self._onboarding_step(
                "project_secrets",
                "done",
                "项目凭证已配置",
                "项目已有可用的 Provider 凭证记录。",
                evidence=evidence,
            )
        return self._onboarding_step(
            "project_secrets",
            "warning",
            "配置项目凭证",
            "项目尚未配置 Provider 凭证；如果使用全局环境变量可暂时运行，但不利于项目隔离。",
            "按需配置 dify_api_key、openai_api_key、gitlab_token、github_token 或 deploy_token。",
            evidence,
        )

    def _project_workflow_provider_onboarding_step(self, provider_names: list[str]) -> dict[str, Any]:
        provider = settings.ai_workflow_provider.strip().lower() or "local"
        if provider == "local":
            return self._onboarding_step(
                "workflow_provider",
                "done",
                "本地方案生成已就绪",
                "当前使用 local Provider，不依赖外部 AI workflow。",
                evidence={"provider": provider},
            )
        required_provider = "openai" if provider == "openai" else "dify"
        has_project_secret = required_provider in provider_names
        has_global_secret = bool(
            settings.openai_api_key.strip()
            if provider == "openai"
            else settings.dify_api_key.strip()
        )
        evidence = {
            "provider": provider,
            "project_secret_configured": has_project_secret,
            "global_secret_configured": has_global_secret,
        }
        if has_project_secret or has_global_secret:
            return self._onboarding_step(
                "workflow_provider",
                "done",
                "AI Provider 凭证已就绪",
                "当前项目或全局环境已具备所选 workflow provider 的凭证来源。",
                evidence=evidence,
            )
        return self._onboarding_step(
            "workflow_provider",
            "warning",
            "配置 AI Provider 凭证",
            "当前选择了外部 workflow provider，但项目未配置对应凭证。",
            f"配置 {required_provider} 项目凭证，或临时切换 AI_WORKFLOW_PROVIDER=local。",
            evidence,
        )

    def _project_merge_request_onboarding_step(self, provider_names: list[str]) -> dict[str, Any]:
        gitlab_ready = bool(settings.gitlab_api_base_url.strip() and settings.gitlab_project_id.strip())
        github_ready = bool(settings.github_api_base_url.strip() and settings.github_repository.strip())
        token_ready = "gitlab" in provider_names or "github" in provider_names or bool(
            settings.gitlab_token.strip() or settings.github_token.strip()
        )
        evidence = {
            "gitlab_repository_configured": gitlab_ready,
            "github_repository_configured": github_ready,
            "token_configured": token_ready,
        }
        if (gitlab_ready or github_ready) and token_ready:
            return self._onboarding_step(
                "merge_request",
                "done",
                "远端 MR/PR 已就绪",
                "远端仓库配置和凭证来源已具备。",
                evidence=evidence,
            )
        if gitlab_ready or github_ready:
            return self._onboarding_step(
                "merge_request",
                "warning",
                "配置 MR/PR 凭证",
                "远端仓库已配置，但还缺少项目级或全局 Token。",
                "配置 gitlab_token 或 github_token 项目凭证。",
                evidence,
            )
        return self._onboarding_step(
            "merge_request",
            "warning",
            "配置远端 MR/PR",
            "当前可以创建本地 MR 记录，但尚未配置 GitLab/GitHub 远端仓库。",
            "按项目选择 GitLab 或 GitHub，并配置仓库、Token、reviewer/label 策略。",
            evidence,
        )

    def _project_execution_onboarding_step(self) -> dict[str, Any]:
        evidence = {
            "execution_codex_enabled": settings.execution_codex_enabled,
            "command_template_configured": bool(settings.execution_codex_command_template.strip()),
            "max_concurrency": settings.execution_max_concurrency,
        }
        if settings.execution_codex_enabled and settings.execution_codex_command_template.strip():
            return self._onboarding_step(
                "execution",
                "done",
                "Codex 执行已配置",
                "任务可以创建受控执行 run。",
                evidence=evidence,
            )
        if settings.execution_codex_enabled:
            return self._onboarding_step(
                "execution",
                "blocked",
                "补齐 Codex 命令模板",
                "Codex 已启用但命令模板为空，执行会失败。",
                "设置 EXECUTION_CODEX_COMMAND_TEMPLATE。",
                evidence,
            )
        return self._onboarding_step(
            "execution",
            "warning",
            "启用 Codex 执行",
            "当前只能生成任务包或执行本地检查，自动编码执行未启用。",
            "设置 EXECUTION_CODEX_ENABLED=true 并配置命令模板。",
            evidence,
        )

    def _project_config_health_onboarding_step(self, config_health: dict) -> dict[str, Any]:
        status_value = config_health.get("status")
        checks = config_health.get("checks") if isinstance(config_health.get("checks"), list) else []
        critical_ids = [check.get("id") for check in checks if check.get("status") == "critical"]
        warning_ids = [check.get("id") for check in checks if check.get("status") == "warning"]
        evidence = {
            "config_health_status": status_value,
            "critical_checks": critical_ids,
            "warning_checks": warning_ids,
        }
        if critical_ids:
            return self._onboarding_step(
                "config_health",
                "blocked",
                "修复阻塞配置",
                "全局配置健康检查存在 critical 项。",
                "打开 /api/v2/observability/config-health 查看并修复 critical 检查。",
                evidence,
            )
        if warning_ids:
            return self._onboarding_step(
                "config_health",
                "warning",
                "处理配置提醒",
                "全局配置健康检查存在 warning 项，不一定阻塞本地验证，但会影响生产化。",
                "按优先级处理 config-health 返回的 warning。",
                evidence,
            )
        return self._onboarding_step(
            "config_health",
            "done",
            "配置健康检查通过",
            "全局配置健康检查没有 warning 或 critical。",
            evidence=evidence,
        )

    def _onboarding_step(
        self,
        step_id: str,
        status: str,
        label: str,
        summary: str,
        next_action: str | None = None,
        evidence: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        safe_evidence = redact_value(evidence or {})
        return {
            "id": step_id,
            "status": status,
            "label": label,
            "summary": summary,
            "next_action": next_action,
            "evidence": safe_evidence if isinstance(safe_evidence, dict) else {},
        }

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

    async def _context_payload_with_similar_demands(
        self,
        *,
        db: AsyncSession,
        raw_input: str,
        title: str,
        project_id: int | None,
        context_payload: dict | None,
    ) -> dict | None:
        payload = dict(context_payload or {})
        candidates = await delivery_repository.list_recent_demands_for_history(
            db=db,
            project_id=project_id,
            limit=50,
        )
        entries = self._similar_demand_entries(
            raw_input=raw_input,
            title=title,
            candidates=candidates,
            limit=5,
        )
        if not entries:
            return payload or None

        context_key = "historical_demands"
        if context_key in payload:
            context_key = "generated_historical_demands"
        payload[context_key] = {
            "generated_by": "ai_pjm",
            "source": "same_project_recent_demands",
            "items": entries,
        }
        return payload

    def _similar_demand_entries(
        self,
        *,
        raw_input: str,
        title: str,
        candidates: list[DemandItem],
        limit: int,
    ) -> list[dict]:
        target_tokens = self._tokenize_history_text(f"{title}\n{raw_input}")
        scored: list[tuple[float, DemandItem]] = []
        for candidate in candidates:
            score = self._demand_similarity_score(target_tokens, candidate)
            if score >= 0.12:
                scored.append((score, candidate))

        scored.sort(
            key=lambda item: (
                item[0],
                item[1].updated_at or item[1].created_at,
                item[1].id,
            ),
            reverse=True,
        )

        entries: list[dict] = []
        for score, candidate in scored[: max(1, limit)]:
            summary = " ".join((candidate.raw_input or "").split())
            entries.append(
                {
                    "id": candidate.id,
                    "title": redact_text(candidate.title or self._derive_title(candidate.raw_input)),
                    "source_type": candidate.source_type,
                    "status": candidate.status,
                    "risk_level": candidate.risk_level,
                    "similarity_score": round(score, 3),
                    "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
                    "summary": redact_text(summary[:360]),
                }
            )
        return entries

    def _demand_similarity_score(self, target_tokens: set[str], candidate: DemandItem) -> float:
        candidate_tokens = self._tokenize_history_text(
            f"{candidate.title or ''}\n{candidate.raw_input or ''}"
        )
        if not target_tokens or not candidate_tokens:
            return 0.0

        overlap = target_tokens & candidate_tokens
        if not overlap:
            return 0.0
        jaccard = len(overlap) / len(target_tokens | candidate_tokens)
        coverage = len(overlap) / len(target_tokens)
        return min((jaccard * 0.8) + (coverage * 0.2), 1.0)

    def _tokenize_history_text(self, text: str) -> set[str]:
        normalized = text.lower()
        ascii_tokens = re.findall(r"[a-z0-9_]{2,}", normalized)
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", normalized)
        chinese_bigrams = [
            f"{left}{right}"
            for left, right in zip(chinese_chars, chinese_chars[1:])
        ]
        return set(ascii_tokens + chinese_chars + chinese_bigrams)

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

    async def _run_provider_operation(
        self,
        *,
        operation: str,
        provider: WorkflowProvider,
        call: Callable[[WorkflowProvider], Awaitable[ProviderDraftT]],
    ) -> tuple[ProviderDraftT, WorkflowProvider]:
        attempts = max(1, settings.ai_workflow_provider_retry_attempts)
        errors: list[dict] = []
        last_error: AIServiceException | None = None

        for attempt in range(1, attempts + 1):
            try:
                draft = await call(provider)
            except AIServiceException as exc:
                last_error = exc
                errors.append(self._provider_error_metadata(provider, operation, attempt, exc))
                if attempt < attempts:
                    await asyncio.sleep(max(settings.ai_workflow_provider_retry_backoff_seconds, 0.0))
                continue

            if attempt > 1:
                draft = self._annotate_provider_draft(
                    draft,
                    {
                        "provider_recovery": {
                            "operation": operation,
                            "fallback_used": False,
                            "provider": provider.name,
                            "attempts": attempt,
                            "previous_errors": errors,
                        }
                    },
                )
            return draft, provider

        if self._should_fallback_provider(provider):
            fallback_provider = LocalWorkflowProvider()
            try:
                fallback_draft = await call(fallback_provider)
            except AIServiceException as fallback_exc:
                errors.append(
                    self._provider_error_metadata(
                        fallback_provider,
                        operation,
                        1,
                        fallback_exc,
                    )
                )
                if last_error is not None:
                    raise AIServiceException(
                        f"{provider.name} provider failed and local fallback also failed: "
                        f"{redact_text(str(fallback_exc))}"
                    ) from last_error
                raise

            fallback_draft = self._annotate_provider_draft(
                fallback_draft,
                {
                    "provider_recovery": {
                        "operation": operation,
                        "fallback_used": True,
                        "failed_provider": provider.name,
                        "fallback_provider": fallback_provider.name,
                        "attempts": attempts,
                        "errors": errors,
                    }
                },
            )
            return fallback_draft, fallback_provider

        if last_error is not None:
            raise last_error
        raise AIServiceException(f"{provider.name} provider failed during {operation}")

    def _should_fallback_provider(self, provider: WorkflowProvider) -> bool:
        return (
            settings.ai_workflow_provider_fallback_enabled
            and provider.name in {"dify", "openai"}
        )

    def _provider_error_metadata(
        self,
        provider: WorkflowProvider,
        operation: str,
        attempt: int,
        exc: Exception,
    ) -> dict:
        return {
            "provider": provider.name,
            "operation": operation,
            "attempt": attempt,
            "error_type": exc.__class__.__name__,
            "message": redact_text(str(exc))[:1000],
        }

    def _annotate_provider_draft(self, draft: ProviderDraftT, metadata: dict) -> ProviderDraftT:
        existing = getattr(draft, "provider_metadata", {}) or {}
        return replace(
            draft,
            provider_metadata={
                **existing,
                **metadata,
            },
        )

    def _provider_fallback_used(self, metadata: dict) -> bool:
        recovery = metadata.get("provider_recovery") if isinstance(metadata, dict) else None
        return isinstance(recovery, dict) and recovery.get("fallback_used") is True

    def _with_provider_evidence(self, decision: GateDecision, provider_metadata: dict) -> GateDecision:
        if not provider_metadata:
            return decision
        return replace(
            decision,
            evidence={
                **decision.evidence,
                "provider_metadata": redact_value(provider_metadata),
            },
        )

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

    def _merge_request_source_run(self, record: MergeRequestRecord, task: CodingTask) -> ExecutionRun | None:
        for run in task.execution_runs or []:
            if run.id == record.execution_run_id:
                return run
        return None

    def _merge_request_review_issues(self, record: MergeRequestRecord) -> list[str]:
        issues: list[str] = []
        evidence = record.evidence_json or {}
        if isinstance(evidence, dict):
            remote_review = evidence.get("remote_review")
            if isinstance(remote_review, dict):
                issues.extend(self._string_items(remote_review.get("blocking_issues")))
            issues.extend(self._string_items(evidence.get("blocking_issues")))

        for comment in record.review_comments_json or []:
            if not isinstance(comment, dict):
                continue
            body = str(comment.get("body") or "").strip()
            if body:
                issues.append(body)

        if not issues and record.review_summary:
            issues.append(record.review_summary)

        deduped: list[str] = []
        seen: set[str] = set()
        for issue in issues:
            text = redact_text(str(issue)).strip()
            if not text or text in seen:
                continue
            deduped.append(text[:1000])
            seen.add(text)
        return deduped

    def _review_gate_status(self, review_status: str) -> GateStatus:
        if review_status == self._enum_or_str(ReviewStatus.PASSED):
            return GateStatus.PASSED
        if review_status == self._enum_or_str(ReviewStatus.BLOCKING):
            return GateStatus.FAILED
        return GateStatus.MANUAL_REQUIRED

    def _gitlab_webhook_iid(self, payload: dict) -> str | None:
        attrs = payload.get("object_attributes")
        merge_request = payload.get("merge_request")
        candidates = []
        if isinstance(attrs, dict):
            candidates.extend([
                attrs.get("iid"),
                attrs.get("merge_request_iid"),
                attrs.get("target_iid"),
                attrs.get("noteable_iid"),
            ])
        if isinstance(merge_request, dict):
            candidates.extend([merge_request.get("iid"), merge_request.get("id")])
        merge_requests = payload.get("merge_requests")
        if isinstance(merge_requests, list):
            for item in merge_requests:
                if isinstance(item, dict):
                    candidates.extend([item.get("iid"), item.get("id")])
        for key in ("merge_request_iid", "mr_iid", "iid"):
            candidates.append(payload.get(key))
        for value in candidates:
            text = self._str_value(value)
            if text:
                return text
        return None

    def _gitlab_webhook_review_update(self, payload: dict) -> dict:
        object_kind = self._str_value(payload.get("object_kind")) or self._str_value(payload.get("event_type")) or "unknown"
        attrs = payload.get("object_attributes")
        attrs = attrs if isinstance(attrs, dict) else {}
        event = {
            "received_at": utc_now().isoformat(),
            "object_kind": object_kind,
            "action": self._str_value(attrs.get("action")),
            "state": self._str_value(attrs.get("state")),
            "status": self._str_value(attrs.get("status")),
            "iid": self._gitlab_webhook_iid(payload),
        }
        status = MergeRequestStatus.REVIEWING
        review_status = ReviewStatus.PENDING
        blocking_issues: list[str] = []
        comments: list[dict] = []
        summary = f"GitLab webhook received: {object_kind}."

        if object_kind == "merge_request":
            state = (self._str_value(attrs.get("state")) or "").lower()
            detailed_status = (self._str_value(attrs.get("detailed_merge_status")) or "").lower()
            event["detailed_merge_status"] = detailed_status
            if state == "closed":
                status = MergeRequestStatus.CLOSED
                review_status = ReviewStatus.BLOCKING
                blocking_issues.append("Merge request is closed.")
                summary = "GitLab webhook marked the merge request closed."
            elif state == "merged":
                status = MergeRequestStatus.REVIEW_PASSED
                review_status = ReviewStatus.PASSED
                summary = "GitLab webhook marked the merge request merged."
            elif detailed_status in {"mergeable", "can_be_merged"}:
                summary = "GitLab webhook marked the merge request mergeable."
            else:
                summary = f"GitLab webhook updated merge request state: {state or detailed_status or 'unknown'}."

        elif object_kind == "pipeline":
            pipeline_status = (self._str_value(attrs.get("status")) or "").lower()
            if pipeline_status in {"success", "passed"}:
                status = MergeRequestStatus.REVIEW_PASSED
                review_status = ReviewStatus.PASSED
                summary = "GitLab webhook reported pipeline success."
            elif pipeline_status in {"failed", "canceled", "cancelled", "skipped"}:
                status = MergeRequestStatus.REVIEW_BLOCKED
                review_status = ReviewStatus.BLOCKING
                blocking_issues.append(f"GitLab pipeline status is {pipeline_status}.")
                summary = f"GitLab webhook reported pipeline {pipeline_status}."
            else:
                summary = f"GitLab webhook reported pipeline {pipeline_status or 'pending'}."

        elif object_kind == "note":
            note = redact_text(self._str_value(attrs.get("note")) or "")
            if note:
                comments.append({
                    "body": note,
                    "author": self._gitlab_webhook_user_name(payload),
                    "created_at": self._str_value(attrs.get("created_at")),
                    "url": self._str_value(attrs.get("url")),
                    "resolvable": bool(attrs.get("resolvable")),
                    "resolved": bool(attrs.get("resolved")),
                })
            if note and bool(attrs.get("resolvable")) and not bool(attrs.get("resolved")):
                status = MergeRequestStatus.REVIEW_BLOCKED
                review_status = ReviewStatus.BLOCKING
                blocking_issues.append(note[:500])
                summary = "GitLab webhook received an unresolved review note."
            else:
                summary = "GitLab webhook received a merge request note."

        return {
            "status": status,
            "review_status": review_status,
            "summary": summary,
            "comments": comments,
            "blocking_issues": blocking_issues,
            "event": event,
        }

    def _gitlab_webhook_user_name(self, payload: dict) -> str | None:
        for key in ("user", "user_username", "user_name"):
            value = payload.get(key)
            if isinstance(value, dict):
                text = self._str_value(value.get("username")) or self._str_value(value.get("name"))
            else:
                text = self._str_value(value)
            if text:
                return text
        return None

    def _github_webhook_signature_valid(self, signature: str, body: bytes, secret: str) -> bool:
        expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.strip(), f"sha256={expected}")

    def _github_webhook_number(self, payload: dict) -> str | None:
        candidates = []
        pull_request = payload.get("pull_request")
        issue = payload.get("issue")
        check_run = payload.get("check_run")
        if isinstance(pull_request, dict):
            candidates.append(pull_request.get("number"))
        if isinstance(issue, dict):
            candidates.append(issue.get("number"))
        if isinstance(check_run, dict):
            pull_requests = check_run.get("pull_requests")
            if isinstance(pull_requests, list):
                for item in pull_requests:
                    if isinstance(item, dict):
                        candidates.append(item.get("number"))
        for key in ("number", "pull_request_number", "pr_number"):
            candidates.append(payload.get(key))
        for value in candidates:
            text = self._str_value(value)
            if text:
                return text
        return None

    def _github_webhook_review_update(self, payload: dict, event_type: str) -> dict:
        action = self._str_value(payload.get("action"))
        event = {
            "received_at": utc_now().isoformat(),
            "event_type": event_type,
            "action": action,
            "number": self._github_webhook_number(payload),
        }
        status = MergeRequestStatus.REVIEWING
        review_status = ReviewStatus.PENDING
        blocking_issues: list[str] = []
        comments: list[dict] = []
        summary = f"GitHub webhook received: {event_type}."

        if event_type == "pull_request":
            pull_request = payload.get("pull_request")
            pull_request = pull_request if isinstance(pull_request, dict) else {}
            state = (self._str_value(pull_request.get("state")) or "").lower()
            merged = bool(pull_request.get("merged"))
            draft = bool(pull_request.get("draft"))
            event["state"] = state
            event["merged"] = merged
            event["draft"] = draft
            if state == "closed" and merged:
                status = MergeRequestStatus.REVIEW_PASSED
                review_status = ReviewStatus.PASSED
                summary = "GitHub webhook marked the pull request merged."
            elif state == "closed":
                status = MergeRequestStatus.CLOSED
                review_status = ReviewStatus.BLOCKING
                blocking_issues.append("Pull request is closed.")
                summary = "GitHub webhook marked the pull request closed."
            elif draft:
                summary = "GitHub webhook reported a draft pull request."
            else:
                summary = f"GitHub webhook updated pull request state: {state or action or 'unknown'}."

        elif event_type == "pull_request_review":
            review = payload.get("review")
            review = review if isinstance(review, dict) else {}
            review_state = (self._str_value(review.get("state")) or "").upper()
            body = redact_text(self._str_value(review.get("body")) or "")
            event["review_state"] = review_state
            if review_state == "CHANGES_REQUESTED":
                status = MergeRequestStatus.REVIEW_BLOCKED
                review_status = ReviewStatus.BLOCKING
                issue = body or "A GitHub reviewer requested changes."
                blocking_issues.append(issue[:500])
                summary = "GitHub webhook received a changes-requested review."
            elif review_state == "APPROVED":
                summary = "GitHub webhook received an approved review; waiting for checks."
            else:
                summary = f"GitHub webhook received review state {review_state or 'unknown'}."

        elif event_type in {"pull_request_review_comment", "issue_comment"}:
            comment = payload.get("comment")
            comment = comment if isinstance(comment, dict) else {}
            body = redact_text(self._str_value(comment.get("body")) or "")
            if body:
                comments.append({
                    "body": body,
                    "author": self._github_user_name(comment.get("user")),
                    "created_at": self._str_value(comment.get("created_at")),
                    "url": self._str_value(comment.get("html_url")) or self._str_value(comment.get("url")),
                })
            summary = "GitHub webhook received a pull request comment."

        elif event_type == "check_run":
            check_run = payload.get("check_run")
            check_run = check_run if isinstance(check_run, dict) else {}
            conclusion = (self._str_value(check_run.get("conclusion")) or "").lower()
            check_status = (self._str_value(check_run.get("status")) or "").lower()
            name = self._str_value(check_run.get("name")) or "check"
            event["check_name"] = name
            event["status"] = check_status
            event["conclusion"] = conclusion
            if conclusion in {"success", "neutral", "skipped"}:
                status = MergeRequestStatus.REVIEW_PASSED
                review_status = ReviewStatus.PASSED
                summary = f"GitHub webhook reported check {name} success."
            elif conclusion in {"failure", "timed_out", "cancelled", "action_required"}:
                status = MergeRequestStatus.REVIEW_BLOCKED
                review_status = ReviewStatus.BLOCKING
                blocking_issues.append(f"GitHub check {name} concluded {conclusion}.")
                summary = f"GitHub webhook reported check {name} {conclusion}."
            else:
                summary = f"GitHub webhook reported check {name} {check_status or conclusion or 'pending'}."

        elif event_type == "status":
            state = (self._str_value(payload.get("state")) or "").lower()
            context = self._str_value(payload.get("context")) or "status"
            event["state"] = state
            event["context"] = context
            if state == "success":
                status = MergeRequestStatus.REVIEW_PASSED
                review_status = ReviewStatus.PASSED
                summary = f"GitHub webhook reported status {context} success."
            elif state in {"failure", "error"}:
                status = MergeRequestStatus.REVIEW_BLOCKED
                review_status = ReviewStatus.BLOCKING
                blocking_issues.append(f"GitHub status {context} is {state}.")
                summary = f"GitHub webhook reported status {context} {state}."
            else:
                summary = f"GitHub webhook reported status {context} {state or 'pending'}."

        return {
            "status": status,
            "review_status": review_status,
            "summary": summary,
            "comments": comments,
            "blocking_issues": blocking_issues,
            "event": event,
        }

    def _github_user_name(self, value: object) -> str | None:
        if not isinstance(value, dict):
            return None
        return self._str_value(value.get("login")) or self._str_value(value.get("name"))

    def _str_value(self, value) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _project_deployment_environments(self, project_settings: dict | None) -> dict:
        if project_settings is None:
            return {}
        if not isinstance(project_settings, dict):
            raise BadRequestException("Project settings must be a JSON object")
        delivery_settings = project_settings.get("delivery")
        if delivery_settings is None:
            return {}
        if not isinstance(delivery_settings, dict):
            raise BadRequestException("Project delivery settings must be a JSON object")
        environments = delivery_settings.get("deployment_environments")
        if environments is None:
            return {}
        return self._normalize_deployment_environment_config(environments)

    def _normalize_deployment_environment_config(self, environments: dict) -> dict:
        if not isinstance(environments, dict):
            raise BadRequestException("Deployment environment settings must be a JSON object")
        if len(environments) > 50:
            raise BadRequestException("Deployment environment settings cannot exceed 50 entries")

        allowed_keys = {"url", "log_url", "description", "environment_name"}
        normalized: dict[str, dict[str, str]] = {}
        for raw_environment, raw_config in environments.items():
            environment = str(raw_environment).strip()
            if not environment:
                raise BadRequestException("Deployment environment name is required")
            if len(environment) > 100:
                raise BadRequestException("Deployment environment name cannot exceed 100 characters")

            if isinstance(raw_config, str):
                values = {"url": raw_config}
            elif isinstance(raw_config, dict):
                unknown_keys = set(raw_config) - allowed_keys
                if unknown_keys:
                    raise BadRequestException(
                        f"Unsupported deployment environment setting: {sorted(unknown_keys)[0]}"
                    )
                values = raw_config
            else:
                raise BadRequestException("Deployment environment entries must be JSON objects")

            sanitized = {}
            for key in allowed_keys:
                value = values.get(key)
                if value is None:
                    continue
                text = str(value).strip()
                if text:
                    sanitized[key] = text
            if sanitized:
                normalized[environment] = sanitized
        return normalized

    def _deployment_environment_settings(
        self,
        environment: str,
        project_settings: dict | None = None,
    ) -> tuple[str | None, dict]:
        project_environments = self._project_deployment_environments(project_settings)
        selected_project_config = project_environments.get(environment) or project_environments.get("*")
        if selected_project_config is not None:
            return self._deployment_environment_entry_settings(
                environment,
                selected_project_config,
                source="project_settings",
            )

        config_text = settings.deploy_environment_config_json.strip()
        if not config_text:
            return None, {"environment": environment, "source": "request"}
        try:
            config = json.loads(config_text)
        except ValueError as exc:
            raise BadRequestException("DEPLOY_ENVIRONMENT_CONFIG_JSON must be valid JSON") from exc
        if not isinstance(config, dict):
            raise BadRequestException("DEPLOY_ENVIRONMENT_CONFIG_JSON must be a JSON object")

        selected = config.get(environment) or config.get("*")
        if selected is None:
            return None, {"environment": environment, "source": "request"}
        return self._deployment_environment_entry_settings(
            environment,
            selected,
            source="DEPLOY_ENVIRONMENT_CONFIG_JSON",
        )

    def _deployment_environment_entry_settings(
        self,
        environment: str,
        selected: str | dict,
        source: str,
    ) -> tuple[str | None, dict]:
        if isinstance(selected, str):
            return selected, {
                "environment": environment,
                "source": source,
                "url": redact_text(selected),
            }
        if not isinstance(selected, dict):
            raise BadRequestException("Deployment environment config entries must be strings or objects")

        allowed_keys = {"url", "log_url", "description", "environment_name"}
        raw_url = selected.get("url")
        configured_url = str(raw_url).strip() if raw_url is not None and str(raw_url).strip() else None
        sanitized = {
            key: redact_text(str(value))
            for key, value in selected.items()
            if key in allowed_keys and value is not None and str(value).strip()
        }
        return configured_url, {"environment": environment, "source": source, **sanitized}

    def _deployment_log_evidence(self, provider_evidence: dict, environment_config: dict) -> dict:
        logs: dict[str, str] = {}
        configured_log_url = environment_config.get("log_url") if isinstance(environment_config, dict) else None
        if isinstance(configured_log_url, str) and configured_log_url.strip():
            logs["configured_log_url"] = configured_log_url.strip()

        provider_log_url = provider_evidence.get("log_url") if isinstance(provider_evidence, dict) else None
        if isinstance(provider_log_url, str) and provider_log_url.strip():
            logs["provider_log_url"] = provider_log_url.strip()

        logs_tail = provider_evidence.get("logs_tail") if isinstance(provider_evidence, dict) else None
        if isinstance(logs_tail, str) and logs_tail.strip():
            logs["logs_tail"] = redact_text(logs_tail)[-4000:]
        return logs

    def _deployment_gate_status(self, deployment_status: str) -> GateStatus:
        if deployment_status == self._enum_or_str(DeploymentStatus.DEPLOYED):
            return GateStatus.PASSED
        if deployment_status == self._enum_or_str(DeploymentStatus.FAILED):
            return GateStatus.FAILED
        return GateStatus.MANUAL_REQUIRED

    def _deployment_gate_reason(self, deployment_status: str) -> str:
        if deployment_status == self._enum_or_str(DeploymentStatus.DEPLOYED):
            return "Test deployment record was created."
        if deployment_status == self._enum_or_str(DeploymentStatus.FAILED):
            return "Test deployment provider reported failure."
        return "Test deployment is pending."

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
        if normalized_provider not in {"gitlab", "github"}:
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

    async def _push_repair_run_to_merge_request(
        self,
        *,
        provider: str,
        record: MergeRequestRecord,
        run: ExecutionRun,
    ) -> dict:
        normalized_provider = (provider or "local").strip().lower()
        if normalized_provider == "local":
            return {"enabled": False, "reason": "local_provider"}
        if normalized_provider not in {"gitlab", "github"}:
            return {"enabled": False, "reason": "provider_not_supported", "provider": normalized_provider}
        if not settings.merge_request_auto_push_enabled:
            return {"enabled": False, "reason": "disabled"}

        remote = settings.merge_request_git_remote.strip()
        if not remote:
            raise BadRequestException("MERGE_REQUEST_GIT_REMOTE is required when auto push is enabled")
        if not record.source_branch:
            raise BadRequestException("Merge request has no source branch for repair push")
        if not run.worktree_path:
            raise BadRequestException("Repair execution run has no worktree path for remote branch push")

        repair_branch = run.branch_name or self._dispatch_evidence_value(run, "branch_name")
        if not repair_branch:
            raise BadRequestException("Repair execution run has no source branch for remote branch push")

        worktree_path = Path(run.worktree_path).expanduser()
        if not worktree_path.exists() or not worktree_path.is_dir():
            raise BadRequestException(f"Repair execution worktree does not exist: {run.worktree_path}")

        try:
            completed = await asyncio.to_thread(
                self._run_git_push_refspec,
                worktree_path,
                remote,
                repair_branch,
                record.source_branch,
            )
        except subprocess.TimeoutExpired as exc:
            raise BadRequestException(
                "Git push timed out while updating merge request repair: "
                f"{self._safe_tail(exc.stderr) or self._safe_tail(exc.stdout)}"
            ) from exc
        stdout_tail = self._safe_tail(completed.stdout)
        stderr_tail = self._safe_tail(completed.stderr)
        if completed.returncode != 0:
            detail = stderr_tail or stdout_tail or "git push failed"
            raise BadRequestException(f"Git push failed while updating merge request repair: {detail}")

        return {
            "enabled": True,
            "provider": normalized_provider,
            "remote": remote,
            "source_branch": repair_branch,
            "target_branch": record.source_branch,
            "timeout_seconds": settings.merge_request_push_timeout_seconds,
            "stdout_tail": stdout_tail,
            "stderr_tail": stderr_tail,
        }

    async def _mark_merge_request_repair_pushed(
        self,
        *,
        db: AsyncSession,
        record: MergeRequestRecord,
        repaired_run: ExecutionRun,
        push_evidence: dict,
        project_id: int | None,
        actor_user_id: int | None,
        actor_ref: str | None,
    ) -> None:
        evidence = {
            **(record.evidence_json or {}),
            "latest_repair_run_id": repaired_run.id,
            "latest_repair_commit_sha": repaired_run.commit_sha or self._dispatch_evidence_value(repaired_run, "commit_sha"),
            "latest_repair_push": redact_value(push_evidence),
        }
        await delivery_repository.update_merge_request_record(
            db,
            record,
            status=MergeRequestStatus.REVIEWING,
            review_status=ReviewStatus.PENDING,
            review_summary="Repair changes were pushed; remote review should be synced again.",
            evidence_json=evidence,
        )
        await audit_repository.create_event(
            db,
            action="delivery.merge_request_repair_pushed",
            entity_type="merge_request",
            entity_id=record.id,
            project_id=project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref or "system",
            summary="Merge request repair changes pushed.",
            metadata={
                "merge_request_id": record.id,
                "repair_run_id": repaired_run.id,
                "source_branch": push_evidence.get("source_branch"),
                "target_branch": push_evidence.get("target_branch"),
                "enabled": push_evidence.get("enabled"),
            },
        )

    def _run_git_push(
        self,
        worktree_path: Path,
        remote: str,
        source_branch: str,
    ) -> subprocess.CompletedProcess[str]:
        return self._run_git_push_refspec(
            worktree_path,
            remote,
            source_branch,
            source_branch,
        )

    def _run_git_push_refspec(
        self,
        worktree_path: Path,
        remote: str,
        source_ref: str,
        target_ref: str,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "git",
                "-C",
                str(worktree_path),
                "push",
                "--set-upstream",
                remote,
                f"{source_ref}:{target_ref}",
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
        evidence_links: dict | None = None,
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
        lines.extend(["", "### Evidence Links"])
        lines.extend(self._markdown_evidence_links(evidence_links or {}))
        return redact_text("\n".join(lines))

    def _merge_request_evidence_links(
        self,
        *,
        demand: DemandItem,
        task: CodingTask,
        run: ExecutionRun,
    ) -> dict:
        base_url = settings.delivery_app_base_url.strip().rstrip("/")
        entries = {
            "demand": {"label": f"Demand #{demand.id}", "tab": "summary"},
            "task_package": {"label": f"Task package #{task.id}", "tab": "taskPackage"},
            "execution": {"label": f"Execution run #{run.id}", "tab": "execution"},
            "evidence": {"label": "Evidence timeline", "tab": "evidence"},
        }
        for entry in entries.values():
            if base_url:
                entry["url"] = f"{base_url}/?demand_id={demand.id}&tab={entry['tab']}"
        if demand.trace_id:
            entries["trace"] = {"label": f"Trace ID {demand.trace_id}"}
        return entries

    def _markdown_evidence_links(self, links: dict) -> list[str]:
        if not links:
            return ["- No evidence links recorded."]
        items = []
        for key in ("demand", "task_package", "execution", "evidence", "trace"):
            value = links.get(key)
            if not isinstance(value, dict):
                continue
            label = str(value.get("label") or key).strip()
            url = str(value.get("url") or "").strip()
            items.append(f"- [{label}]({url})" if url else f"- {label}")
        return items or ["- No evidence links recorded."]

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

    def _build_retry_context(self, task: CodingTask) -> dict:
        latest_run = self._latest_by_created_at(task.execution_runs or [])
        if not latest_run:
            return {}

        source_evidence = latest_run.evidence_json or {}
        execution_allowed = (
            source_evidence.get("execution_allowed")
            if isinstance(source_evidence, dict)
            else None
        )
        previous_context = None
        if isinstance(execution_allowed, dict):
            previous_context = execution_allowed.get("retry_context")
        if previous_context is None and isinstance(source_evidence, dict):
            previous_context = source_evidence.get("retry_context")

        previous_chain = []
        if isinstance(previous_context, dict) and isinstance(previous_context.get("retry_chain"), list):
            previous_chain = [item for item in previous_context["retry_chain"] if isinstance(item, int)]

        return {
            "source_run_id": latest_run.id,
            "source_status": self._enum_or_str(latest_run.status),
            "source_trigger_mode": latest_run.trigger_mode,
            "source_summary": latest_run.result_summary,
            "retry_chain": [*previous_chain, latest_run.id],
        }

    def _build_review_repair_context(
        self,
        *,
        record: MergeRequestRecord,
        source_run: ExecutionRun,
        review_issues: list[str],
        attempt: int,
        max_attempts: int,
    ) -> dict:
        return {
            "source": "merge_request_review",
            "source_run_id": source_run.id,
            "source_merge_request_id": record.id,
            "attempt": attempt,
            "max_attempts": max_attempts,
            "failure_summary": record.review_summary or "Merge request review has blocking issues.",
            "failed_checks": [],
            "review_issues": review_issues,
            "repair_chain": [source_run.id],
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

    def _symphony_lease_expired(self, run: ExecutionRun, now: datetime) -> bool:
        evidence = run.evidence_json or {}
        bridge = evidence.get("symphony_bridge") if isinstance(evidence, dict) else {}
        if not isinstance(bridge, dict):
            return False
        expires_at = self._parse_datetime(bridge.get("lease_expires_at"))
        return expires_at is not None and expires_at <= now

    def _run_has_unredacted_sensitive_evidence(self, run: ExecutionRun) -> bool:
        if has_unredacted_sensitive_data(run.result_summary):
            return True
        if has_unredacted_sensitive_data(run.evidence_json):
            return True
        for log in run.logs or []:
            if has_unredacted_sensitive_data(log.message):
                return True
            if has_unredacted_sensitive_data(log.event_json):
                return True
        return False

    def _secret_health_breakdown(
        self,
        secrets: list,
        statuses: dict[int, str],
        reasons: dict[int, str],
    ) -> str:
        if not secrets:
            return ""
        counts = Counter(statuses.get(secret.id, "unknown") for secret in secrets)
        status_summary = "，".join(f"{status} {count}" for status, count in sorted(counts.items()))
        reason = next((reasons.get(secret.id) for secret in secrets if reasons.get(secret.id)), None)
        if reason:
            return f" 状态分布：{status_summary}。示例原因：{redact_text(reason)[:160]}"
        return f" 状态分布：{status_summary}。"

    def _parse_datetime(self, value) -> datetime | None:
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed

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
        return sorted(
            items,
            key=lambda item: (self._created_at_timestamp(getattr(item, "created_at", None)), item.id or 0),
            reverse=True,
        )[0]

    def _created_at_timestamp(self, value: datetime | None) -> float:
        if not value:
            return 0.0
        normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return normalized.timestamp()


delivery_service = DeliveryService()
