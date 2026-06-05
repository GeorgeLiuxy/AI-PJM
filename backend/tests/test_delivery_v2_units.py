"""Delivery v2 service rule tests that do not require a database."""

import logging
import sys
import subprocess
import json
import hashlib
import hmac
from types import SimpleNamespace
from datetime import timedelta

import pytest

from app.core.config import settings
from app.core.db import utc_now
from app.core.exceptions import AIServiceException, BadRequestException
from app.core.logging import JsonLogFormatter
from app.modules.audit.repository import audit_repository
from app.modules.auth.repository import auth_repository
from app.modules.delivery.executors.base import CheckResult
from app.modules.delivery.executors.factory import get_execution_executor
from app.modules.delivery.executors.local_checks import LocalChecksExecutor, WorktreeChecksExecutor
from app.modules.delivery.executors.symphony_bridge import SymphonyBridgeExecutor
from app.modules.delivery.deployments.webhook import WebhookDeployClient
from app.modules.delivery.enums import (
    CodingTaskStatus,
    DeliveryRiskLevel,
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
from app.modules.delivery.gates import gate_engine
from app.modules.delivery.merge_requests.github import GitHubPullRequestClient
from app.modules.delivery.merge_requests.gitlab import GitLabMergeRequestClient
from app.modules.delivery.models import CodingTask, DemandItem, DeployRecord, ExecutionRun, MergeRequestRecord, RepoContext
from app.modules.delivery.provider_credentials import ProviderCredential, resolve_provider_credential
from app.modules.delivery.providers.base import SpecDraft
from app.modules.delivery.providers.dify import DifyWorkflowProvider
from app.modules.delivery.providers.factory import get_workflow_provider
from app.modules.delivery.providers.local import LocalWorkflowProvider
from app.modules.delivery.providers.openai import OpenAIWorkflowProvider
from app.modules.delivery.redaction import REDACTED, redact_text, redact_value
from app.modules.delivery.repository import delivery_repository
from app.modules.delivery.service import DeliveryService, delivery_service
from app.modules.delivery.trace_backfill import backfill_delivery_trace_ids
from app.modules.secrets.provider_health import check_remote_provider_health
from app.modules.secrets.service import secret_store_service
from scripts import deployment_sync_worker
from scripts.database_backup import backup_database, normalize_database_url_for_cli, sqlite_path_from_url
from scripts.database_restore import RESTORE_CONFIRMATION, restore_database
from scripts.recover_symphony_runs import recover_expired_runs
from scripts.seed_delivery_capacity import seed_capacity_data, validate_safety, workload_status
from scripts.symphony_worker import Worker, quote_arg, run_loop, tail


def test_delivery_v2_low_risk_auto_approval_rule():
    risk_level = delivery_service._classify_risk(
        "Add a compact execution status badge to the delivery dashboard."
    )
    confidence = delivery_service._estimate_confidence(
        "Add a compact execution status badge to the delivery dashboard."
    )
    status = delivery_service._decide_spec_status(
        risk_level=risk_level,
        confidence_score=confidence,
        auto_approve_low_risk=True,
    )

    assert risk_level == DeliveryRiskLevel.L1
    assert confidence >= 0.7
    assert status == SpecStatus.APPROVED


def test_json_log_formatter_outputs_structured_context():
    formatter = JsonLogFormatter()
    record = logging.LogRecord(
        name="ai_pjm.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="delivery event",
        args=(),
        exc_info=None,
    )
    record.trace_id = "trace-123"
    record.project_id = 42

    payload = json.loads(formatter.format(record))

    assert payload["level"] == "INFO"
    assert payload["logger"] == "ai_pjm.test"
    assert payload["message"] == "delivery event"
    assert payload["trace_id"] == "trace-123"
    assert payload["project_id"] == 42
    assert "timestamp" in payload


def test_delivery_v2_high_risk_requires_manual_review_rule():
    risk_level = delivery_service._classify_risk(
        "Change login permission logic and migrate production user tokens."
    )
    confidence = delivery_service._estimate_confidence(
        "Change login permission logic and migrate production user tokens."
    )
    status = delivery_service._decide_spec_status(
        risk_level=risk_level,
        confidence_score=confidence,
        auto_approve_low_risk=True,
    )

    assert risk_level == DeliveryRiskLevel.L2
    assert confidence >= 0.7
    assert status == SpecStatus.MANUAL_REVIEW


def test_delivery_v2_execution_gate_blocks_draft_task():
    decision = gate_engine.evaluate_execution_allowed(
        coding_task_id=1,
        coding_task_status=CodingTaskStatus.DRAFT,
        risk_level=DeliveryRiskLevel.L1,
    )

    assert decision.status == GateStatus.MANUAL_REQUIRED
    assert decision.evidence["coding_task_status"] == CodingTaskStatus.DRAFT


def test_database_backup_helpers_normalize_database_urls(tmp_path):
    sqlite_file = tmp_path / "app.sqlite"
    sqlite_url = f"sqlite+aiosqlite:///{sqlite_file}"

    assert sqlite_path_from_url(sqlite_url) == sqlite_file
    assert (
        normalize_database_url_for_cli("postgresql+asyncpg://user:pass@127.0.0.1:5432/app")
        == "postgresql://user:pass@127.0.0.1:5432/app"
    )


def test_sqlite_backup_and_restore_creates_safety_copy(tmp_path):
    sqlite_file = tmp_path / "app.sqlite"
    sqlite_file.write_text("before", encoding="utf-8")
    sqlite_url = f"sqlite+aiosqlite:///{sqlite_file}"

    backup_path = backup_database(sqlite_url, output_dir=tmp_path / "backups")
    sqlite_file.write_text("after", encoding="utf-8")
    safety_copy = restore_database(
        sqlite_url,
        backup_file=backup_path,
        confirm=RESTORE_CONFIRMATION,
    )

    assert sqlite_file.read_text(encoding="utf-8") == "before"
    assert safety_copy is not None
    assert safety_copy.read_text(encoding="utf-8") == "after"


def test_database_restore_requires_explicit_confirmation(tmp_path):
    sqlite_file = tmp_path / "app.sqlite"
    backup_file = tmp_path / "backup.sqlite"
    backup_file.write_text("backup", encoding="utf-8")

    with pytest.raises(ValueError, match=RESTORE_CONFIRMATION):
        restore_database(
            f"sqlite+aiosqlite:///{sqlite_file}",
            backup_file=backup_file,
            confirm="wrong",
        )


def test_capacity_seed_safety_requires_confirmation(monkeypatch):
    with pytest.raises(BadRequestException, match="--confirm"):
        validate_safety(confirm=False, allow_production=False)

    monkeypatch.setattr(settings, "environment", "production")
    with pytest.raises(BadRequestException, match="--allow-production"):
        validate_safety(confirm=True, allow_production=False)

    validate_safety(confirm=True, allow_production=True)
    assert workload_status(20)["run_status"] == ExecutionRunStatus.QUEUED
    assert workload_status(13)["run_status"] == ExecutionRunStatus.FAILED


@pytest.mark.asyncio
async def test_capacity_seed_creates_synthetic_delivery_records(db_session):
    project = await auth_repository.create_project(
        db_session,
        key="capacity-seed",
        name="Capacity Seed",
    )

    summary = await seed_capacity_data(
        db_session,
        count=25,
        batch_size=10,
        project_id=project.id,
        prefix="load",
        include_delivery_records=True,
    )

    assert summary["demands"] == 25
    assert summary["execution_runs"] == 25
    assert summary["merge_requests"] == 22
    assert summary["deployments"] == 22
    assert await delivery_repository.count_execution_runs(
        db_session,
        statuses=[ExecutionRunStatus.QUEUED],
        project_ids=[project.id],
    ) == 1
    assert await delivery_repository.count_execution_runs(
        db_session,
        statuses=[ExecutionRunStatus.FAILED],
        project_ids=[project.id],
    ) == 1
    assert await delivery_repository.count_execution_runs(
        db_session,
        statuses=[ExecutionRunStatus.BLOCKED],
        project_ids=[project.id],
    ) == 1
    assert await delivery_repository.count_deploy_records(
        db_session,
        statuses=[DeploymentStatus.DEPLOYED],
        project_ids=[project.id],
    ) == 22


@pytest.mark.asyncio
async def test_delivery_service_adds_same_project_historical_demand_context(db_session):
    service = DeliveryService()
    alpha = await auth_repository.create_project(
        db_session,
        key="history-alpha",
        name="History Alpha",
    )
    beta = await auth_repository.create_project(
        db_session,
        key="history-beta",
        name="History Beta",
    )
    alpha_previous = await service.create_demand(
        db_session,
        raw_input="Add a compact execution status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Delivery status badge",
        project_id=alpha.id,
    )
    beta_previous = await service.create_demand(
        db_session,
        raw_input="Add a compact execution status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Delivery status badge",
        project_id=beta.id,
    )

    demand = await service.create_demand(
        db_session,
        raw_input="Improve the delivery dashboard status badge for execution results.",
        source_type="new_requirement",
        title="Improve delivery status badge",
        context_payload={"files": ["frontend/src/App.tsx"]},
        project_id=alpha.id,
    )

    payload = demand.context_payload or {}
    history = payload["historical_demands"]
    history_ids = [item["id"] for item in history["items"]]

    assert payload["files"] == ["frontend/src/App.tsx"]
    assert history["generated_by"] == "ai_pjm"
    assert history["source"] == "same_project_recent_demands"
    assert alpha_previous.id in history_ids
    assert beta_previous.id not in history_ids
    assert history["items"][0]["similarity_score"] > 0
    assert "raw_input" not in history["items"][0]


@pytest.mark.asyncio
async def test_delivery_service_preserves_explicit_historical_demand_context(db_session):
    service = DeliveryService()
    await service.create_demand(
        db_session,
        raw_input="Add a reusable OpenAI provider quality gate.",
        source_type="new_requirement",
        title="OpenAI quality gate",
    )

    demand = await service.create_demand(
        db_session,
        raw_input="Add another OpenAI provider quality gate check.",
        source_type="new_requirement",
        title="OpenAI quality gate follow-up",
        context_payload={"historical_demands": {"items": [{"id": "manual"}]}},
    )

    payload = demand.context_payload or {}

    assert payload["historical_demands"] == {"items": [{"id": "manual"}]}
    assert payload["generated_historical_demands"]["items"][0]["title"] == "OpenAI quality gate"


@pytest.mark.asyncio
async def test_delivery_trace_id_propagates_across_main_workflow(db_session):
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a trace id to the delivery workflow.",
        source_type="new_requirement",
        title="Trace delivery workflow",
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Trace delivery workflow",
        user_story="As an operator, I can trace delivery work.",
        scope="Trace id propagation.",
        acceptance_criteria=["Trace id is visible."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    gate = await delivery_repository.create_gate_check(
        db_session,
        demand_id=demand.id,
        gate_type=GateType.SPEC_READY,
        status=GateStatus.PASSED,
    )
    repo_context = await delivery_repository.create_repo_context(
        db_session,
        demand_id=demand.id,
        status=RepoContextStatus.READY,
        provider="local",
        summary="Trace context.",
        source_refs=["workspace.root"],
        discovered_files=["backend/app/modules/delivery/models.py"],
        dependency_refs=["backend/pyproject.toml"],
        confidence_score=0.9,
    )
    impact = await delivery_repository.create_impact_analysis(
        db_session,
        demand_id=demand.id,
        repo_context_id=repo_context.id,
        status=ImpactAnalysisStatus.READY,
        provider="local",
        summary="Trace impact.",
        impacted_areas=["backend/app/modules/delivery"],
        affected_files=["backend/app/modules/delivery/models.py"],
        recommendations=["Run delivery unit tests."],
        risk_level=DeliveryRiskLevel.L1,
        confidence_score=0.9,
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Trace delivery workflow",
        task_prompt="Add trace id propagation.",
        allowed_paths=["backend/app/modules/delivery"],
        forbidden_actions=[],
        required_checks=["python -m pytest tests/test_delivery_v2_units.py -q"],
        expected_evidence=["command_results"],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
    )
    log = await delivery_repository.create_execution_log(
        db_session,
        execution_run_id=run.id,
        level=ExecutionLogLevel.INFO,
        message="Trace log.",
    )
    merge_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="local",
        status=MergeRequestStatus.REVIEW_PASSED,
        review_status=ReviewStatus.PASSED,
        title="Trace delivery workflow",
        source_branch="codex/trace",
        target_branch="main",
    )
    deploy_record = await delivery_repository.create_deploy_record(
        db_session,
        merge_request_id=merge_request.id,
        coding_task_id=task.id,
        provider="local",
        status=DeploymentStatus.DEPLOYED,
        environment="test",
    )
    verification = await delivery_repository.create_verification_record(
        db_session,
        deploy_record_id=deploy_record.id,
        status=VerificationStatus.PASSED,
    )

    assert demand.trace_id
    assert {
        spec.trace_id,
        gate.trace_id,
        repo_context.trace_id,
        impact.trace_id,
        task.trace_id,
        run.trace_id,
        log.trace_id,
        merge_request.trace_id,
        deploy_record.trace_id,
        verification.trace_id,
    } == {demand.trace_id}

    trace_detail = await DeliveryService().get_trace_detail(db_session, demand.trace_id)
    stages = [event["stage"] for event in trace_detail["timeline"]]

    assert trace_detail["trace_id"] == demand.trace_id
    assert trace_detail["demand_id"] == demand.id
    assert trace_detail["counts"]["timeline_events"] == 11
    assert trace_detail["counts"]["execution_logs"] == 1
    assert stages == [
        "demand",
        "spec",
        "gate",
        "context",
        "impact",
        "task",
        "execution",
        "execution_log",
        "merge_request",
        "deployment",
        "verification",
    ]
    assert trace_detail["timeline"][7]["summary"] == "Trace log."


@pytest.mark.asyncio
async def test_delivery_trace_id_backfill_restores_historical_records(db_session):
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Backfill old delivery trace ids.",
        source_type="new_requirement",
        title="Trace backfill",
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Trace backfill",
        user_story="As an operator, I can backfill trace ids.",
        scope="Backfill historical rows.",
        acceptance_criteria=["Old rows receive trace ids."],
        constraints=[],
        risks=[],
        open_questions=[],
    )
    gate = await delivery_repository.create_gate_check(
        db_session,
        demand_id=demand.id,
        gate_type=GateType.SPEC_READY,
        status=GateStatus.PASSED,
    )
    repo_context = await delivery_repository.create_repo_context(
        db_session,
        demand_id=demand.id,
        status=RepoContextStatus.READY,
        provider="local",
        summary="Backfill context.",
        source_refs=[],
        discovered_files=[],
        dependency_refs=[],
        confidence_score=0.9,
    )
    impact = await delivery_repository.create_impact_analysis(
        db_session,
        demand_id=demand.id,
        repo_context_id=repo_context.id,
        status=ImpactAnalysisStatus.READY,
        provider="local",
        summary="Backfill impact.",
        impacted_areas=[],
        affected_files=[],
        recommendations=[],
        risk_level=DeliveryRiskLevel.L1,
        confidence_score=0.9,
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Trace backfill",
        task_prompt="Backfill trace ids.",
        allowed_paths=[],
        forbidden_actions=[],
        required_checks=[],
        expected_evidence=[],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
    )
    log = await delivery_repository.create_execution_log(
        db_session,
        execution_run_id=run.id,
        level=ExecutionLogLevel.INFO,
        message="Backfill log.",
    )
    merge_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="local",
        status=MergeRequestStatus.REVIEW_PASSED,
        review_status=ReviewStatus.PASSED,
        title="Trace backfill",
        source_branch="codex/backfill-trace",
        target_branch="main",
    )
    deploy_record = await delivery_repository.create_deploy_record(
        db_session,
        merge_request_id=merge_request.id,
        coding_task_id=task.id,
        provider="local",
        status=DeploymentStatus.DEPLOYED,
        environment="test",
    )
    verification = await delivery_repository.create_verification_record(
        db_session,
        deploy_record_id=deploy_record.id,
        status=VerificationStatus.PASSED,
    )

    historical_rows = [
        demand,
        spec,
        gate,
        repo_context,
        impact,
        task,
        run,
        log,
        merge_request,
        deploy_record,
        verification,
    ]
    for row in historical_rows:
        row.trace_id = None
    await db_session.flush()

    dry_run = await backfill_delivery_trace_ids(db_session, dry_run=True)

    assert dry_run.dry_run is True
    assert dry_run.total_updated == len(historical_rows)
    assert all(row.trace_id is None for row in historical_rows)

    result = await backfill_delivery_trace_ids(db_session)

    assert result.dry_run is False
    assert result.total_updated == len(historical_rows)
    assert demand.trace_id
    assert {row.trace_id for row in historical_rows} == {demand.trace_id}


