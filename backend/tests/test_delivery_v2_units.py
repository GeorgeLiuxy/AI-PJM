"""Delivery v2 service rule tests that do not require a database."""

import sys
import subprocess
import json

import pytest

from app.core.config import settings
from app.core.exceptions import AIServiceException, BadRequestException
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
    ExecutionRunStatus,
    GateStatus,
    GateType,
    MergeRequestStatus,
    ReviewStatus,
    SpecStatus,
)
from app.modules.delivery.gates import gate_engine
from app.modules.delivery.merge_requests.gitlab import GitLabMergeRequestClient
from app.modules.delivery.models import CodingTask, DemandItem, DeployRecord, ExecutionRun, MergeRequestRecord, RepoContext
from app.modules.delivery.provider_credentials import ProviderCredential, resolve_provider_credential
from app.modules.delivery.providers.dify import DifyWorkflowProvider
from app.modules.delivery.providers.factory import get_workflow_provider
from app.modules.delivery.providers.local import LocalWorkflowProvider
from app.modules.delivery.redaction import REDACTED, redact_text, redact_value
from app.modules.delivery.repository import delivery_repository
from app.modules.delivery.service import DeliveryService, delivery_service
from app.modules.secrets.service import secret_store_service
from scripts.symphony_worker import Worker, quote_arg, tail


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
    assert remote_status.evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": 123,
        "token_secret_name": "deploy_token",
    }
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
    assert provider_evidence["credential"] == {
        "credential_source": "secret_store",
        "credential_project_id": project.id,
        "token_secret_name": "gitlab_token",
    }
    assert "project-gitlab-token" not in str(record.evidence_json)


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