@pytest.mark.asyncio
async def test_delivery_service_manual_retry_records_retry_context_and_reuses_active_run(db_session):
    project = await auth_repository.create_project(
        db_session,
        key="retry-context-project",
        name="Retry Context Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Retry a failed task with traceable context.",
        source_type="new_requirement",
        title="Retry context",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Retry context",
        user_story="As an operator, I can trace manual retries.",
        scope="Execution retry evidence.",
        acceptance_criteria=["Retry context is recorded."],
        constraints=["Do not duplicate active runs."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.BLOCKED,
        title="Retry context task",
        task_prompt="Retry with evidence.",
        allowed_paths=["backend/app"],
        forbidden_actions=[],
        required_checks=["python -m compileall app"],
        expected_evidence=["retry context"],
    )
    source_run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.FAILED,
        executor_type="codex",
        trigger_mode="manual",
        result_summary="Required checks failed.",
        evidence_json={
            "dispatch": {
                "check_results": [
                    {"command": "python -m compileall app", "status": "failed", "exit_code": 1}
                ]
            }
        },
    )
    await db_session.commit()

    service = DeliveryService()
    retried = await service.retry_coding_task_execution(
        db_session,
        task.id,
        executor_type="symphony",
    )

    assert retried.status == ExecutionRunStatus.QUEUED
    assert retried.trigger_mode == "manual_retry"
    retry_context = retried.evidence_json["execution_allowed"]["retry_context"]
    assert retry_context["source_run_id"] == source_run.id
    assert retry_context["source_status"] == ExecutionRunStatus.FAILED
    assert retry_context["source_trigger_mode"] == "manual"
    assert retry_context["source_summary"] == "Required checks failed."
    assert retry_context["retry_chain"] == [source_run.id]

    duplicate_retry = await service.retry_coding_task_execution(
        db_session,
        task.id,
        executor_type="symphony",
    )

    assert duplicate_retry.id == retried.id


@pytest.mark.asyncio
async def test_recover_symphony_runs_marks_expired_running_runs_failed(db_session):
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Recover expired Symphony run.",
        source_type="new_requirement",
        title="Recover expired run",
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Recover expired run",
        user_story="As an operator, expired worker leases are recovered.",
        scope="Queue recovery.",
        acceptance_criteria=["Expired running run is failed."],
        constraints=[],
        risks=[],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.RUNNING,
        title="Recover expired run",
        task_prompt="Recover expired run.",
        allowed_paths=[],
        forbidden_actions=[],
        required_checks=[],
        expected_evidence=[],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.RUNNING,
        executor_type="symphony",
        trigger_mode="manual",
        evidence_json={
            "symphony_bridge": {
                "worker_id": "worker-expired",
                "lease_expires_at": (utc_now() - timedelta(minutes=5)).isoformat(),
            }
        },
    )

    summary = await recover_expired_runs(db_session, limit=10)

    assert summary["recovered_count"] == 1
    assert summary["recovered_run_ids"] == [run.id]
    assert run.status == ExecutionRunStatus.FAILED
    assert task.status == CodingTaskStatus.BLOCKED
    assert run.evidence_json["symphony_bridge"]["status"] == "lease_expired"


def test_symphony_executor_is_deferred_queue_adapter():
    executor = get_execution_executor("symphony")

    assert isinstance(executor, SymphonyBridgeExecutor)
    assert executor.deferred is True


def test_delivery_redacts_sensitive_text_patterns():
    raw = (
        "Authorization: Bearer sk-test-abcdefghijklmnopqrstuvwxyz\n"
        "DIFY_API_KEY=project-dify-key-123456\n"
        "codex exec --token local-token-123456 --password bad-password\n"
        "https://dify.local/run?access_token=access-token-123456&x=1\n"
        "glpat-abcdefghijklmnopqrstuvwxyz"
    )

    redacted = redact_text(raw)

    assert "sk-test-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "project-dify-key-123456" not in redacted
    assert "local-token-123456" not in redacted
    assert "bad-password" not in redacted
    assert "access-token-123456" not in redacted
    assert "glpat-abcdefghijklmnopqrstuvwxyz" not in redacted
    assert REDACTED in redacted


def test_delivery_redacts_sensitive_json_values_recursively():
    payload = {
        "api_key": "project-dify-key",
        "api_key_secret_name": "dify_api_key",
        "nested": {
            "command": "codex exec --api-key sk-proj-abcdefghijklmnopqrstuvwxyz",
            "stdout_tail": "token=local-token-123456",
        },
        "items": ["Authorization: Bearer bearer-token-1234567890"],
    }

    redacted = redact_value(payload)

    assert redacted["api_key"] == REDACTED
    assert redacted["api_key_secret_name"] == "dify_api_key"
    assert "sk-proj-abcdefghijklmnopqrstuvwxyz" not in redacted["nested"]["command"]
    assert "local-token-123456" not in redacted["nested"]["stdout_tail"]
    assert "bearer-token-1234567890" not in redacted["items"][0]


def test_symphony_worker_runs_required_checks_and_completes(tmp_path):
    command = (
        f'"{sys.executable}" -c '
        '"from pathlib import Path; Path(\'worker-output.txt\').write_text(\'ok\', encoding=\'utf-8\')"'
    )

    class FakeBridgeClient:
        def __init__(self):
            self.posts = []

        def get(self, path, query=None):
            if path == "/internal/symphony/execution-runs":
                return {"data": [{"id": 7}]}
            if path == "/internal/symphony/execution-runs/7/task-package":
                return {
                    "data": {
                        "run_id": 7,
                        "coding_task_id": 11,
                        "demand_id": 13,
                        "risk_level": "L1",
                        "task_prompt": "Write a worker output probe.",
                        "allowed_paths": ["backend/app"],
                        "forbidden_actions": ["Do not edit secrets."],
                        "required_checks": [command],
                        "expected_evidence": ["command_results"],
                    }
                }
            raise AssertionError(f"Unexpected GET {path}")

        def post(self, path, payload):
            self.posts.append((path, payload))
            return {"data": {}}

    client = FakeBridgeClient()
    worker = Worker(
        client=client,
        worker_id="worker-unit",
        workspace=tmp_path,
        runtime_dir=tmp_path / ".runtime",
        runner_command="",
        timeout_seconds=30,
        lease_seconds=60,
        skip_required_checks=False,
        status_file=tmp_path / ".runtime" / "worker-status.json",
    )

    assert worker.run_once() is True
    status = json.loads((tmp_path / ".runtime" / "worker-status.json").read_text(encoding="utf-8"))
    assert status["state"] == "succeeded"
    assert status["run_id"] == 7
    assert (tmp_path / "worker-output.txt").read_text(encoding="utf-8") == "ok"
    complete_payload = [
        payload
        for path, payload in client.posts
        if path == "/internal/symphony/execution-runs/7/complete"
    ][0]
    assert complete_payload["status"] == "succeeded"
    result = complete_payload["evidence"]["command_results"][0]
    assert result["command"] == command
    assert result["command_type"] == "required_check"
    assert result["status"] == "passed"
    assert result["cwd"] == str(tmp_path)
    prompt = (tmp_path / ".runtime" / "7" / "task-prompt.md").read_text(encoding="utf-8")
    assert "## Allowed Paths" in prompt
    assert "- backend/app" in prompt
    assert command in prompt


def test_symphony_worker_formats_quoted_runner_placeholders(tmp_path):
    worker = Worker(
        client=None,
        worker_id="worker-unit",
        workspace=tmp_path / "workspace with spaces",
        runtime_dir=tmp_path / ".runtime",
        runner_command=(
            "runner --workspace {workspace_q} --prompt {task_prompt_file_q} "
            "--raw {task_package_file}"
        ),
        timeout_seconds=30,
        lease_seconds=60,
        skip_required_checks=False,
    )

    formatted = worker._format_command(
        7,
        {
            "task_package_file": str(tmp_path / "package with spaces.json"),
            "task_prompt_file": str(tmp_path / "prompt with spaces.md"),
        },
    )

    assert f"--workspace {quote_arg(str(tmp_path / 'workspace with spaces'))}" in formatted
    assert f"--prompt {quote_arg(str(tmp_path / 'prompt with spaces.md'))}" in formatted
    assert f"--raw {tmp_path / 'package with spaces.json'}" in formatted


def test_symphony_worker_writes_idle_status(tmp_path):
    class FakeBridgeClient:
        def get(self, path, query=None):
            assert path == "/internal/symphony/execution-runs"
            return {"data": []}

    status_file = tmp_path / ".runtime" / "worker-status.json"
    worker = Worker(
        client=FakeBridgeClient(),
        worker_id="worker-unit",
        workspace=tmp_path,
        runtime_dir=tmp_path / ".runtime",
        runner_command="",
        timeout_seconds=30,
        lease_seconds=60,
        skip_required_checks=False,
        status_file=status_file,
    )

    assert worker.run_once() is False
    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert status["state"] == "idle"
    assert status["run_id"] is None


def test_symphony_worker_loop_continues_after_unexpected_error():
    class FakeWorker:
        def __init__(self):
            self.calls = 0
            self.statuses = []

        def run_once(self):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("temporary API outage")
            return False

        def _write_status(self, state, run_id=None, message=None):
            self.statuses.append({"state": state, "run_id": run_id, "message": message})

    sleeps: list[int] = []
    worker = FakeWorker()

    exit_code = run_loop(
        worker,
        poll_seconds=5,
        sleep_func=sleeps.append,
        max_iterations=2,
    )

    assert exit_code == 0
    assert worker.calls == 2
    assert sleeps == [5, 5]
    assert worker.statuses[0]["state"] == "error"
    assert "temporary API outage" in worker.statuses[0]["message"]


def test_symphony_worker_loop_fail_fast_exits_after_unexpected_error():
    class FakeWorker:
        def __init__(self):
            self.statuses = []

        def run_once(self):
            raise RuntimeError("bad worker config")

        def _write_status(self, state, run_id=None, message=None):
            self.statuses.append({"state": state, "run_id": run_id, "message": message})

    sleeps: list[int] = []
    worker = FakeWorker()

    exit_code = run_loop(
        worker,
        poll_seconds=5,
        fail_fast=True,
        sleep_func=sleeps.append,
        max_iterations=2,
    )

    assert exit_code == 1
    assert sleeps == []
    assert worker.statuses[0]["state"] == "error"


@pytest.mark.asyncio
async def test_deployment_sync_worker_writes_success_status(tmp_path):
    captured: dict[str, object] = {}

    async def fake_sync(limit, project_ids):
        captured["limit"] = limit
        captured["project_ids"] = project_ids
        return {
            "scanned": 1,
            "synced_count": 1,
            "error_count": 0,
            "synced": [SimpleNamespace(id=9)],
            "errors": [],
        }

    status_file = tmp_path / "deployment-sync-status.json"
    summary = await deployment_sync_worker.run_once(
        limit=3,
        project_ids=[11],
        status_file=status_file,
        sync_func=fake_sync,
    )

    status = json.loads(status_file.read_text(encoding="utf-8"))
    assert captured == {"limit": 3, "project_ids": [11]}
    assert summary["synced_ids"] == [9]
    assert status["state"] == "succeeded"
    assert status["synced_ids"] == [9]


def test_symphony_worker_records_command_timeout(tmp_path, monkeypatch):
    class FakeBridgeClient:
        def __init__(self):
            self.posts = []

        def post(self, path, payload):
            self.posts.append((path, payload))
            return {"data": {}}

    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd=args[0],
            timeout=1,
            output=b"\xffstdout",
            stderr=b"\xffstderr",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    worker = Worker(
        client=FakeBridgeClient(),
        worker_id="worker-unit",
        workspace=tmp_path,
        runtime_dir=tmp_path / ".runtime",
        runner_command="",
        timeout_seconds=1,
        lease_seconds=60,
        skip_required_checks=False,
    )

    result = worker._run_command(7, "example command", "runner_command")

    assert result.status == "failed"
    assert result.exit_code == -1
    assert result.error == "Timed out after 1 seconds."
    assert "stdout" in result.stdout_tail
    assert "stderr" in result.stderr_tail


def test_symphony_worker_tail_decodes_bytes():
    assert "text" in tail(b"\xfftext")


def test_local_check_result_evidence_is_redacted():
    executor = LocalChecksExecutor()
    result = CheckResult(
        command="python -m pytest --api-key sk-proj-abcdefghijklmnopqrstuvwxyz",
        cwd="C:/repo",
        status="failed",
        exit_code=1,
        duration_ms=12,
        stdout_tail=executor._tail("Authorization: Bearer bearer-token-1234567890"),
        stderr_tail=executor._tail("password=bad-password"),
        error="token=local-token-123456",
    )

    evidence = executor._check_to_dict(result)

    assert "sk-proj-abcdefghijklmnopqrstuvwxyz" not in evidence["command"]
    assert "bearer-token-1234567890" not in evidence["stdout_tail"]
    assert "bad-password" not in evidence["stderr_tail"]
    assert "local-token-123456" not in evidence["error"]
    assert REDACTED in evidence["command"]


def test_delivery_v2_repo_context_gate_uses_confidence_threshold():
    decision = gate_engine.evaluate_repo_context(
        repo_context_id=1,
        confidence_score=0.55,
        source_refs=["demand.raw_input"],
    )

    assert decision.status == GateStatus.MANUAL_REQUIRED


def test_delivery_v2_dify_provider_resolves_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ai_workflow_provider", "dify")
    monkeypatch.setattr(settings, "dify_api_base_url", "http://dify.local")
    monkeypatch.setattr(settings, "dify_api_key", "test-key")
    monkeypatch.setattr(settings, "dify_spec_workflow_id", "spec-flow")
    monkeypatch.setattr(settings, "dify_impact_workflow_id", "impact-flow")

    provider = get_workflow_provider()

    assert isinstance(provider, DifyWorkflowProvider)
    assert provider.name == "dify"


def test_delivery_v2_openai_provider_resolves_when_configured(monkeypatch):
    monkeypatch.setattr(settings, "ai_workflow_provider", "openai")

    provider = get_workflow_provider()

    assert isinstance(provider, OpenAIWorkflowProvider)
    assert provider.name == "openai"


def test_delivery_v2_dify_provider_requires_base_config(monkeypatch):
    monkeypatch.setattr(settings, "dify_api_base_url", "")
    monkeypatch.setattr(settings, "dify_api_key", "")

    with pytest.raises(AIServiceException, match="DIFY_API_BASE_URL"):
        DifyWorkflowProvider()._require_base_config()


def test_delivery_v2_dify_provider_accepts_injected_api_key(monkeypatch):
    monkeypatch.setattr(settings, "dify_api_base_url", "http://dify.local")
    monkeypatch.setattr(settings, "dify_api_key", "")

    provider = DifyWorkflowProvider(
        api_key="project-dify-key",
        credential_source="secret_store",
        credential_project_id=123,
        api_key_secret_name="dify_api_key",
    )

    provider._require_base_config()
    assert provider._api_key() == "project-dify-key"
    assert provider._credential_metadata() == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "api_key_secret_name": "dify_api_key",
    }


def test_delivery_v2_dify_provider_rejects_invalid_risk_level():
    provider = DifyWorkflowProvider()

    with pytest.raises(AIServiceException, match="risk_level"):
        provider._risk_level("critical")


def test_delivery_v2_openai_provider_requires_base_config(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_base_url", "")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openai_model", "")

    with pytest.raises(AIServiceException, match="OPENAI_API_BASE_URL"):
        OpenAIWorkflowProvider()._require_base_config()


def test_delivery_v2_openai_provider_accepts_injected_api_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_base_url", "https://api.openai.example/v1")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")

    provider = OpenAIWorkflowProvider(
        api_key="project-openai-key",
        credential_source="secret_store",
        credential_project_id=123,
        api_key_secret_name="openai_api_key",
    )

    provider._require_base_config()
    assert provider._api_key() == "project-openai-key"
    assert provider._credential_metadata() == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "api_key_secret_name": "openai_api_key",
    }


def test_delivery_v2_openai_provider_rejects_invalid_risk_level():
    provider = OpenAIWorkflowProvider()

    with pytest.raises(AIServiceException, match="risk_level"):
        provider._risk_level("critical")


@pytest.mark.asyncio
async def test_dify_remote_health_probe_requires_explicit_safe_url(monkeypatch):
    monkeypatch.setattr(settings, "dify_health_check_url", "")

    result = await check_remote_provider_health("dify", "project-dify-key")

    assert result.status == "unknown"
    assert result.remote_probe is False
    assert "DIFY_HEALTH_CHECK_URL" in result.reason


@pytest.mark.asyncio
async def test_github_remote_health_probe_uses_bearer_token(monkeypatch):
    monkeypatch.setattr(settings, "github_api_base_url", "https://api.github.example")
    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("app.modules.secrets.provider_health.httpx.AsyncClient", FakeAsyncClient)

    result = await check_remote_provider_health("github", "project-github-token")

    assert result.status == "healthy"
    assert result.remote_probe is True
    assert result.endpoint == "github.user"
    assert captured["url"] == "https://api.github.example/user"
    assert captured["headers"]["Authorization"] == "Bearer project-github-token"


@pytest.mark.asyncio
async def test_delivery_v2_openai_provider_generates_spec_with_structured_outputs(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_base_url", "https://api.openai.example/v1")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "openai_request_timeout_seconds", 12)
    monkeypatch.setattr(settings, "ai_workflow_provider_schema_version", "test-schema-v1")
    monkeypatch.setattr(settings, "ai_workflow_provider_prompt_version", "test-prompt-v1")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "resp_123",
                "output_text": json.dumps(
                    {
                        "title": "Add status badge",
                        "user_story": "As an operator, I can see execution status.",
                        "scope": "Delivery dashboard status display.",
                        "acceptance_criteria": ["Status badge is visible."],
                        "constraints": ["Do not expose secrets."],
                        "risks": ["Low UI risk."],
                        "open_questions": [],
                    }
                ),
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.providers.openai.httpx.AsyncClient", FakeAsyncClient)
    provider = OpenAIWorkflowProvider(
        api_key="project-openai-key",
        credential_source="secret_store",
        credential_project_id=123,
        api_key_secret_name="openai_api_key",
    )
    demand = DemandItem(
        id=1,
        raw_input="Add a compact execution status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
    )

    spec = await provider.generate_spec(demand)

    assert spec.title == "Add status badge"
    assert spec.provider_metadata == {
        "provider": "openai",
        "model": "gpt-4o-mini",
        "source": "openai_responses_api",
        "schema_name": "ai_pjm_spec_draft",
        "schema_version": "test-schema-v1",
        "prompt_version": "test-prompt-v1",
        "response_id": "resp_123",
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "api_key_secret_name": "openai_api_key",
    }
    assert captured["timeout"] == 12
    assert captured["url"] == "https://api.openai.example/v1/responses"
    assert captured["headers"] == {
        "Authorization": "Bearer project-openai-key",
        "Content-Type": "application/json",
    }
    request_json = captured["json"]
    assert isinstance(request_json, dict)
    assert request_json["model"] == "gpt-4o-mini"
    assert request_json["text"]["format"]["type"] == "json_schema"
    assert request_json["text"]["format"]["name"] == "ai_pjm_spec_draft"
    assert request_json["text"]["format"]["strict"] is True
    assert "project-openai-key" not in str(spec.provider_metadata)


@pytest.mark.asyncio
async def test_delivery_v2_openai_provider_analyzes_impact_from_output_items(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_base_url", "https://api.openai.example/v1")
    monkeypatch.setattr(settings, "openai_api_key", "settings-openai-key")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "ai_workflow_provider_schema_version", "test-schema-v1")
    monkeypatch.setattr(settings, "ai_workflow_provider_prompt_version", "test-prompt-v1")

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "resp_impact",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": json.dumps(
                                    {
                                        "summary": "UI and delivery API are affected.",
                                        "impacted_areas": ["frontend/src/app/pages", "backend/app/modules"],
                                        "affected_files": [
                                            "frontend/src/app/pages/DeliveryV2Page.tsx",
                                        ],
                                        "recommendations": ["Run frontend build."],
                                        "risk_level": "L1",
                                        "confidence_score": 1.2,
                                    }
                                ),
                            }
                        ],
                    }
                ],
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.providers.openai.httpx.AsyncClient", FakeAsyncClient)
    demand = DemandItem(
        id=1,
        raw_input="Update delivery dashboard.",
        source_type="new_requirement",
        title="Update delivery dashboard",
        risk_level=DeliveryRiskLevel.L1,
    )
    repo_context = RepoContext(
        id=2,
        demand_id=1,
        status="ready",
        provider="local",
        summary="local",
        source_refs_json=["workspace.root"],
        discovered_files_json=["frontend/src/app/pages/DeliveryV2Page.tsx"],
        dependency_refs_json=["frontend/package.json:scripts.build"],
        confidence_score=0.9,
        provider_metadata_json={"provider": "local"},
    )

    draft = await OpenAIWorkflowProvider().analyze_impact(demand, None, repo_context)

    assert draft.risk_level == "L1"
    assert draft.confidence_score == 1.0
    assert "frontend/src/app/pages/DeliveryV2Page.tsx" in draft.affected_files
    assert draft.provider_metadata["response_id"] == "resp_impact"
    assert draft.provider_metadata["schema_name"] == "ai_pjm_impact_analysis"
    assert draft.provider_metadata["schema_version"] == "test-schema-v1"
    assert draft.provider_metadata["prompt_version"] == "test-prompt-v1"


@pytest.mark.asyncio
async def test_delivery_service_retries_external_provider_before_success(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ai_workflow_provider_retry_attempts", 2)
    monkeypatch.setattr(settings, "ai_workflow_provider_retry_backoff_seconds", 0)
    monkeypatch.setattr(settings, "ai_workflow_provider_fallback_enabled", True)

    class FlakyOpenAIProvider:
        name = "openai"

        def __init__(self):
            self.attempts = 0

        async def generate_spec(self, demand):
            self.attempts += 1
            if self.attempts == 1:
                raise AIServiceException("temporary provider outage")
            return SpecDraft(
                title="Add status badge",
                user_story="As an operator, I can see execution status.",
                scope="Delivery dashboard status display.",
                acceptance_criteria=["Status badge is visible."],
                constraints=["Do not expose secrets."],
                risks=["Low UI risk."],
                open_questions=[],
                provider_metadata={"provider": self.name},
            )

        async def collect_repo_context(self, demand):
            raise AssertionError("not used")

        async def analyze_impact(self, demand, spec, repo_context):
            raise AssertionError("not used")

        async def create_coding_task(self, demand, spec, allowed_paths, required_checks):
            raise AssertionError("not used")

    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a compact execution status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
    )
    provider = FlakyOpenAIProvider()

    spec = await DeliveryService(provider=provider).generate_spec(db_session, demand.id)
    detail = await delivery_repository.get_demand_detail(db_session, demand.id)
    spec_ready_gate = next(gate for gate in detail.gate_checks if gate.gate_type == GateType.SPEC_READY)
    recovery = spec_ready_gate.evidence_json["provider_metadata"]["provider_recovery"]

    assert provider.attempts == 2
    assert spec.title == "Add status badge"
    assert recovery["fallback_used"] is False
    assert recovery["provider"] == "openai"
    assert recovery["attempts"] == 2
    assert "temporary provider outage" in recovery["previous_errors"][0]["message"]


@pytest.mark.asyncio
async def test_delivery_service_falls_back_to_local_spec_after_external_provider_failure(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "ai_workflow_provider_retry_attempts", 2)
    monkeypatch.setattr(settings, "ai_workflow_provider_retry_backoff_seconds", 0)
    monkeypatch.setattr(settings, "ai_workflow_provider_fallback_enabled", True)

    class FailingOpenAIProvider:
        name = "openai"

        async def generate_spec(self, demand):
            raise AIServiceException("Authorization: Bearer sk-test-abcdefghijklmnopqrstuvwxyz")

        async def collect_repo_context(self, demand):
            raise AssertionError("not used")

        async def analyze_impact(self, demand, spec, repo_context):
            raise AssertionError("not used")

        async def create_coding_task(self, demand, spec, allowed_paths, required_checks):
            raise AssertionError("not used")

    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a compact execution status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
    )

    spec = await DeliveryService(provider=FailingOpenAIProvider()).generate_spec(db_session, demand.id)
    detail = await delivery_repository.get_demand_detail(db_session, demand.id)
    spec_ready_gate = next(gate for gate in detail.gate_checks if gate.gate_type == GateType.SPEC_READY)
    metadata = spec_ready_gate.evidence_json["provider_metadata"]
    recovery = metadata["provider_recovery"]

    assert spec.title == "Add status badge"
    assert spec.created_by == "ai"
    assert any("local rule fallback" in question for question in spec.open_questions_json)
    assert metadata["provider"] == "local"
    assert recovery["fallback_used"] is True
    assert recovery["failed_provider"] == "openai"
    assert recovery["fallback_provider"] == "local"
    assert len(recovery["errors"]) == 2
    assert "sk-test-abcdefghijklmnopqrstuvwxyz" not in str(recovery)
    assert REDACTED in str(recovery)


@pytest.mark.asyncio
async def test_delivery_service_resolves_project_dify_api_key_from_secret_store(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    monkeypatch.setattr(settings, "dify_api_base_url", "http://dify.local")
    monkeypatch.setattr(settings, "dify_api_key", "")
    monkeypatch.setattr(settings, "dify_api_key_secret_name", "dify_api_key")
    monkeypatch.setattr(settings, "dify_spec_workflow_id", "spec-flow")
    monkeypatch.setattr(settings, "ai_workflow_provider_schema_version", "test-schema-v1")
    monkeypatch.setattr(settings, "ai_workflow_provider_prompt_version", "test-prompt-v1")
    project = await auth_repository.create_project(
        db_session,
        key="dify-secret-project",
        name="Dify Secret Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
        project_id=project.id,
    )
    await secret_store_service.create_secret(
        db_session,
        project_id=project.id,
        name="dify_api_key",
        provider="dify",
        value="project-dify-key",
        actor_ref="test",
    )
    captured: dict[str, object] = {}

    async def fake_run_workflow(self, workflow_id, inputs):
        captured["workflow_id"] = workflow_id
        captured["api_key"] = self._api_key()
        captured["credential_metadata"] = self._credential_metadata()
        return {
            "title": "Add status badge",
            "user_story": "As an operator, I can see execution status.",
            "scope": "Delivery dashboard status display.",
            "acceptance_criteria": ["Status badge is visible."],
            "constraints": ["Do not expose secrets."],
            "risks": ["Low UI risk."],
            "open_questions": [],
        }

    monkeypatch.setattr(DifyWorkflowProvider, "_run_workflow", fake_run_workflow)

    spec = await DeliveryService(provider=DifyWorkflowProvider()).generate_spec(db_session, demand.id)

    assert spec.title == "Add status badge"
    assert captured["workflow_id"] == "spec-flow"
    assert captured["api_key"] == "project-dify-key"
    assert captured["credential_metadata"] == {
        "credential_source": "secret_store",
        "credential_project_id": project.id,
        "api_key_secret_name": "dify_api_key",
    }
    assert spec.provider_metadata_json["schema_name"] == "ai_pjm_spec_draft"
    assert spec.provider_metadata_json["schema_version"] == "test-schema-v1"
    assert spec.provider_metadata_json["prompt_version"] == "test-prompt-v1"
    assert spec.provider_metadata_json["quality_evaluation"]["version"] == "provider-quality-v1"
    assert spec.provider_metadata_json["quality_evaluation"]["passed"] is True


@pytest.mark.asyncio
async def test_delivery_service_resolves_project_openai_api_key_from_secret_store(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    monkeypatch.setattr(settings, "openai_api_base_url", "https://api.openai.example/v1")
    monkeypatch.setattr(settings, "openai_api_key", "")
    monkeypatch.setattr(settings, "openai_api_key_secret_name", "openai_api_key")
    monkeypatch.setattr(settings, "openai_model", "gpt-4o-mini")
    monkeypatch.setattr(settings, "ai_workflow_provider_schema_version", "test-schema-v1")
    monkeypatch.setattr(settings, "ai_workflow_provider_prompt_version", "test-prompt-v1")
    project = await auth_repository.create_project(
        db_session,
        key="openai-secret-project",
        name="OpenAI Secret Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
        project_id=project.id,
    )
    await secret_store_service.create_secret(
        db_session,
        project_id=project.id,
        name="openai_api_key",
        provider="openai",
        value="project-openai-key",
        actor_ref="test",
    )
    captured: dict[str, object] = {}

    async def fake_create_structured_response(self, schema_name, schema, system_prompt, user_payload):
        captured["schema_name"] = schema_name
        captured["api_key"] = self._api_key()
        captured["credential_metadata"] = self._credential_metadata()
        return (
            {
                "title": "Add status badge",
                "user_story": "As an operator, I can see execution status.",
                "scope": "Delivery dashboard status display.",
                "acceptance_criteria": ["Status badge is visible."],
                "constraints": ["Do not expose secrets."],
                "risks": ["Low UI risk."],
                "open_questions": [],
            },
            "resp_project",
        )

    monkeypatch.setattr(
        OpenAIWorkflowProvider,
        "_create_structured_response",
        fake_create_structured_response,
    )

    spec = await DeliveryService(provider=OpenAIWorkflowProvider()).generate_spec(db_session, demand.id)

    assert spec.title == "Add status badge"
    assert captured["schema_name"] == "ai_pjm_spec_draft"
    assert captured["api_key"] == "project-openai-key"
    assert captured["credential_metadata"] == {
        "credential_source": "secret_store",
        "credential_project_id": project.id,
        "api_key_secret_name": "openai_api_key",
    }
    assert spec.provider_metadata_json["schema_name"] == "ai_pjm_spec_draft"
    assert spec.provider_metadata_json["schema_version"] == "test-schema-v1"
    assert spec.provider_metadata_json["prompt_version"] == "test-prompt-v1"
    assert spec.provider_metadata_json["quality_evaluation"]["version"] == "provider-quality-v1"
    assert spec.provider_metadata_json["quality_evaluation"]["passed"] is True


@pytest.mark.asyncio
async def test_delivery_provider_credential_prefers_project_secret_store(
    db_session,
    monkeypatch,
):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    project = await auth_repository.create_project(
        db_session,
        key="provider-secret-project",
        name="Provider Secret Project",
    )
    await secret_store_service.create_secret(
        db_session,
        project_id=project.id,
        name="gitlab_token",
        provider="gitlab",
        value="project-gitlab-token",
        actor_ref="test",
    )

    credential = await resolve_provider_credential(
        db_session,
        project_id=project.id,
        provider="gitlab",
        secret_name="gitlab_token",
        settings_value="global-gitlab-token",
    )

    assert credential is not None
    assert credential.value == "project-gitlab-token"
    assert credential.metadata(secret_name_key="token_secret_name") == {
        "credential_source": "secret_store",
        "credential_project_id": project.id,
        "token_secret_name": "gitlab_token",
    }
    assert "project-gitlab-token" not in repr(credential)


@pytest.mark.asyncio
async def test_delivery_provider_credential_falls_back_to_settings(db_session):
    credential = await resolve_provider_credential(
        db_session,
        project_id=None,
        provider="openai",
        secret_name="openai_api_key",
        settings_value="settings-openai-key",
    )

    assert credential is not None
    assert credential.value == "settings-openai-key"
    assert credential.metadata(secret_name_key="api_key_secret_name") == {
        "credential_source": "settings",
    }


@pytest.mark.asyncio
async def test_gitlab_merge_request_client_uses_credential_without_exposing_it(monkeypatch):
    monkeypatch.setattr(settings, "gitlab_api_base_url", "https://gitlab.example/api/v4")
    monkeypatch.setattr(settings, "gitlab_project_id", "group/demo")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": 99,
                "iid": 12,
                "web_url": "https://gitlab.example/group/demo/-/merge_requests/12",
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.merge_requests.gitlab.httpx.AsyncClient", FakeAsyncClient)
    credential = ProviderCredential(
        provider="gitlab",
        value="project-gitlab-token",
        source="secret_store",
        project_id=123,
        secret_name="gitlab_token",
    )
    task = CodingTask(id=11, demand_id=1, spec_card_id=2, title="Add status badge", task_prompt="Do it")
    run = ExecutionRun(id=7, coding_task_id=11, branch_name="codex/status-badge", commit_sha="abc123")

    draft = await GitLabMergeRequestClient(credential=credential).create_merge_request(
        task=task,
        run=run,
        title="Add status badge",
        description="Generated delivery summary.",
        source_branch="codex/status-badge",
        target_branch="main",
    )

    assert captured["url"] == "https://gitlab.example/api/v4/projects/group%2Fdemo/merge_requests"
    assert captured["headers"] == {"PRIVATE-TOKEN": "project-gitlab-token"}
    assert captured["json"] == {
        "source_branch": "codex/status-badge",
        "target_branch": "main",
        "title": "Add status badge",
        "description": "Generated delivery summary.",
        "remove_source_branch": False,
    }
    assert draft.provider == "gitlab"
    assert draft.external_id == "12"
    assert draft.url == "https://gitlab.example/group/demo/-/merge_requests/12"
    assert draft.evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "token_secret_name": "gitlab_token",
    }
    assert "project-gitlab-token" not in str(draft.evidence)


@pytest.mark.asyncio
async def test_gitlab_merge_request_client_applies_reviewers_assignees_and_labels(monkeypatch):
    monkeypatch.setattr(settings, "gitlab_api_base_url", "https://gitlab.example/api/v4")
    monkeypatch.setattr(settings, "gitlab_project_id", "group/demo")
    monkeypatch.setattr(settings, "gitlab_default_labels", "ai-pjm, delivery")
    monkeypatch.setattr(settings, "gitlab_reviewer_ids", "101, 102")
    monkeypatch.setattr(settings, "gitlab_assignee_ids", "201")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": 99,
                "iid": 12,
                "web_url": "https://gitlab.example/group/demo/-/merge_requests/12",
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.merge_requests.gitlab.httpx.AsyncClient", FakeAsyncClient)
    credential = ProviderCredential(
        provider="gitlab",
        value="project-gitlab-token",
        source="secret_store",
        project_id=123,
        secret_name="gitlab_token",
    )
    task = CodingTask(id=11, demand_id=1, spec_card_id=2, title="Add status badge", task_prompt="Do it")
    run = ExecutionRun(id=7, coding_task_id=11, branch_name="codex/status-badge", commit_sha="abc123")

    draft = await GitLabMergeRequestClient(credential=credential).create_merge_request(
        task=task,
        run=run,
        title="Add status badge",
        description="Generated delivery summary.",
        source_branch="codex/status-badge",
        target_branch="main",
    )

    assert captured["json"]["labels"] == "ai-pjm,delivery"
    assert captured["json"]["reviewer_ids"] == [101, 102]
    assert captured["json"]["assignee_ids"] == [201]
    assert draft.evidence["labels"] == ["ai-pjm", "delivery"]
    assert draft.evidence["reviewer_ids"] == [101, 102]
    assert draft.evidence["assignee_ids"] == [201]
    assert "project-gitlab-token" not in str(draft.evidence)


@pytest.mark.asyncio
async def test_gitlab_merge_request_client_fetches_remote_review_and_ci(monkeypatch):
    monkeypatch.setattr(settings, "gitlab_api_base_url", "https://gitlab.example/api/v4")
    monkeypatch.setattr(settings, "gitlab_project_id", "group/demo")
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers, params=None):
            requests.append({"url": url, "headers": headers, "params": params})
            if url.endswith("/merge_requests/12"):
                return FakeResponse(
                    {
                        "state": "opened",
                        "detailed_merge_status": "mergeable",
                        "web_url": "https://gitlab.example/group/demo/-/merge_requests/12",
                    }
                )
            if url.endswith("/merge_requests/12/discussions"):
                return FakeResponse(
                    [
                        {
                            "id": "discussion-1",
                            "notes": [
                                {
                                    "id": 100,
                                    "body": "Fix the failing build before merging.",
                                    "author": {"username": "reviewer"},
                                    "created_at": "2026-05-25T06:00:00Z",
                                    "resolvable": True,
                                    "resolved": False,
                                    "system": False,
                                    "url": "https://gitlab.example/note/100",
                                }
                            ],
                        }
                    ]
                )
            if "/repository/commits/abc123/statuses" in url:
                return FakeResponse(
                    [
                        {
                            "name": "unit",
                            "status": "failed",
                            "target_url": "https://gitlab.example/jobs/1",
                        }
                    ]
                )
            raise AssertionError(f"Unexpected GitLab URL: {url}")

    monkeypatch.setattr("app.modules.delivery.merge_requests.gitlab.httpx.AsyncClient", FakeAsyncClient)
    credential = ProviderCredential(
        provider="gitlab",
        value="project-gitlab-token",
        source="secret_store",
        project_id=123,
        secret_name="gitlab_token",
    )
    record = MergeRequestRecord(
        id=19,
        coding_task_id=11,
        execution_run_id=7,
        provider="gitlab",
        title="Add status badge",
        source_branch="codex/status-badge",
        target_branch="main",
        external_id="12",
        evidence_json={"provider_evidence": {"gitlab_merge_request_iid": "12"}},
    )

    review = await GitLabMergeRequestClient(credential=credential).fetch_remote_review(
        record=record,
        commit_sha="abc123",
    )

    assert [request["headers"] for request in requests] == [{"PRIVATE-TOKEN": "project-gitlab-token"}] * 3
    assert requests[1]["params"] == {"per_page": 100}
    assert review.status == MergeRequestStatus.REVIEW_BLOCKED
    assert review.review_status == ReviewStatus.BLOCKING
    assert "2 blocking issue" in review.summary
    assert review.comments[0]["author"] == "reviewer"
    assert "Fix the failing build" in review.blocking_issues[0]
    assert "CI status unit is failed." in review.blocking_issues
    assert review.evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "token_secret_name": "gitlab_token",
    }
    assert "project-gitlab-token" not in str(review.evidence)


@pytest.mark.asyncio
async def test_github_pull_request_client_creates_pr_and_applies_metadata(monkeypatch):
    monkeypatch.setattr(settings, "github_api_base_url", "https://api.github.example")
    monkeypatch.setattr(settings, "github_repository", "org/demo")
    monkeypatch.setattr(settings, "github_default_labels", "ai-pjm, delivery")
    monkeypatch.setattr(settings, "github_reviewers", "alice,bob")
    monkeypatch.setattr(settings, "github_assignees", "carol")
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            requests.append({"url": url, "headers": headers, "json": json})
            if url.endswith("/pulls"):
                return FakeResponse(
                    {
                        "id": 1001,
                        "number": 42,
                        "html_url": "https://github.example/org/demo/pull/42",
                    }
                )
            return FakeResponse({})

    monkeypatch.setattr("app.modules.delivery.merge_requests.github.httpx.AsyncClient", FakeAsyncClient)
    credential = ProviderCredential(
        provider="github",
        value="project-github-token",
        source="secret_store",
        project_id=123,
        secret_name="github_token",
    )
    task = CodingTask(id=11, demand_id=1, spec_card_id=2, title="Add status badge", task_prompt="Do it")
    run = ExecutionRun(id=7, coding_task_id=11, branch_name="codex/status-badge", commit_sha="abc123")

    draft = await GitHubPullRequestClient(credential=credential).create_merge_request(
        task=task,
        run=run,
        title="Add status badge",
        description="Generated delivery summary.",
        source_branch="codex/status-badge",
        target_branch="main",
    )

    auth_headers = [request["headers"]["Authorization"] for request in requests]
    assert auth_headers == ["Bearer project-github-token"] * 4
    assert requests[0]["url"] == "https://api.github.example/repos/org/demo/pulls"
    assert requests[0]["json"] == {
        "head": "codex/status-badge",
        "base": "main",
        "title": "Add status badge",
        "body": "Generated delivery summary.",
        "draft": False,
    }
    assert requests[1]["url"].endswith("/issues/42/labels")
    assert requests[1]["json"] == {"labels": ["ai-pjm", "delivery"]}
    assert requests[2]["url"].endswith("/pulls/42/requested_reviewers")
    assert requests[2]["json"] == {"reviewers": ["alice", "bob"]}
    assert requests[3]["url"].endswith("/issues/42/assignees")
    assert requests[3]["json"] == {"assignees": ["carol"]}
    assert draft.provider == "github"
    assert draft.external_id == "42"
    assert draft.url == "https://github.example/org/demo/pull/42"
    assert draft.evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "token_secret_name": "github_token",
    }
    assert draft.evidence["labels"] == ["ai-pjm", "delivery"]
    assert draft.evidence["reviewers"] == ["alice", "bob"]
    assert draft.evidence["assignees"] == ["carol"]
    assert "project-github-token" not in str(draft.evidence)


@pytest.mark.asyncio
async def test_github_pull_request_client_fetches_remote_review_and_checks(monkeypatch):
    monkeypatch.setattr(settings, "github_api_base_url", "https://api.github.example")
    monkeypatch.setattr(settings, "github_repository", "org/demo")
    requests: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers, params=None):
            requests.append({"url": url, "headers": headers, "params": params})
            if url.endswith("/pulls/42"):
                return FakeResponse(
                    {
                        "state": "open",
                        "draft": False,
                        "merged": False,
                        "mergeable": True,
                        "html_url": "https://github.example/org/demo/pull/42",
                    }
                )
            if url.endswith("/pulls/42/comments"):
                return FakeResponse(
                    [
                        {
                            "id": 501,
                            "body": "Please adjust this line.",
                            "user": {"login": "reviewer"},
                            "created_at": "2026-05-25T06:00:00Z",
                            "html_url": "https://github.example/comment/501",
                        }
                    ]
                )
            if url.endswith("/issues/42/comments"):
                return FakeResponse(
                    [
                        {
                            "id": 502,
                            "body": "CI should be green before merge.",
                            "user": {"login": "maintainer"},
                            "created_at": "2026-05-25T06:02:00Z",
                            "html_url": "https://github.example/comment/502",
                        }
                    ]
                )
            if url.endswith("/pulls/42/reviews"):
                return FakeResponse(
                    [
                        {
                            "id": 601,
                            "state": "CHANGES_REQUESTED",
                            "body": "Fix the failing check before merging.",
                            "user": {"login": "reviewer"},
                            "submitted_at": "2026-05-25T06:03:00Z",
                            "html_url": "https://github.example/review/601",
                        }
                    ]
                )
            if url.endswith("/commits/abc123/check-runs"):
                return FakeResponse(
                    {
                        "check_runs": [
                            {
                                "id": 701,
                                "name": "unit",
                                "status": "completed",
                                "conclusion": "failure",
                                "html_url": "https://github.example/check/701",
                                "completed_at": "2026-05-25T06:04:00Z",
                            }
                        ]
                    }
                )
            if url.endswith("/commits/abc123/status"):
                return FakeResponse({"state": "success", "total_count": 1, "statuses": []})
            raise AssertionError(f"Unexpected GitHub URL: {url}")

    monkeypatch.setattr("app.modules.delivery.merge_requests.github.httpx.AsyncClient", FakeAsyncClient)
    credential = ProviderCredential(
        provider="github",
        value="project-github-token",
        source="secret_store",
        project_id=123,
        secret_name="github_token",
    )
    record = MergeRequestRecord(
        id=19,
        coding_task_id=11,
        execution_run_id=7,
        provider="github",
        title="Add status badge",
        source_branch="codex/status-badge",
        target_branch="main",
        external_id="42",
        evidence_json={"provider_evidence": {"github_pull_request_number": "42"}},
    )

    review = await GitHubPullRequestClient(credential=credential).fetch_remote_review(
        record=record,
        commit_sha="abc123",
    )

    assert [request["headers"]["Authorization"] for request in requests] == ["Bearer project-github-token"] * 6
    assert requests[1]["params"] == {"per_page": 100}
    assert review.status == MergeRequestStatus.REVIEW_BLOCKED
    assert review.review_status == ReviewStatus.BLOCKING
    assert "2 blocking issue" in review.summary
    assert len(review.comments) == 2
    assert review.comments[0]["author"] == "reviewer"
    assert "Fix the failing check" in review.blocking_issues[0]
    assert "GitHub check unit concluded failure." in review.blocking_issues
    assert review.evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "token_secret_name": "github_token",
    }
    assert review.evidence["check_runs"][0]["name"] == "unit"
    assert "project-github-token" not in str(review.evidence)


@pytest.mark.asyncio
async def test_delivery_service_handles_gitlab_pipeline_webhook(db_session, monkeypatch):
    monkeypatch.setattr(settings, "gitlab_webhook_secret_token", "webhook-secret")
    project = await auth_repository.create_project(
        db_session,
        key="gitlab-webhook",
        name="GitLab Webhook",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Handle GitLab webhook.",
        source_type="new_requirement",
        title="GitLab webhook",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="GitLab webhook",
        user_story="As an operator, GitLab webhook updates MR review state.",
        scope="MR sync",
        acceptance_criteria=["Webhook updates existing MR."],
        constraints=[],
        risks=[],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="GitLab webhook task",
        task_prompt="Handle GitLab webhook.",
        allowed_paths=["backend/app"],
        forbidden_actions=[],
        required_checks=[],
        expected_evidence=[],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
    )
    merge_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="gitlab",
        status=MergeRequestStatus.REVIEWING,
        review_status=ReviewStatus.PENDING,
        title="GitLab webhook",
        source_branch="codex/gitlab-webhook",
        target_branch="main",
        external_id="12",
        url="https://gitlab.example/group/demo/-/merge_requests/12",
    )
    await db_session.commit()

    result = await DeliveryService().handle_gitlab_webhook(
        db_session,
        payload={
            "object_kind": "pipeline",
            "object_attributes": {
                "status": "success",
            },
            "merge_request": {
                "iid": 12,
            },
        },
        token="webhook-secret",
    )

    assert result["processed"] is True
    updated = result["merge_request"]
    assert updated.id == merge_request.id
    assert updated.status == MergeRequestStatus.REVIEW_PASSED
    assert updated.review_status == ReviewStatus.PASSED
    assert updated.review_summary == "GitLab webhook reported pipeline success."
    assert updated.evidence_json["gitlab_webhook"]["last_event"]["status"] == "success"

    detail = await delivery_repository.get_demand_detail(db_session, demand.id)
    review_gates = [gate for gate in detail.gate_checks if gate.gate_type == GateType.REVIEW_PASSED]
    assert review_gates[-1].status == GateStatus.PASSED

    audit_events = await audit_repository.list_events(
        db_session,
        project_id=project.id,
        action="delivery.merge_request_gitlab_webhook_received",
    )
    assert audit_events
    assert audit_events[0].actor_ref == "gitlab-webhook"


@pytest.mark.asyncio
async def test_delivery_service_handles_github_check_run_webhook(db_session, monkeypatch):
    monkeypatch.setattr(settings, "github_webhook_secret", "github-webhook-secret")
    project = await auth_repository.create_project(
        db_session,
        key="github-webhook",
        name="GitHub Webhook",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Handle GitHub webhook.",
        source_type="new_requirement",
        title="GitHub webhook",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="GitHub webhook",
        user_story="As an operator, GitHub webhook updates PR review state.",
        scope="PR sync",
        acceptance_criteria=["Webhook updates existing PR."],
        constraints=[],
        risks=[],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="GitHub webhook task",
        task_prompt="Handle GitHub webhook.",
        allowed_paths=["backend/app"],
        forbidden_actions=[],
        required_checks=[],
        expected_evidence=[],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
    )
    pull_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="github",
        status=MergeRequestStatus.REVIEWING,
        review_status=ReviewStatus.PENDING,
        title="GitHub webhook",
        source_branch="codex/github-webhook",
        target_branch="main",
        external_id="42",
        url="https://github.example/org/demo/pull/42",
    )
    await db_session.commit()

    payload = {
        "action": "completed",
        "check_run": {
            "name": "unit",
            "status": "completed",
            "conclusion": "success",
            "pull_requests": [{"number": 42}],
        },
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(
        b"github-webhook-secret",
        body,
        hashlib.sha256,
    ).hexdigest()

    result = await DeliveryService().handle_github_webhook(
        db_session,
        payload=payload,
        signature=signature,
        event_type="check_run",
        body=body,
    )

    assert result["processed"] is True
    updated = result["merge_request"]
    assert updated.id == pull_request.id
    assert updated.status == MergeRequestStatus.REVIEW_PASSED
    assert updated.review_status == ReviewStatus.PASSED
    assert updated.review_summary == "GitHub webhook reported check unit success."
    assert updated.evidence_json["github_webhook"]["last_event"]["conclusion"] == "success"
    assert updated.reviewed_by_ref == "github-webhook"

    detail = await delivery_repository.get_demand_detail(db_session, demand.id)
    review_gates = [gate for gate in detail.gate_checks if gate.gate_type == GateType.REVIEW_PASSED]
    assert review_gates[-1].status == GateStatus.PASSED

    audit_events = await audit_repository.list_events(
        db_session,
        project_id=project.id,
        action="delivery.merge_request_github_webhook_received",
    )
    assert audit_events
    assert audit_events[0].actor_ref == "github-webhook"


@pytest.mark.asyncio
async def test_webhook_deploy_client_uses_credential_without_exposing_it(monkeypatch):
    monkeypatch.setattr(settings, "deploy_webhook_url", "https://deploy.example/hooks/test")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "deploy-123",
                "url": "https://test.example/deploy-123",
                "status_url": "https://deploy.example/status/deploy-123",
                "status": "deployed",
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.deployments.webhook.httpx.AsyncClient", FakeAsyncClient)
    credential = ProviderCredential(
        provider="webhook",
        value="project-deploy-token",
        source="secret_store",
        project_id=123,
        secret_name="deploy_token",
    )
    task = CodingTask(id=11, demand_id=1, spec_card_id=2, title="Add status badge", task_prompt="Do it")
    merge_request = MergeRequestRecord(
        id=19,
        coding_task_id=11,
        execution_run_id=7,
        provider="gitlab",
        title="Add status badge",
        source_branch="codex/status-badge",
        target_branch="main",
        url="https://gitlab.example/group/demo/-/merge_requests/12",
        evidence_json={"commit_sha": "abc123"},
    )

    draft = await WebhookDeployClient(credential=credential).create_deployment(
        task=task,
        merge_request=merge_request,
        environment="test",
    )

    assert captured["url"] == "https://deploy.example/hooks/test"
    assert captured["headers"] == {"Authorization": "Bearer project-deploy-token"}
    assert captured["json"]["commit_sha"] == "abc123"
    assert draft.provider == "webhook"
    assert draft.url == "https://test.example/deploy-123"
    assert draft.evidence["status_url"] == "https://deploy.example/status/deploy-123"
    assert draft.evidence["raw_status"] == "deployed"
    assert draft.evidence["normalized_status"] == "deployed"
    assert draft.evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "token_secret_name": "deploy_token",
    }
    assert "project-deploy-token" not in str(draft.evidence)


@pytest.mark.asyncio
async def test_webhook_deploy_client_fetches_status_without_exposing_credential(monkeypatch):
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "success",
                "url": "https://test.example/deploy-123",
                "summary": "Deployment completed.",
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.deployments.webhook.httpx.AsyncClient", FakeAsyncClient)
    credential = ProviderCredential(
        provider="webhook",
        value="project-deploy-token",
        source="secret_store",
        project_id=123,
        secret_name="deploy_token",
    )
    deploy_record = DeployRecord(
        id=21,
        merge_request_id=19,
        coding_task_id=11,
        provider="webhook",
        status=DeploymentStatus.PENDING,
        environment="test",
        evidence_json={"provider_evidence": {"status_url": "https://deploy.example/status/deploy-123"}},
    )

    remote_status = await WebhookDeployClient(credential=credential).fetch_deployment_status(
        deploy_record=deploy_record,
    )

    assert captured["url"] == "https://deploy.example/status/deploy-123"
    assert captured["headers"] == {"Authorization": "Bearer project-deploy-token"}
    assert remote_status.status == DeploymentStatus.DEPLOYED
    assert remote_status.url == "https://test.example/deploy-123"
    assert remote_status.summary == "Deployment completed."
    assert remote_status.evidence["raw_status"] == "success"
    assert remote_status.evidence["normalized_status"] == "deployed"
    assert remote_status.evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "token_secret_name": "deploy_token",
    }
    assert "project-deploy-token" not in str(remote_status.evidence)


def test_webhook_deploy_client_normalizes_common_ci_cd_status_shapes():
    credential = ProviderCredential(
        provider="webhook",
        value="project-deploy-token",
        source="secret_store",
        project_id=123,
        secret_name="deploy_token",
    )
    client = WebhookDeployClient(credential=credential, webhook_url="https://deploy.example/hooks/test")

    assert client._status({"state": "timed_out"}) == DeploymentStatus.FAILED
    assert client._status({"result": "green"}) == DeploymentStatus.DEPLOYED
    assert client._status({"conclusion": "cancelled"}) == DeploymentStatus.FAILED
    assert client._status({"pipeline": {"status": "manual"}}) == DeploymentStatus.PENDING
    assert client._status({"deployment": {"detailed_status": "available"}}) == DeploymentStatus.DEPLOYED
    assert client._status({"pipeline": {"jobs": [{"name": "build", "status": "success"}, {"name": "deploy", "status": "running"}]}}) == DeploymentStatus.PENDING
    assert client._status({"stages": [{"name": "build", "status": "success"}, {"name": "deploy", "state": "failed"}]}) == DeploymentStatus.FAILED
    assert client._status({"workflow_run": {"conclusion": "success"}}) == DeploymentStatus.DEPLOYED


@pytest.mark.asyncio
async def test_webhook_deploy_client_extracts_nested_ci_cd_status_evidence(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "platform": "gitlab",
                "pipeline": {
                    "jobs": [
                        {"name": "build", "status": "success", "web_url": "https://ci.example/jobs/1"},
                        {"name": "deploy", "status": "failed", "web_url": "https://ci.example/jobs/2"},
                    ]
                },
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers):
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.deployments.webhook.httpx.AsyncClient", FakeAsyncClient)
    credential = ProviderCredential(
        provider="webhook",
        value="project-deploy-token",
        source="secret_store",
        project_id=123,
        secret_name="deploy_token",
    )
    deploy_record = DeployRecord(
        id=22,
        merge_request_id=19,
        coding_task_id=11,
        provider="webhook",
        status=DeploymentStatus.PENDING,
        environment="test",
        evidence_json={"provider_evidence": {"status_url": "https://deploy.example/status/deploy-123"}},
    )

    remote_status = await WebhookDeployClient(credential=credential).fetch_deployment_status(
        deploy_record=deploy_record,
    )

    assert remote_status.status == DeploymentStatus.FAILED
    assert remote_status.evidence["status_platform"] == "gitlab"
    assert remote_status.evidence["raw_status"] == "failed"
    assert remote_status.evidence["status_path"] == "pipeline.jobs[1].status"
    assert remote_status.evidence["status_item"] == "deploy"
    assert remote_status.evidence["failed_status_items"] == [
        {
            "name": "deploy",
            "raw_status": "failed",
            "normalized_status": "failed",
            "path": "pipeline.jobs[1].status",
            "url": "https://ci.example/jobs/2",
        }
    ]
    assert "project-deploy-token" not in str(remote_status.evidence)


@pytest.mark.asyncio
async def test_delivery_service_creates_gitlab_merge_request_with_project_secret(
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    monkeypatch.setattr(settings, "gitlab_api_base_url", "https://gitlab.example/api/v4")
    monkeypatch.setattr(settings, "gitlab_project_id", "group/demo")
    monkeypatch.setattr(settings, "gitlab_token", "")
    monkeypatch.setattr(settings, "gitlab_token_secret_name", "gitlab_token")
    monkeypatch.setattr(settings, "merge_request_auto_push_enabled", True)
    monkeypatch.setattr(settings, "merge_request_git_remote", "origin")
    monkeypatch.setattr(settings, "delivery_app_base_url", "https://ai-pjm.example")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": 99,
                "iid": 12,
                "web_url": "https://gitlab.example/group/demo/-/merge_requests/12",
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.merge_requests.gitlab.httpx.AsyncClient", FakeAsyncClient)
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    def fake_git_push(self, path, remote, source_branch):
        captured["git_push"] = {
            "path": str(path),
            "remote": remote,
            "source_branch": source_branch,
        }
        return subprocess.CompletedProcess(
            args=["git", "push"],
            returncode=0,
            stdout="branch pushed",
            stderr="",
        )

    monkeypatch.setattr(DeliveryService, "_run_git_push", fake_git_push)
    project = await auth_repository.create_project(
        db_session,
        key="gitlab-secret-project",
        name="GitLab Secret Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
        project_id=project.id,
    )
    await secret_store_service.create_secret(
        db_session,
        project_id=project.id,
        name="gitlab_token",
        provider="gitlab",
        value="project-gitlab-token",
        actor_ref="test",
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Add status badge",
        user_story="As an operator, I can see delivery status.",
        scope="Dashboard badge only.",
        acceptance_criteria=["Badge is visible."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Add status badge",
        task_prompt="Add a compact execution status badge.",
        allowed_paths=["frontend/src/app/pages/DeliveryV2Page.tsx"],
        forbidden_actions=["Do not expose secrets."],
        required_checks=["npm run build"],
        expected_evidence=["build output"],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
        result_summary="Implemented.",
        evidence_json={"dispatch": {"branch_name": "codex/status-badge", "commit_sha": "abc123"}},
    )
    await delivery_repository.update_execution_run(
        db_session,
        run,
        worktree_path=str(worktree_path),
        branch_name="codex/status-badge",
        commit_sha="abc123",
    )
    await db_session.commit()

    record = await DeliveryService().create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        provider="gitlab",
    )

    assert captured["git_push"] == {
        "path": str(worktree_path),
        "remote": "origin",
        "source_branch": "codex/status-badge",
    }
    assert captured["headers"] == {"PRIVATE-TOKEN": "project-gitlab-token"}
    description = captured["json"]["description"]
    assert "Demand ID" in description
    assert "Execution run ID" in description
    assert "npm run build" in description
    assert "### Evidence Links" in description
    assert "[Demand #" in description
    assert "https://ai-pjm.example/?demand_id=" in description
    assert "tab=execution" in description
    assert "project-gitlab-token" not in description
    assert record.provider == "gitlab"
    assert record.external_id == "12"
    assert record.url == "https://gitlab.example/group/demo/-/merge_requests/12"
    provider_evidence = record.evidence_json["provider_evidence"]
    assert record.evidence_json["git_push"] == {
        "enabled": True,
        "provider": "gitlab",
        "remote": "origin",
        "branch": "codex/status-badge",
        "timeout_seconds": settings.merge_request_push_timeout_seconds,
        "stdout_tail": "branch pushed",
        "stderr_tail": "",
    }
    assert record.evidence_json["evidence_links"]["demand"]["url"].startswith(
        f"https://ai-pjm.example/?demand_id={demand.id}"
    )
    assert record.evidence_json["evidence_links"]["execution"]["url"].endswith("tab=execution")
    assert record.evidence_json["evidence_links"]["task_package"]["label"] == f"Task package #{task.id}"
    assert provider_evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": project.id,
        "token_secret_name": "gitlab_token",
    }
    assert "project-gitlab-token" not in str(record.evidence_json)


@pytest.mark.asyncio
async def test_delivery_service_creates_github_pull_request_with_project_secret(
    db_session,
    monkeypatch,
    tmp_path,
):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    monkeypatch.setattr(settings, "github_api_base_url", "https://api.github.example")
    monkeypatch.setattr(settings, "github_repository", "org/demo")
    monkeypatch.setattr(settings, "github_token", "")
    monkeypatch.setattr(settings, "github_token_secret_name", "github_token")
    monkeypatch.setattr(settings, "merge_request_auto_push_enabled", True)
    monkeypatch.setattr(settings, "merge_request_git_remote", "origin")
    monkeypatch.setattr(settings, "delivery_app_base_url", "https://ai-pjm.example")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": 1001,
                "number": 42,
                "html_url": "https://github.example/org/demo/pull/42",
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, headers, json):
            captured["url"] = url
            captured["headers"] = headers
            captured["json"] = json
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.merge_requests.github.httpx.AsyncClient", FakeAsyncClient)
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    def fake_git_push(self, path, remote, source_branch):
        captured["git_push"] = {
            "path": str(path),
            "remote": remote,
            "source_branch": source_branch,
        }
        return subprocess.CompletedProcess(
            args=["git", "push"],
            returncode=0,
            stdout="branch pushed",
            stderr="",
        )

    monkeypatch.setattr(DeliveryService, "_run_git_push", fake_git_push)
    project = await auth_repository.create_project(
        db_session,
        key="github-secret-project",
        name="GitHub Secret Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
        project_id=project.id,
    )
    await secret_store_service.create_secret(
        db_session,
        project_id=project.id,
        name="github_token",
        provider="github",
        value="project-github-token",
        actor_ref="test",
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Add status badge",
        user_story="As an operator, I can see delivery status.",
        scope="Dashboard badge only.",
        acceptance_criteria=["Badge is visible."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Add status badge",
        task_prompt="Add a compact execution status badge.",
        allowed_paths=["frontend/src/app/pages/DeliveryV2Page.tsx"],
        forbidden_actions=["Do not expose secrets."],
        required_checks=["npm run build"],
        expected_evidence=["build output"],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
        result_summary="Implemented.",
        evidence_json={"dispatch": {"branch_name": "codex/status-badge", "commit_sha": "abc123"}},
    )
    await delivery_repository.update_execution_run(
        db_session,
        run,
        worktree_path=str(worktree_path),
        branch_name="codex/status-badge",
        commit_sha="abc123",
    )
    await db_session.commit()

    record = await DeliveryService().create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        provider="github",
    )

    assert captured["git_push"] == {
        "path": str(worktree_path),
        "remote": "origin",
        "source_branch": "codex/status-badge",
    }
    assert captured["headers"]["Authorization"] == "Bearer project-github-token"
    assert captured["url"] == "https://api.github.example/repos/org/demo/pulls"
    description = captured["json"]["body"]
    assert "Demand ID" in description
    assert "Execution run ID" in description
    assert "npm run build" in description
    assert "### Evidence Links" in description
    assert "project-github-token" not in description
    assert record.provider == "github"
    assert record.external_id == "42"
    assert record.url == "https://github.example/org/demo/pull/42"
    provider_evidence = record.evidence_json["provider_evidence"]
    assert record.evidence_json["git_push"] == {
        "enabled": True,
        "provider": "github",
        "remote": "origin",
        "branch": "codex/status-badge",
        "timeout_seconds": settings.merge_request_push_timeout_seconds,
        "stdout_tail": "branch pushed",
        "stderr_tail": "",
    }
    assert provider_evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": project.id,
        "token_secret_name": "github_token",
    }
    assert "project-github-token" not in str(record.evidence_json)


@pytest.mark.asyncio
async def test_delivery_service_syncs_gitlab_remote_review_gate_and_audit(db_session, monkeypatch):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    monkeypatch.setattr(settings, "gitlab_api_base_url", "https://gitlab.example/api/v4")
    monkeypatch.setattr(settings, "gitlab_project_id", "group/demo")
    monkeypatch.setattr(settings, "gitlab_token", "")
    monkeypatch.setattr(settings, "gitlab_token_secret_name", "gitlab_token")
    requests: list[str] = []

    class FakeResponse:
        def __init__(self, body):
            self._body = body

        def raise_for_status(self):
            return None

        def json(self):
            return self._body

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers, params=None):
            requests.append(url)
            assert headers == {"PRIVATE-TOKEN": "project-gitlab-token"}
            if url.endswith("/merge_requests/12"):
                return FakeResponse({"state": "opened", "detailed_merge_status": "mergeable"})
            if url.endswith("/merge_requests/12/discussions"):
                return FakeResponse(
                    [
                        {
                            "id": "discussion-1",
                            "notes": [
                                {
                                    "id": 100,
                                    "body": "Fix the failing build before merging.",
                                    "author": {"username": "reviewer"},
                                    "created_at": "2026-05-25T06:00:00Z",
                                    "resolvable": True,
                                    "resolved": False,
                                    "system": False,
                                }
                            ],
                        }
                    ]
                )
            if "/repository/commits/abc123/statuses" in url:
                return FakeResponse([{"name": "unit", "status": "failed"}])
            raise AssertionError(f"Unexpected GitLab URL: {url}")

    monkeypatch.setattr("app.modules.delivery.merge_requests.gitlab.httpx.AsyncClient", FakeAsyncClient)
    project = await auth_repository.create_project(
        db_session,
        key="gitlab-sync-project",
        name="GitLab Sync Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
        project_id=project.id,
    )
    await secret_store_service.create_secret(
        db_session,
        project_id=project.id,
        name="gitlab_token",
        provider="gitlab",
        value="project-gitlab-token",
        actor_ref="test",
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Add status badge",
        user_story="As an operator, I can see delivery status.",
        scope="Dashboard badge only.",
        acceptance_criteria=["Badge is visible."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Add status badge",
        task_prompt="Add a compact execution status badge.",
        allowed_paths=["frontend/src/app/pages/DeliveryV2Page.tsx"],
        forbidden_actions=["Do not expose secrets."],
        required_checks=["npm run build"],
        expected_evidence=["build output"],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
        result_summary="Implemented.",
        evidence_json={"dispatch": {"branch_name": "codex/status-badge", "commit_sha": "abc123"}},
    )
    await delivery_repository.update_execution_run(
        db_session,
        run,
        branch_name="codex/status-badge",
        commit_sha="abc123",
    )
    record = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="gitlab",
        status=MergeRequestStatus.CREATED,
        review_status=ReviewStatus.PENDING,
        title="Add status badge",
        source_branch="codex/status-badge",
        target_branch="main",
        external_id="12",
        url="https://gitlab.example/group/demo/-/merge_requests/12",
        evidence_json={
            "commit_sha": "abc123",
            "provider_evidence": {
                "gitlab_merge_request_iid": "12",
                "credential": {"token_secret_name": "gitlab_token"},
            },
        },
    )
    await db_session.commit()

    synced = await DeliveryService().sync_merge_request_remote_review(
        db_session,
        record.id,
        actor_ref="review-bot",
    )

    assert len(requests) == 3
    assert synced.status == MergeRequestStatus.REVIEW_BLOCKED
    assert synced.review_status == ReviewStatus.BLOCKING
    assert "2 blocking issue" in synced.review_summary
    assert synced.review_comments_json[0]["author"] == "reviewer"
    assert synced.evidence_json["remote_review"]["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": project.id,
        "token_secret_name": "gitlab_token",
    }
    assert "project-gitlab-token" not in str(synced.evidence_json)

    detail = await delivery_repository.get_demand_detail(db_session, demand.id)
    review_gates = [gate for gate in detail.gate_checks if gate.gate_type == GateType.REVIEW_PASSED]
    assert review_gates[-1].status == GateStatus.FAILED
    assert review_gates[-1].evidence_json["blocking_issues"]

    audit_events = await audit_repository.list_events(
        db_session,
        project_id=project.id,
        action="delivery.merge_request_remote_review_synced",
    )
    assert audit_events
    assert audit_events[0].actor_ref == "review-bot"


@pytest.mark.asyncio
async def test_delivery_service_auto_repairs_blocking_merge_request_review(db_session):
    project = await auth_repository.create_project(
        db_session,
        key="review-repair-project",
        name="Review Repair Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Add status badge",
        user_story="As an operator, I can see delivery status.",
        scope="Dashboard badge only.",
        acceptance_criteria=["Badge is visible."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Add status badge",
        task_prompt="Add a compact execution status badge.",
        allowed_paths=["frontend/src/app/pages/DeliveryV2Page.tsx"],
        forbidden_actions=["Do not expose secrets."],
        required_checks=["npm run build"],
        expected_evidence=["build output"],
    )
    source_run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
        result_summary="Implemented.",
        evidence_json={"dispatch": {"branch_name": "codex/status-badge", "commit_sha": "abc123"}},
    )
    record = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=source_run.id,
        provider="gitlab",
        status=MergeRequestStatus.REVIEW_BLOCKED,
        review_status=ReviewStatus.BLOCKING,
        title="Add status badge",
        source_branch="codex/status-badge",
        target_branch="main",
        external_id="12",
        url="https://gitlab.example/group/demo/-/merge_requests/12",
        review_summary="GitLab review sync found 1 blocking issue(s).",
        review_comments=[{"body": "Fix the failing build before merging."}],
        evidence_json={
            "remote_review": {
                "blocking_issues": ["Fix the failing build before merging."],
            },
        },
    )
    await db_session.commit()

    service = DeliveryService()
    pushed: dict[str, object] = {}

    async def fake_dispatch(db, execution_run_id):
        run = await delivery_repository.get_execution_run(db, execution_run_id)
        await delivery_repository.update_execution_run(
            db,
            run,
            status=ExecutionRunStatus.SUCCEEDED,
            result_summary="Review issue fixed.",
            evidence_json={
                **(run.evidence_json or {}),
                "dispatch": {
                    "check_results": [{"command": "npm run build", "status": "passed", "exit_code": 0}],
                    "changed_files": ["frontend/src/app/pages/DeliveryV2Page.tsx"],
                },
            },
        )
        await db.commit()
        loaded = await delivery_repository.get_execution_run(db, execution_run_id)
        assert loaded is not None
        return loaded

    async def fake_push_repair(*, provider, record, run):
        pushed["provider"] = provider
        pushed["merge_request_id"] = record.id
        pushed["repair_run_id"] = run.id
        return {
            "enabled": True,
            "provider": "gitlab",
            "remote": "origin",
            "source_branch": "codex/repaired",
            "target_branch": record.source_branch,
            "stdout_tail": "pushed",
            "stderr_tail": "",
        }

    service.dispatch_execution_run = fake_dispatch
    service._push_repair_run_to_merge_request = fake_push_repair

    repair_runs = await service.auto_repair_merge_request_review(
        db_session,
        record.id,
        actor_ref="operator",
    )

    assert len(repair_runs) == 1
    repair_run = repair_runs[0]
    assert repair_run.status == ExecutionRunStatus.SUCCEEDED
    assert repair_run.trigger_mode == "auto_repair"
    repair_context = repair_run.evidence_json["repair_context"]
    assert repair_context["source"] == "merge_request_review"
    assert repair_context["source_run_id"] == source_run.id
    assert repair_context["source_merge_request_id"] == record.id
    assert repair_context["review_issues"] == ["Fix the failing build before merging."]
    assert pushed == {
        "provider": "gitlab",
        "merge_request_id": record.id,
        "repair_run_id": repair_run.id,
    }

    updated_record = await delivery_repository.get_merge_request_record(db_session, record.id)
    assert updated_record.status == MergeRequestStatus.REVIEWING
    assert updated_record.review_status == ReviewStatus.PENDING
    assert updated_record.evidence_json["latest_repair_run_id"] == repair_run.id
    assert updated_record.evidence_json["latest_repair_push"]["target_branch"] == "codex/status-badge"

    audit_events = await audit_repository.list_events(
        db_session,
        project_id=project.id,
        entity_type="merge_request",
    )
    actions = {event.action: event for event in audit_events}
    assert actions["delivery.merge_request_review_repair_started"].actor_ref == "operator"
    assert actions["delivery.merge_request_review_repair_started"].metadata_json["execution_run_ids"] == [repair_run.id]
    assert actions["delivery.merge_request_repair_pushed"].metadata_json["repair_run_id"] == repair_run.id


@pytest.mark.asyncio
async def test_delivery_service_syncs_webhook_deployment_status_gate_and_audit(db_session, monkeypatch):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    monkeypatch.setattr(settings, "deploy_token", "")
    monkeypatch.setattr(settings, "deploy_token_secret_name", "deploy_token")
    captured: dict[str, object] = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "status": "success",
                "url": "https://test.example/deploy-123",
                "summary": "Deployment completed.",
            }

    class FakeAsyncClient:
        def __init__(self, timeout):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def get(self, url, headers):
            captured["url"] = url
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr("app.modules.delivery.deployments.webhook.httpx.AsyncClient", FakeAsyncClient)
    project = await auth_repository.create_project(
        db_session,
        key="deploy-sync-project",
        name="Deploy Sync Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
        project_id=project.id,
    )
    await secret_store_service.create_secret(
        db_session,
        project_id=project.id,
        name="deploy_token",
        provider="webhook",
        value="project-deploy-token",
        actor_ref="test",
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Add status badge",
        user_story="As an operator, I can see delivery status.",
        scope="Dashboard badge only.",
        acceptance_criteria=["Badge is visible."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Add status badge",
        task_prompt="Add a compact execution status badge.",
        allowed_paths=["frontend/src/app/pages/DeliveryV2Page.tsx"],
        forbidden_actions=["Do not expose secrets."],
        required_checks=["npm run build"],
        expected_evidence=["build output"],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
        result_summary="Implemented.",
        evidence_json={"dispatch": {"branch_name": "codex/status-badge", "commit_sha": "abc123"}},
    )
    merge_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="gitlab",
        status=MergeRequestStatus.REVIEW_PASSED,
        review_status=ReviewStatus.PASSED,
        title="Add status badge",
        source_branch="codex/status-badge",
        target_branch="main",
        external_id="12",
        url="https://gitlab.example/group/demo/-/merge_requests/12",
        evidence_json={"commit_sha": "abc123"},
    )
    deploy_record = await delivery_repository.create_deploy_record(
        db_session,
        merge_request_id=merge_request.id,
        coding_task_id=task.id,
        provider="webhook",
        status=DeploymentStatus.PENDING,
        environment="test",
        url=None,
        evidence_json={
            "provider_evidence": {
                "status_url": "https://deploy.example/status/deploy-123",
                "credential": {"token_secret_name": "deploy_token"},
            },
        },
    )
    await db_session.commit()

    synced = await DeliveryService().sync_deploy_record_status(
        db_session,
        deploy_record.id,
        actor_ref="operator",
    )

    assert captured["url"] == "https://deploy.example/status/deploy-123"
    assert captured["headers"] == {"Authorization": "Bearer project-deploy-token"}
    assert synced.status == DeploymentStatus.DEPLOYED
    assert synced.url == "https://test.example/deploy-123"
    assert synced.evidence_json["remote_status"]["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": project.id,
        "token_secret_name": "deploy_token",
    }
    assert "project-deploy-token" not in str(synced.evidence_json)

    detail = await delivery_repository.get_demand_detail(db_session, demand.id)
    deploy_gates = [gate for gate in detail.gate_checks if gate.gate_type == GateType.TEST_DEPLOYED]
    assert deploy_gates[-1].status == GateStatus.PASSED

    audit_events = await audit_repository.list_events(
        db_session,
        project_id=project.id,
        action="delivery.test_deployment_status_synced",
    )
    assert audit_events
    assert audit_events[0].actor_ref == "operator"

    second_deploy_record = await delivery_repository.create_deploy_record(
        db_session,
        merge_request_id=merge_request.id,
        coding_task_id=task.id,
        provider="webhook",
        status=DeploymentStatus.PENDING,
        environment="test",
        url=None,
        evidence_json={
            "provider_evidence": {
                "status_url": "https://deploy.example/status/deploy-456",
                "credential": {"token_secret_name": "deploy_token"},
            },
        },
    )
    await db_session.commit()

    batch = await DeliveryService().sync_pending_deploy_records(
        db_session,
        limit=10,
        project_ids=[project.id],
        actor_ref="worker",
    )

    assert batch["scanned"] == 1
    assert batch["synced_count"] == 1
    assert batch["error_count"] == 0
    assert batch["synced"][0].id == second_deploy_record.id
    assert batch["synced"][0].status == DeploymentStatus.DEPLOYED


@pytest.mark.asyncio
async def test_delivery_service_records_deployment_environment_config_and_logs(db_session, monkeypatch):
    monkeypatch.setattr(
        settings,
        "deploy_environment_config_json",
        json.dumps(
            {
                "test": {
                    "url": "https://test.example/app",
                    "log_url": "https://ci.example/jobs/42",
                    "description": "Shared test environment",
                }
            }
        ),
    )
    project = await auth_repository.create_project(
        db_session,
        key="deploy-env-project",
        name="Deploy Env Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add deployment environment config.",
        source_type="new_requirement",
        title="Deployment env config",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Deployment env config",
        user_story="As an operator, I can see deployment config evidence.",
        scope="Deployment evidence.",
        acceptance_criteria=["Deployment config is recorded."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Deployment env config",
        task_prompt="Record deployment config.",
        allowed_paths=["backend/app/modules/delivery"],
        forbidden_actions=[],
        required_checks=[],
        expected_evidence=[],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
    )
    merge_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="local",
        status=MergeRequestStatus.REVIEW_PASSED,
        review_status=ReviewStatus.PASSED,
        title="Deployment env config",
        source_branch="codex/deploy-env",
        target_branch="main",
    )

    deploy_record = await DeliveryService().create_deploy_record(
        db_session,
        merge_request.id,
        provider="local",
        environment="test",
        actor_ref="operator",
    )

    assert deploy_record.trace_id == demand.trace_id
    assert deploy_record.url == "https://test.example/app"
    assert deploy_record.evidence_json["deployment_config"] == {
        "environment": "test",
        "source": "DEPLOY_ENVIRONMENT_CONFIG_JSON",
        "url": "https://test.example/app",
        "log_url": "https://ci.example/jobs/42",
        "description": "Shared test environment",
    }
    assert deploy_record.evidence_json["deployment_logs"] == {
        "configured_log_url": "https://ci.example/jobs/42",
    }


@pytest.mark.asyncio
async def test_delivery_service_prefers_project_deployment_environment_config(db_session, monkeypatch):
    monkeypatch.setattr(
        settings,
        "deploy_environment_config_json",
        json.dumps(
            {
                "test": {
                    "url": "https://global.example/app",
                    "log_url": "https://ci.example/global",
                    "description": "Global test environment",
                }
            }
        ),
    )
    project = await auth_repository.create_project(
        db_session,
        key="project-deploy-env",
        name="Project Deploy Env",
    )
    await auth_repository.update_project(
        db_session,
        project,
        settings_json={
            "delivery": {
                "deployment_environments": {
                    "test": {
                        "url": "https://project.example/app",
                        "log_url": "https://ci.example/project",
                        "description": "Project test environment",
                        "environment_name": "Project Test",
                    }
                }
            }
        },
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Use project deployment environment config.",
        source_type="new_requirement",
        title="Project deployment env config",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Project deployment env config",
        user_story="As an operator, project deployment config overrides global defaults.",
        scope="Deployment evidence.",
        acceptance_criteria=["Project deployment config is recorded."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Project deployment env config",
        task_prompt="Record project deployment config.",
        allowed_paths=["backend/app/modules/delivery"],
        forbidden_actions=[],
        required_checks=[],
        expected_evidence=[],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
    )
    merge_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="local",
        status=MergeRequestStatus.REVIEW_PASSED,
        review_status=ReviewStatus.PASSED,
        title="Project deployment env config",
        source_branch="codex/project-deploy-env",
        target_branch="main",
    )

    deploy_record = await DeliveryService().create_deploy_record(
        db_session,
        merge_request.id,
        provider="local",
        environment="test",
        actor_ref="operator",
    )

    assert deploy_record.url == "https://project.example/app"
    assert deploy_record.evidence_json["deployment_config"] == {
        "environment": "test",
        "source": "project_settings",
        "url": "https://project.example/app",
        "log_url": "https://ci.example/project",
        "description": "Project test environment",
        "environment_name": "Project Test",
    }
    assert deploy_record.evidence_json["deployment_logs"] == {
        "configured_log_url": "https://ci.example/project",
    }


@pytest.mark.asyncio
async def test_delivery_service_redeploys_failed_deployment_with_source_evidence(db_session):
    project = await auth_repository.create_project(
        db_session,
        key="redeploy-project",
        name="Redeploy Project",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add a status badge to the delivery dashboard.",
        source_type="new_requirement",
        title="Add status badge",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Add status badge",
        user_story="As an operator, I can see delivery status.",
        scope="Dashboard badge only.",
        acceptance_criteria=["Badge is visible."],
        constraints=["Do not expose secrets."],
        risks=["Low risk."],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.COMPLETED,
        title="Add status badge",
        task_prompt="Add a compact execution status badge.",
        allowed_paths=["frontend/src/app/pages/DeliveryV2Page.tsx"],
        forbidden_actions=["Do not expose secrets."],
        required_checks=["npm run build"],
        expected_evidence=["build output"],
    )
    run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.SUCCEEDED,
        executor_type="codex",
        trigger_mode="manual",
        result_summary="Implemented.",
        evidence_json={"dispatch": {"branch_name": "codex/status-badge", "commit_sha": "abc123"}},
    )
    merge_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=run.id,
        provider="local",
        status=MergeRequestStatus.REVIEW_PASSED,
        review_status=ReviewStatus.PASSED,
        title="Add status badge",
        source_branch="codex/status-badge",
        target_branch="main",
        external_id="12",
        url="local://merge-requests/12",
        evidence_json={"commit_sha": "abc123"},
    )
    failed_deploy = await delivery_repository.create_deploy_record(
        db_session,
        merge_request_id=merge_request.id,
        coding_task_id=task.id,
        provider="local",
        status=DeploymentStatus.FAILED,
        environment="test",
        url="local://deployments/failed",
        evidence_json={"reason": "previous deployment failed"},
    )
    await db_session.commit()

    redeployed = await DeliveryService().redeploy_deploy_record(
        db_session,
        failed_deploy.id,
        actor_ref="operator",
    )

    assert redeployed.id != failed_deploy.id
    assert redeployed.merge_request_id == merge_request.id
    assert redeployed.provider == "local"
    assert redeployed.environment == "test"
    assert redeployed.status == DeploymentStatus.DEPLOYED
    assert redeployed.url == f"local://deployments/{redeployed.id}"
    assert redeployed.evidence_json["redeploy_from_deploy_record_id"] == failed_deploy.id
    assert redeployed.evidence_json["redeployed_by_ref"] == "operator"

    detail = await delivery_repository.get_demand_detail(db_session, demand.id)
    deploy_gates = [gate for gate in detail.gate_checks if gate.gate_type == GateType.TEST_DEPLOYED]
    assert deploy_gates[-1].status == GateStatus.PASSED

    audit_events = await audit_repository.list_events(
        db_session,
        project_id=project.id,
        action="delivery.test_deployment_redeployed",
    )
    assert audit_events
    assert audit_events[0].actor_ref == "operator"
    assert audit_events[0].metadata_json["source_deploy_record_id"] == failed_deploy.id
    assert audit_events[0].metadata_json["new_deploy_record_id"] == redeployed.id


@pytest.mark.asyncio
async def test_delivery_service_observability_summary_reports_core_alerts(db_session, monkeypatch):
    monkeypatch.setattr(settings, "secret_store_master_key", "test-secret-master-key")
    monkeypatch.setattr(settings, "observability_queue_backlog_threshold", 2)

    project = await auth_repository.create_project(
        db_session,
        key="observability",
        name="Observability",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Add alert summary.",
        source_type="new_requirement",
        title="Alert summary",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Alert summary",
        user_story="As an operator, I can see operational alerts.",
        scope="Observability",
        acceptance_criteria=["Alerts are visible"],
        constraints=[],
        risks=[],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.READY,
        title="Alert task",
        task_prompt="Implement alerts.",
        allowed_paths=["backend/app"],
        forbidden_actions=[],
        required_checks=["python -m compileall app"],
        expected_evidence=["tests"],
    )
    queued_a = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.QUEUED,
        executor_type="symphony",
        trigger_mode="manual",
    )
    queued_b = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.QUEUED,
        executor_type="symphony",
        trigger_mode="manual",
    )
    expired_run = await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.RUNNING,
        executor_type="symphony",
        trigger_mode="manual",
        evidence_json={
            "symphony_bridge": {
                "worker_id": "worker-a",
                "lease_expires_at": (utc_now() - timedelta(minutes=5)).isoformat(),
            }
        },
    )
    merge_request = await delivery_repository.create_merge_request_record(
        db_session,
        coding_task_id=task.id,
        execution_run_id=expired_run.id,
        provider="local",
        status=MergeRequestStatus.REVIEW_PASSED,
        review_status=ReviewStatus.PASSED,
        title="Alert MR",
        source_branch="codex/alerts",
        target_branch="main",
    )
    failed_deploy = await delivery_repository.create_deploy_record(
        db_session,
        merge_request_id=merge_request.id,
        coding_task_id=task.id,
        provider="local",
        status=DeploymentStatus.FAILED,
        environment="test",
        url="local://deployments/failed",
    )
    secret = await secret_store_service.create_secret(
        db_session,
        project_id=project.id,
        name="deploy_token",
        provider="deploy",
        value="deploy-token",
        expires_at=utc_now() - timedelta(days=1),
    )

    summary = await DeliveryService().get_observability_summary(db_session, project_ids=[project.id])

    assert summary["status"] == "critical"
    assert summary["metrics"]["queued_runs"] == 2
    assert summary["metrics"]["running_runs"] == 1
    assert summary["metrics"]["expired_worker_runs"] == 1
    assert summary["metrics"]["failed_deployments"] == 1
    assert summary["metrics"]["unhealthy_secrets"] == 1
    alert_ids = {alert["id"] for alert in summary["alerts"]}
    assert alert_ids == {
        "worker-lease-expired",
        "queue-backlog",
        "secret-unhealthy",
        "deployment-failed",
    }
    alert_entities = {alert["id"]: alert["entity_ids"] for alert in summary["alerts"]}
    assert alert_entities["queue-backlog"] == [queued_b.id, queued_a.id]
    assert alert_entities["worker-lease-expired"] == [expired_run.id]
    assert alert_entities["deployment-failed"] == [failed_deploy.id]
    assert alert_entities["secret-unhealthy"] == [secret.id]


@pytest.mark.asyncio
async def test_delivery_service_observability_summary_reports_execution_failure_rate(db_session, monkeypatch):
    monkeypatch.setattr(settings, "observability_failure_rate_window_minutes", 60)
    monkeypatch.setattr(settings, "observability_failure_rate_min_runs", 5)
    monkeypatch.setattr(settings, "observability_failure_rate_threshold_percent", 40)

    project = await auth_repository.create_project(
        db_session,
        key="failure-rate",
        name="Failure Rate",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Track execution failure rate.",
        source_type="new_requirement",
        title="Failure rate",
        project_id=project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Failure rate",
        user_story="As an operator, I can detect abnormal execution failures.",
        scope="Observability",
        acceptance_criteria=["Failure rate alert is emitted."],
        constraints=[],
        risks=[],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.READY,
        title="Failure rate task",
        task_prompt="Implement execution failure rate alert.",
        allowed_paths=["backend/app"],
        forbidden_actions=[],
        required_checks=[],
        expected_evidence=[],
    )

    for _ in range(3):
        await delivery_repository.create_execution_run(
            db_session,
            coding_task_id=task.id,
            status=ExecutionRunStatus.SUCCEEDED,
            executor_type="symphony",
            trigger_mode="manual",
        )
    failed_runs = []
    for _ in range(2):
        failed_runs.append(
            await delivery_repository.create_execution_run(
                db_session,
                coding_task_id=task.id,
                status=ExecutionRunStatus.FAILED,
                executor_type="symphony",
                trigger_mode="manual",
            )
        )
    await db_session.commit()

    summary = await DeliveryService().get_observability_summary(db_session, project_ids=[project.id])

    assert summary["status"] == "critical"
    assert summary["metrics"]["recent_execution_runs"] == 5
    assert summary["metrics"]["recent_failed_execution_runs"] == 2
    assert summary["metrics"]["recent_execution_failure_rate_percent"] == 40
    alert = next(item for item in summary["alerts"] if item["id"] == "execution-failure-rate")
    assert alert["category"] == "execution"
    assert alert["count"] == 2
    assert alert["entity_ids"] == [run.id for run in reversed(failed_runs)]


@pytest.mark.asyncio
async def test_delivery_service_project_observability_summaries(db_session, monkeypatch):
    monkeypatch.setattr(settings, "observability_queue_backlog_threshold", 1)
    active_project = await auth_repository.create_project(
        db_session,
        key="active-health",
        name="Active Health",
    )
    quiet_project = await auth_repository.create_project(
        db_session,
        key="quiet-health",
        name="Quiet Health",
    )
    demand = await delivery_repository.create_demand(
        db_session,
        raw_input="Create project health summary.",
        source_type="new_requirement",
        title="Project health",
        project_id=active_project.id,
    )
    spec = await delivery_repository.create_spec_card(
        db_session,
        demand_id=demand.id,
        status=SpecStatus.APPROVED,
        title="Project health",
        user_story="As an operator, I can see project health.",
        scope="Project observability summary.",
        acceptance_criteria=["Project health includes alert counts."],
        constraints=[],
        risks=[],
        open_questions=[],
    )
    task = await delivery_repository.create_coding_task(
        db_session,
        demand_id=demand.id,
        spec_card_id=spec.id,
        status=CodingTaskStatus.READY,
        title="Project health task",
        task_prompt="Implement project health.",
        allowed_paths=[],
        forbidden_actions=[],
        required_checks=[],
        expected_evidence=[],
    )
    await delivery_repository.create_execution_run(
        db_session,
        coding_task_id=task.id,
        status=ExecutionRunStatus.QUEUED,
        executor_type="symphony",
        trigger_mode="manual",
    )
    await db_session.commit()

    summaries = await DeliveryService().get_project_observability_summaries(
        db_session,
        project_ids=[active_project.id, quiet_project.id],
    )

    by_project = {summary["project_key"]: summary for summary in summaries}
    assert by_project["active-health"]["status"] == "warning"
    assert by_project["active-health"]["warning_alerts"] == 1
    assert by_project["active-health"]["top_alerts"][0]["id"] == "queue-backlog"
    assert by_project["quiet-health"]["status"] == "healthy"
    assert by_project["quiet-health"]["alert_count"] == 0


@pytest.mark.asyncio
async def test_delivery_service_blocks_gitlab_merge_request_when_push_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "merge_request_auto_push_enabled", True)
    monkeypatch.setattr(settings, "merge_request_git_remote", "origin")
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()

    def fake_git_push(self, path, remote, source_branch):
        return subprocess.CompletedProcess(
            args=["git", "push"],
            returncode=1,
            stdout="",
            stderr="remote rejected token=local-token-123456",
        )

    monkeypatch.setattr(DeliveryService, "_run_git_push", fake_git_push)
    run = ExecutionRun(
        id=7,
        coding_task_id=11,
        worktree_path=str(worktree_path),
        branch_name="codex/status-badge",
        commit_sha="abc123",
    )

    with pytest.raises(BadRequestException) as exc_info:
        await DeliveryService()._push_source_branch_for_provider(
            provider="gitlab",
            run=run,
            source_branch="codex/status-badge",
        )

    assert "Git push failed" in exc_info.value.detail
    assert "local-token-123456" not in exc_info.value.detail
    assert REDACTED in exc_info.value.detail


@pytest.mark.asyncio
async def test_delivery_service_pushes_repair_run_to_original_merge_request_branch(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "merge_request_auto_push_enabled", True)
    monkeypatch.setattr(settings, "merge_request_git_remote", "origin")
    worktree_path = tmp_path / "worktree"
    worktree_path.mkdir()
    captured: dict[str, object] = {}

    def fake_git_push_refspec(self, path, remote, source_ref, target_ref):
        captured["path"] = str(path)
        captured["remote"] = remote
        captured["source_ref"] = source_ref
        captured["target_ref"] = target_ref
        return subprocess.CompletedProcess(
            args=["git", "push"],
            returncode=0,
            stdout="repair pushed",
            stderr="",
        )

    monkeypatch.setattr(DeliveryService, "_run_git_push_refspec", fake_git_push_refspec)
    run = ExecutionRun(
        id=8,
        coding_task_id=11,
        worktree_path=str(worktree_path),
        branch_name="codex/delivery-run-8-repair",
        commit_sha="def456",
    )
    record = MergeRequestRecord(
        id=19,
        coding_task_id=11,
        execution_run_id=7,
        provider="gitlab",
        title="Add status badge",
        source_branch="codex/status-badge",
        target_branch="main",
    )

    evidence = await DeliveryService()._push_repair_run_to_merge_request(
        provider="gitlab",
        record=record,
        run=run,
    )

    assert captured == {
        "path": str(worktree_path),
        "remote": "origin",
        "source_ref": "codex/delivery-run-8-repair",
        "target_ref": "codex/status-badge",
    }
    assert evidence["source_branch"] == "codex/delivery-run-8-repair"
    assert evidence["target_branch"] == "codex/status-badge"
    assert evidence["stdout_tail"] == "repair pushed"


@pytest.mark.asyncio
async def test_local_provider_collects_real_workspace_context(tmp_path):
    (tmp_path / "README.md").write_text("# Demo\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "v2-delivery-blueprint.md").write_text("delivery docs\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "app" / "pages").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "app" / "pages" / "DeliveryV2Page.tsx").write_text(
        "export function DeliveryV2Page() { return null; }\n",
        encoding="utf-8",
    )
    (tmp_path / "frontend" / "src" / "app").mkdir(parents=True, exist_ok=True)
    (tmp_path / "frontend" / "src" / "app" / "Root.tsx").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "frontend" / "src" / "app" / "lib").mkdir(parents=True)
    (tmp_path / "frontend" / "src" / "app" / "lib" / "api.ts").write_text("export {}\n", encoding="utf-8")
    (tmp_path / "frontend" / "package.json").write_text(
        '{"scripts":{"build":"vite build","test":"vitest"}}',
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "modules" / "delivery").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "modules" / "delivery" / "service.py").write_text(
        "class DeliveryService: pass\n",
        encoding="utf-8",
    )
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    (tmp_path / "backend" / "tests" / "test_health.py").write_text("def test_health(): pass\n", encoding="utf-8")
    (tmp_path / "backend" / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime" / "ignored.py").write_text("ignored\n", encoding="utf-8")

    demand = DemandItem(
        raw_input="Update the delivery dashboard page and API status display.",
        source_type="new_requirement",
        title="Update delivery dashboard",
    )
    draft = await LocalWorkflowProvider(workspace_root=tmp_path).collect_repo_context(demand)

    assert draft.confidence_score >= 0.6
    assert draft.provider_metadata["provider"] == "local"
    assert draft.provider_metadata["file_count"] >= 6
    assert "frontend/package.json:scripts.build" in draft.dependency_refs
    assert "backend/pyproject.toml" in draft.dependency_refs
    assert "workspace.root" in draft.source_refs
    assert "frontend/src/app/pages/DeliveryV2Page.tsx" in draft.discovered_files
    assert "backend/app/modules/delivery/service.py" in draft.discovered_files
    assert not any(path.startswith(".runtime") for path in draft.discovered_files)


@pytest.mark.asyncio
async def test_local_provider_uses_history_and_content_for_context_matching(tmp_path):
    (tmp_path / "backend" / "app" / "modules" / "delivery").mkdir(parents=True)
    (tmp_path / "backend" / "app" / "modules" / "delivery" / "a.py").write_text(
        '"""Historical demand similarity matcher for repository context collection."""\n',
        encoding="utf-8",
    )
    (tmp_path / "backend" / "app" / "modules" / "delivery" / "unrelated.py").write_text(
        '"""Queue lease maintenance."""\n',
        encoding="utf-8",
    )

    demand = DemandItem(
        raw_input="Reuse previous context collection evidence.",
        source_type="new_requirement",
        title="Context collection",
        context_payload={
            "historical_demands": {
                "items": [
                    {
                        "title": "Historical similarity matcher",
                        "summary": "Match repository files from historical demand similarity evidence.",
                    }
                ]
            }
        },
    )

    draft = await LocalWorkflowProvider(workspace_root=tmp_path).collect_repo_context(demand)

    assert "backend/app/modules/delivery/a.py" in draft.discovered_files
    assert "backend/app/modules/delivery/unrelated.py" not in draft.discovered_files
    assert draft.provider_metadata["matcher"] == "path_and_content_tokens"
    assert draft.provider_metadata["historical_context_items"] == 1


@pytest.mark.asyncio
async def test_local_provider_analyzes_impact_from_repo_context():
    demand = DemandItem(
        raw_input="Update the delivery dashboard page and backend delivery status API.",
        source_type="new_requirement",
        title="Update delivery dashboard",
        risk_level=DeliveryRiskLevel.L1,
        confidence_score=0.82,
    )
    repo_context = RepoContext(
        id=1,
        demand_id=1,
        status="ready",
        provider="local",
        summary="local",
        source_refs_json=["workspace.root"],
        discovered_files_json=[
            "frontend/src/app/pages/DeliveryV2Page.tsx",
            "backend/app/modules/delivery/service.py",
        ],
        dependency_refs_json=[
            "frontend/package.json:scripts.build",
            "backend/tests",
        ],
        confidence_score=0.9,
        provider_metadata_json={"provider": "local"},
    )

    draft = await LocalWorkflowProvider().analyze_impact(demand, None, repo_context)

    assert draft.risk_level == DeliveryRiskLevel.L1
    assert draft.confidence_score == 0.82
    assert "frontend/src/app/pages/DeliveryV2Page.tsx" in draft.affected_files
    assert "backend/app/modules/delivery/service.py" in draft.affected_files
    assert "frontend/src/app/pages" in draft.impacted_areas
    assert "backend/app/modules/delivery" in draft.impacted_areas
    assert any("npm run build" in item for item in draft.recommendations)
    assert any("python -m pytest" in item for item in draft.recommendations)


def test_worktree_executor_links_dependency_cache(tmp_path):
    source_root = tmp_path / "source"
    worktree_root = tmp_path / "worktree"
    source_dependency = source_root / "frontend" / "node_modules"
    target_dependency = worktree_root / "frontend" / "node_modules"
    source_dependency.mkdir(parents=True)
    (worktree_root / "frontend").mkdir(parents=True)

    try:
        links = WorktreeChecksExecutor()._link_dependency_cache_dirs(source_root, worktree_root)

        assert len(links) == 1
        assert links[0]["path"] == "frontend/node_modules"
        assert links[0]["source"] == str(source_dependency)
        assert links[0]["target"] == str(target_dependency)
        assert links[0]["type"] in {"symlink", "junction"}
        assert target_dependency.is_dir()
    finally:
        if target_dependency.exists():
            target_dependency.rmdir() if not target_dependency.is_symlink() else target_dependency.unlink()
