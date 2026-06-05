"""Delivery v2 API tests."""

import json
import hashlib
import hmac
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.core.config import settings
from app.modules.audit.repository import audit_repository
from app.modules.auth.repository import auth_repository
from app.modules.delivery.enums import CodingTaskStatus, ExecutionRunStatus, GateType, MergeRequestStatus, ReviewStatus, SpecStatus
from app.modules.delivery.repository import delivery_repository


@pytest.fixture
def generated_worktrees():
    worktrees: list[dict[str, str | None]] = []
    yield worktrees

    repo_root = Path(__file__).resolve().parents[2]
    allowed_root = (repo_root / ".runtime" / "worktrees").resolve()
    allowed_prompt_root = (repo_root / ".runtime" / "codex-prompts").resolve()

    for worktree in worktrees:
        path = worktree.get("workspace_root")
        branch = worktree.get("branch_name")
        prompt_file = worktree.get("prompt_file")
        if prompt_file:
            resolved_prompt = Path(prompt_file).resolve()
            if str(resolved_prompt).lower().startswith(str(allowed_prompt_root).lower()):
                resolved_prompt.unlink(missing_ok=True)
        if path:
            resolved_path = Path(path).resolve()
            if str(resolved_path).lower().startswith(str(allowed_root).lower()):
                for relative_path in (
                    Path("frontend") / "node_modules",
                    Path("backend") / ".venv",
                    Path(".venv"),
                ):
                    dependency_link = resolved_path / relative_path
                    is_junction = bool(
                        hasattr(os.path, "isjunction") and os.path.isjunction(dependency_link)
                    )
                    if dependency_link.is_symlink():
                        dependency_link.unlink(missing_ok=True)
                    elif is_junction:
                        dependency_link.rmdir()

                result = subprocess.run(
                    ["git", "-C", str(repo_root), "worktree", "remove", "--force", "--force", str(resolved_path)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0 and resolved_path.exists():
                    shutil.rmtree(resolved_path, ignore_errors=True)
                    subprocess.run(
                        ["git", "-C", str(repo_root), "worktree", "prune"],
                        capture_output=True,
                        text=True,
                        check=False,
                    )
        if branch and branch.startswith("codex/delivery-run-"):
            subprocess.run(
                ["git", "-C", str(repo_root), "branch", "-D", branch],
                capture_output=True,
                text=True,
                check=False,
            )


def remember_worktree(run_data: dict, generated_worktrees: list[dict[str, str | None]]) -> None:
    evidence = run_data.get("evidence_json") or {}
    dispatch = evidence.get("dispatch") or {}
    if not isinstance(dispatch, dict):
        return
    codex_invocation = dispatch.get("codex_invocation") or {}
    if dispatch.get("workspace_root") and dispatch.get("branch_name"):
        generated_worktrees.append(
            {
                "workspace_root": dispatch.get("workspace_root"),
                "branch_name": dispatch.get("branch_name"),
                "prompt_file": codex_invocation.get("prompt_file")
                if isinstance(codex_invocation, dict)
                else None,
            }
        )


async def create_ready_coding_task(client, allowed_paths: list[str] | None = None) -> dict:
    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Add a compact execution status badge to the delivery dashboard.",
            "source_type": "new_requirement",
        },
    )
    assert demand_response.status_code == 201
    demand_id = demand_response.json()["data"]["id"]

    spec_response = await client.post(
        f"/api/v2/demands/{demand_id}/spec",
        json={"auto_approve_low_risk": True},
    )
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={
            "allowed_paths": allowed_paths or ["backend/app"],
            "required_checks": ["python -m compileall app"],
        },
    )
    assert task_response.status_code == 201
    return task_response.json()["data"]


async def create_succeeded_execution(client, generated_worktrees) -> tuple[dict, dict]:
    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    dispatched_run = dispatch_response.json()["data"]
    remember_worktree(dispatched_run, generated_worktrees)
    assert dispatched_run["status"] == "succeeded"
    return task_data, dispatched_run


async def create_review_passed_merge_request(client, generated_worktrees) -> tuple[dict, dict, dict]:
    task_data, run_data = await create_succeeded_execution(client, generated_worktrees)
    mr_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/merge-request",
        json={"provider": "local", "target_branch": "main"},
    )
    assert mr_response.status_code == 201
    mr_data = mr_response.json()["data"]
    assert mr_data["created_by_ref"] == "local_operator"
    assert mr_data["created_by_user_id"] is None
    review_response = await client.post(
        f"/api/v2/merge-requests/{mr_data['id']}/review",
        json={"review_status": "passed", "review_summary": "Local review passed."},
    )
    assert review_response.status_code == 200
    review_data = review_response.json()["data"]
    assert review_data["reviewed_by_ref"] == "local_operator"
    assert review_data["reviewed_by_user_id"] is None
    assert review_data["reviewed_at"]
    return task_data, run_data, review_data


@pytest.mark.asyncio
async def test_observability_summary_endpoint(client):
    response = await client.get("/api/v2/observability/summary")

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "healthy"
    assert data["metrics"]["queued_runs"] == 0
    assert data["alerts"] == []


@pytest.mark.asyncio
async def test_observability_metrics_endpoint(client):
    response = await client.get("/api/v2/observability/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "# TYPE ai_pjm_observability_status_code gauge" in body
    assert 'ai_pjm_observability_status_code{status="healthy"} 0' in body
    assert 'ai_pjm_execution_runs{state="queued"} 0' in body
    assert "ai_pjm_recent_execution_failure_rate_percent 0" in body


@pytest.mark.asyncio
async def test_github_webhook_endpoint_updates_existing_pull_request(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "github_webhook_secret", "github-webhook-secret")
    project = await auth_repository.create_project(
        db_session,
        key="api-github-webhook",
        name="API GitHub Webhook",
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
        scope="PR sync.",
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
        "state": "success",
        "context": "ci/unit",
        "pull_request_number": 42,
    }
    body = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    signature = "sha256=" + hmac.new(
        b"github-webhook-secret",
        body,
        hashlib.sha256,
    ).hexdigest()

    response = await client.post(
        "/api/v2/github/webhook",
        content=body,
        headers={
            "X-GitHub-Event": "status",
            "X-Hub-Signature-256": signature,
            "Content-Type": "application/json",
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["processed"] is True
    assert data["external_id"] == "42"
    assert data["merge_request"]["id"] == pull_request.id
    assert data["merge_request"]["status"] == "review_passed"
    assert data["merge_request"]["review_status"] == "passed"

    detail = await delivery_repository.get_demand_detail(db_session, demand.id)
    review_gates = [gate for gate in detail.gate_checks if gate.gate_type == GateType.REVIEW_PASSED]
    assert review_gates[-1].status == "passed"


@pytest.mark.asyncio
async def test_project_deployment_environment_config_endpoint(client, db_session):
    project = await auth_repository.create_project(
        db_session,
        key="api-deploy-env",
        name="API Deploy Env",
    )
    await db_session.commit()

    update_response = await client.put(
        f"/api/v2/projects/{project.id}/deployment-environments",
        json={
            "environments": {
                "test": {
                    "url": "https://test.example/app",
                    "log_url": "https://ci.example/jobs/123",
                    "description": "Shared test environment",
                    "environment_name": "Test",
                }
            }
        },
    )

    assert update_response.status_code == 200
    payload = update_response.json()["data"]
    assert payload["project_id"] == project.id
    assert payload["environments"]["test"]["url"] == "https://test.example/app"
    assert payload["environments"]["test"]["log_url"] == "https://ci.example/jobs/123"

    get_response = await client.get(f"/api/v2/projects/{project.id}/deployment-environments")
    assert get_response.status_code == 200
    assert get_response.json()["data"]["environments"]["test"]["description"] == "Shared test environment"

    loaded_project = await auth_repository.get_project(db_session, project.id)
    assert loaded_project.settings_json["delivery"]["deployment_environments"]["test"]["environment_name"] == "Test"

    audit_events = await audit_repository.list_events(
        db_session,
        project_id=project.id,
        action="delivery.project_deployment_environments_updated",
    )
    assert audit_events
    assert audit_events[0].metadata_json == {"environments": ["test"]}


@pytest.mark.asyncio
async def test_symphony_dispatch_keeps_run_queued_for_worker(client, monkeypatch):
    monkeypatch.setattr(settings, "symphony_bridge_token", "bridge-token")

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "symphony", "trigger_mode": "background"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    dispatched = dispatch_response.json()["data"]
    assert dispatched["status"] == ExecutionRunStatus.QUEUED
    assert dispatched["result_summary"] == "Execution is queued for Symphony worker claim."
    assert dispatched["evidence_json"]["dispatch"]["executor"] == "symphony_bridge"
    assert dispatched["evidence_json"]["dispatch"]["deferred"] is True

    task_response = await client.get(f"/api/v2/coding-tasks/{task_data['id']}")
    assert task_response.status_code == 200
    assert task_response.json()["data"]["status"] == "ready"

    headers = {"X-Symphony-Bridge-Token": "bridge-token"}
    queue_response = await client.get("/api/v2/internal/symphony/execution-runs", headers=headers)
    assert queue_response.status_code == 200
    assert [item["id"] for item in queue_response.json()["data"]] == [run_data["id"]]

    claim_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_data['id']}/claim",
        json={"worker_id": "worker-a", "lease_seconds": 90},
        headers=headers,
    )
    assert claim_response.status_code == 200
    assert claim_response.json()["data"]["status"] == ExecutionRunStatus.RUNNING


@pytest.mark.asyncio
async def test_symphony_bridge_claim_event_heartbeat_and_complete(client, monkeypatch):
    monkeypatch.setattr(settings, "symphony_bridge_token", "bridge-token")
    monkeypatch.setattr(settings, "symphony_bridge_default_lease_seconds", 120)

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "symphony", "trigger_mode": "background"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    missing_token_response = await client.get("/api/v2/internal/symphony/execution-runs")
    assert missing_token_response.status_code == 401

    headers = {"X-Symphony-Bridge-Token": "bridge-token"}
    queue_response = await client.get("/api/v2/internal/symphony/execution-runs", headers=headers)
    assert queue_response.status_code == 200
    queue_items = queue_response.json()["data"]
    assert [item["id"] for item in queue_items] == [run_data["id"]]

    package_response = await client.get(
        f"/api/v2/internal/symphony/execution-runs/{run_data['id']}/task-package",
        headers=headers,
    )
    assert package_response.status_code == 200
    package = package_response.json()["data"]
    assert package["run_id"] == run_data["id"]
    assert package["coding_task_id"] == task_data["id"]
    assert package["required_checks"] == ["python -m compileall app"]

    claim_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_data['id']}/claim",
        json={"worker_id": "worker-a", "lease_seconds": 90},
        headers=headers,
    )
    assert claim_response.status_code == 200
    claimed = claim_response.json()["data"]
    assert claimed["status"] == ExecutionRunStatus.RUNNING
    assert claimed["evidence_json"]["symphony_bridge"]["worker_id"] == "worker-a"
    assert claimed["evidence_json"]["symphony_bridge"]["lease_seconds"] == 90

    duplicate_claim_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_data['id']}/claim",
        json={"worker_id": "worker-b"},
        headers=headers,
    )
    assert duplicate_claim_response.status_code == 409

    event_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_data['id']}/events",
        json={
            "worker_id": "worker-a",
            "level": "info",
            "message": "Codex started with token=local-token-123456",
            "event_json": {"api_key": "sk-test-abcdefghijklmnopqrstuvwxyz"},
        },
        headers=headers,
    )
    assert event_response.status_code == 200
    event_payload = json.dumps(event_response.json()["data"], ensure_ascii=False)
    assert "local-token-123456" not in event_payload
    assert "sk-test-abcdefghijklmnopqrstuvwxyz" not in event_payload

    heartbeat_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_data['id']}/heartbeat",
        json={"worker_id": "worker-a", "lease_seconds": 180},
        headers=headers,
    )
    assert heartbeat_response.status_code == 200
    assert heartbeat_response.json()["data"]["evidence_json"]["symphony_bridge"]["lease_seconds"] == 180

    complete_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_data['id']}/complete",
        json={
            "worker_id": "worker-a",
            "status": "succeeded",
            "summary": "Required checks passed.",
            "evidence": {
                "changed_files": ["backend/app/modules/delivery/symphony_bridge.py"],
                "command_results": [
                    {"command": "python -m compileall app", "status": "passed", "exit_code": 0}
                ],
                "api_key": "sk-test-abcdefghijklmnopqrstuvwxyz",
            },
            "worktree_path": "D:/projects/AI PJM/.runtime/worktrees/example",
            "branch_name": "codex/example",
            "commit_sha": "abc123",
        },
        headers=headers,
    )
    assert complete_response.status_code == 200
    completed = complete_response.json()["data"]
    assert completed["status"] == ExecutionRunStatus.SUCCEEDED
    assert completed["worktree_path"].endswith("/.runtime/worktrees/example")
    assert completed["evidence_json"]["dispatch"]["api_key"] == "[REDACTED]"


@pytest.mark.asyncio
async def test_symphony_bridge_recovers_expired_worker_lease(client, db_session, monkeypatch):
    monkeypatch.setattr(settings, "symphony_bridge_token", "bridge-token")

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "symphony", "trigger_mode": "background"},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["data"]["id"]

    headers = {"X-Symphony-Bridge-Token": "bridge-token"}
    claim_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_id}/claim",
        json={"worker_id": "worker-expired", "lease_seconds": 90},
        headers=headers,
    )
    assert claim_response.status_code == 200

    run = await delivery_repository.get_execution_run(db_session, run_id)
    expired_evidence = dict(run.evidence_json or {})
    bridge_metadata = dict(expired_evidence["symphony_bridge"])
    bridge_metadata["lease_expires_at"] = datetime(2000, 1, 1, tzinfo=timezone.utc).isoformat()
    expired_evidence["symphony_bridge"] = bridge_metadata
    await delivery_repository.update_execution_run(db_session, run, evidence_json=expired_evidence)
    await db_session.commit()

    queue_response = await client.get("/api/v2/internal/symphony/execution-runs", headers=headers)
    assert queue_response.status_code == 200
    assert queue_response.json()["data"] == []

    recovered_response = await client.get(f"/api/v2/execution-runs/{run_id}")
    assert recovered_response.status_code == 200
    recovered = recovered_response.json()["data"]
    assert recovered["status"] == ExecutionRunStatus.FAILED
    assert recovered["evidence_json"]["symphony_bridge"]["status"] == "lease_expired"
    assert recovered["result_summary"] == "Symphony worker lease expired; run was marked failed for recovery."

    task_response = await client.get(f"/api/v2/coding-tasks/{task_data['id']}")
    assert task_response.status_code == 200
    assert task_response.json()["data"]["status"] == "blocked"


@pytest.mark.asyncio
async def test_execution_run_pause_and_resume_control_symphony_queue(client, monkeypatch):
    monkeypatch.setattr(settings, "symphony_bridge_token", "bridge-token")

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "symphony", "trigger_mode": "background"},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["data"]["id"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_id}/dispatch")
    assert dispatch_response.status_code == 200

    pause_response = await client.post(
        f"/api/v2/execution-runs/{run_id}/pause",
        json={"reason": "Hold for operator check."},
    )
    assert pause_response.status_code == 200
    paused = pause_response.json()["data"]
    assert paused["status"] == ExecutionRunStatus.PAUSED
    assert paused["evidence_json"]["last_control"]["action"] == "paused"

    headers = {"X-Symphony-Bridge-Token": "bridge-token"}
    queue_response = await client.get("/api/v2/internal/symphony/execution-runs", headers=headers)
    assert queue_response.status_code == 200
    assert queue_response.json()["data"] == []

    resume_response = await client.post(
        f"/api/v2/execution-runs/{run_id}/resume",
        json={"reason": "Operator check passed."},
    )
    assert resume_response.status_code == 200
    resumed = resume_response.json()["data"]
    assert resumed["status"] == ExecutionRunStatus.QUEUED
    assert resumed["evidence_json"]["last_control"]["action"] == "resumed"

    resumed_queue_response = await client.get("/api/v2/internal/symphony/execution-runs", headers=headers)
    assert resumed_queue_response.status_code == 200
    assert [item["id"] for item in resumed_queue_response.json()["data"]] == [run_id]


@pytest.mark.asyncio
async def test_execution_run_cancel_blocks_late_symphony_completion(client, monkeypatch):
    monkeypatch.setattr(settings, "symphony_bridge_token", "bridge-token")

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "symphony", "trigger_mode": "background"},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["data"]["id"]

    headers = {"X-Symphony-Bridge-Token": "bridge-token"}
    claim_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_id}/claim",
        json={"worker_id": "worker-cancel", "lease_seconds": 90},
        headers=headers,
    )
    assert claim_response.status_code == 200

    cancel_response = await client.post(
        f"/api/v2/execution-runs/{run_id}/cancel",
        json={"reason": "Operator cancelled stale task."},
    )
    assert cancel_response.status_code == 200
    cancelled = cancel_response.json()["data"]
    assert cancelled["status"] == ExecutionRunStatus.CANCELLED
    assert cancelled["evidence_json"]["last_control"]["action"] == "cancelled"

    task_response = await client.get(f"/api/v2/coding-tasks/{task_data['id']}")
    assert task_response.status_code == 200
    assert task_response.json()["data"]["status"] == "blocked"

    complete_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_id}/complete",
        json={
            "worker_id": "worker-cancel",
            "status": "succeeded",
            "summary": "Late worker completion.",
            "evidence": {
                "changed_files": ["backend/app/modules/delivery/symphony_bridge.py"],
                "command_results": [
                    {"command": "python -m compileall app", "status": "passed", "exit_code": 0}
                ],
            },
        },
        headers=headers,
    )
    assert complete_response.status_code == 409
    assert "not running" in complete_response.json()["message"]


@pytest.mark.asyncio
async def test_symphony_bridge_complete_enforces_required_checks_and_allowed_paths(client, monkeypatch):
    monkeypatch.setattr(settings, "symphony_bridge_token", "bridge-token")

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "symphony", "trigger_mode": "background"},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["data"]["id"]

    headers = {"X-Symphony-Bridge-Token": "bridge-token"}
    claim_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_id}/claim",
        json={"worker_id": "worker-a"},
        headers=headers,
    )
    assert claim_response.status_code == 200

    complete_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_id}/complete",
        json={
            "worker_id": "worker-a",
            "status": "succeeded",
            "summary": "Worker reported success.",
            "evidence": {
                "changed_files": ["README.md"],
                "command_results": [],
            },
        },
        headers=headers,
    )
    assert complete_response.status_code == 200
    completed = complete_response.json()["data"]
    assert completed["status"] == ExecutionRunStatus.FAILED
    validation = completed["evidence_json"]["dispatch"]["bridge_validation"]
    assert validation["passed"] is False
    assert validation["changed_file_violations"] == ["README.md"]
    assert validation["missing_required_checks"] == ["python -m compileall app"]


@pytest.mark.asyncio
async def test_symphony_bridge_complete_requires_expected_changed_file_evidence(client, monkeypatch):
    monkeypatch.setattr(settings, "symphony_bridge_token", "bridge-token")

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "symphony", "trigger_mode": "background"},
    )
    assert run_response.status_code == 201
    run_id = run_response.json()["data"]["id"]

    headers = {"X-Symphony-Bridge-Token": "bridge-token"}
    claim_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_id}/claim",
        json={"worker_id": "worker-a"},
        headers=headers,
    )
    assert claim_response.status_code == 200

    complete_response = await client.post(
        f"/api/v2/internal/symphony/execution-runs/{run_id}/complete",
        json={
            "worker_id": "worker-a",
            "status": "succeeded",
            "summary": "Worker reported success without changes.",
            "evidence": {
                "changed_files": [],
                "command_results": [
                    {"command": "python -m compileall app", "status": "passed", "exit_code": 0}
                ],
            },
        },
        headers=headers,
    )
    assert complete_response.status_code == 200
    completed = complete_response.json()["data"]
    assert completed["status"] == ExecutionRunStatus.FAILED
    validation = completed["evidence_json"]["dispatch"]["bridge_validation"]
    assert validation["missing_expected_evidence"] == ["changed_files"]


@pytest.mark.asyncio
async def test_delivery_v2_demand_to_coding_task(client, generated_worktrees):
    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Add a compact execution status badge to the delivery dashboard.",
            "source_type": "new_requirement",
        },
    )
    assert demand_response.status_code == 201
    demand_data = demand_response.json()["data"]
    assert demand_data["status"] == "intake"
    demand_id = demand_data["id"]

    spec_response = await client.post(
        f"/api/v2/demands/{demand_id}/spec",
        json={"auto_approve_low_risk": True},
    )
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]
    assert spec_data["demand_id"] == demand_id
    assert spec_data["status"] == "approved"
    assert spec_data["acceptance_criteria_json"]

    repo_context_response = await client.post(
        f"/api/v2/demands/{demand_id}/repo-context",
        json={},
    )
    assert repo_context_response.status_code == 201
    repo_context_data = repo_context_response.json()["data"]
    assert repo_context_data["demand_id"] == demand_id
    assert repo_context_data["status"] == "ready"

    impact_response = await client.post(
        f"/api/v2/demands/{demand_id}/impact-analysis",
        json={"repo_context_id": repo_context_data["id"]},
    )
    assert impact_response.status_code == 201
    impact_data = impact_response.json()["data"]
    assert impact_data["demand_id"] == demand_id
    assert impact_data["status"] == "ready"

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={
            "allowed_paths": ["frontend/src/app/components"],
            "required_checks": ["python -m compileall app"],
        },
    )
    assert task_response.status_code == 201
    task_data = task_response.json()["data"]
    assert task_data["spec_card_id"] == spec_data["id"]
    assert task_data["status"] == "ready"
    assert "Acceptance criteria" in task_data["task_prompt"]

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]
    assert run_data["coding_task_id"] == task_data["id"]
    assert run_data["status"] == "queued"
    assert run_data["logs"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    dispatched_run = dispatch_response.json()["data"]
    remember_worktree(dispatched_run, generated_worktrees)
    assert dispatched_run["status"] == "succeeded"
    assert dispatched_run["result_summary"] == "Required checks passed (1/1)."
    dispatch_evidence = dispatched_run["evidence_json"]["dispatch"]
    assert dispatch_evidence["executor"] == "worktree_checks"
    assert dispatch_evidence["workspace_root"]
    assert dispatch_evidence["original_workspace_root"]
    assert dispatch_evidence["workspace_root"] != dispatch_evidence["original_workspace_root"]
    assert dispatch_evidence["branch_name"].startswith("codex/delivery-run-")
    assert dispatched_run["worktree_path"] == dispatch_evidence["workspace_root"]
    assert dispatched_run["branch_name"] == dispatch_evidence["branch_name"]
    assert dispatched_run["commit_sha"] == dispatch_evidence["commit_sha"]
    assert dispatch_evidence["check_results"][0]["status"] == "passed"
    assert any(log["message"].startswith("Check passed") for log in dispatched_run["logs"])
    assert any(log["message"] == "Isolated git worktree prepared." for log in dispatched_run["logs"])

    spec_get_response = await client.get(f"/api/v2/spec-cards/{spec_data['id']}")
    assert spec_get_response.status_code == 200
    assert spec_get_response.json()["data"]["id"] == spec_data["id"]

    task_get_response = await client.get(f"/api/v2/coding-tasks/{task_data['id']}")
    assert task_get_response.status_code == 200
    assert task_get_response.json()["data"]["id"] == task_data["id"]

    run_get_response = await client.get(f"/api/v2/execution-runs/{run_data['id']}")
    assert run_get_response.status_code == 200
    assert run_get_response.json()["data"]["id"] == run_data["id"]
    assert run_get_response.json()["data"]["status"] == "succeeded"

    detail_response = await client.get(f"/api/v2/demands/{demand_id}")
    assert detail_response.status_code == 200
    detail_data = detail_response.json()["data"]
    assert detail_data["status"] == "planned"
    assert detail_data["risk_level"] == "L1"
    assert len(detail_data["spec_cards"]) == 1
    assert len(detail_data["repo_contexts"]) == 1
    assert len(detail_data["impact_analyses"]) == 1
    assert len(detail_data["gate_checks"]) >= 5
    assert len(detail_data["coding_tasks"]) == 1
    assert len(detail_data["coding_tasks"][0]["execution_runs"]) == 1
    assert detail_data["coding_tasks"][0]["execution_runs"][0]["status"] == "succeeded"

    retry_response = await client.post(f"/api/v2/coding-tasks/{task_data['id']}/retry")
    assert retry_response.status_code == 200
    retry_data = retry_response.json()["data"]
    remember_worktree(retry_data, generated_worktrees)
    assert retry_data["coding_task_id"] == task_data["id"]
    assert retry_data["status"] == "succeeded"
    assert retry_data["trigger_mode"] == "manual_retry"
    assert retry_data["evidence_json"]["dispatch"]["check_results"][0]["status"] == "passed"

    retry_detail_response = await client.get(f"/api/v2/demands/{demand_id}")
    assert retry_detail_response.status_code == 200
    retry_detail_data = retry_detail_response.json()["data"]
    retry_runs = sorted(
        retry_detail_data["coding_tasks"][0]["execution_runs"],
        key=lambda item: item["id"],
    )
    assert len(retry_runs) == 2
    assert retry_runs[-1]["status"] == "succeeded"

    list_response = await client.get("/api/v2/demands")
    assert list_response.status_code == 200
    list_data = list_response.json()["data"]
    assert any(item["id"] == demand_id for item in list_data)


@pytest.mark.asyncio
async def test_delivery_v2_creates_local_merge_request_record(client, generated_worktrees):
    task_data, run_data = await create_succeeded_execution(client, generated_worktrees)

    mr_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/merge-request",
        json={"provider": "local", "target_branch": "main"},
    )
    assert mr_response.status_code == 201
    mr_data = mr_response.json()["data"]
    assert mr_data["coding_task_id"] == task_data["id"]
    assert mr_data["execution_run_id"] == run_data["id"]
    assert mr_data["provider"] == "local"
    assert mr_data["status"] == "created"
    assert mr_data["review_status"] == "pending"
    assert mr_data["source_branch"] == run_data["branch_name"]
    assert mr_data["target_branch"] == "main"
    assert mr_data["url"] == f"local://merge-requests/{mr_data['id']}"

    detail_response = await client.get(f"/api/v2/demands/{task_data['demand_id']}")
    assert detail_response.status_code == 200
    detail_task = detail_response.json()["data"]["coding_tasks"][0]
    assert detail_task["merge_requests"][0]["id"] == mr_data["id"]


@pytest.mark.asyncio
async def test_delivery_v2_blocks_merge_request_before_successful_execution(client):
    task_data = await create_ready_coding_task(client)

    mr_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/merge-request",
        json={"provider": "local"},
    )
    assert mr_response.status_code == 400
    assert "completed coding task" in mr_response.json()["message"]


@pytest.mark.asyncio
async def test_delivery_v2_records_merge_request_review_gate(client, generated_worktrees):
    task_data, _run_data = await create_succeeded_execution(client, generated_worktrees)
    mr_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/merge-request",
        json={"provider": "local"},
    )
    assert mr_response.status_code == 201
    mr_data = mr_response.json()["data"]

    review_response = await client.post(
        f"/api/v2/merge-requests/{mr_data['id']}/review",
        json={
            "review_status": "passed",
            "review_summary": "Local review passed.",
            "review_comments": [{"body": "No blocking issues."}],
            "blocking_issues": [],
        },
    )
    assert review_response.status_code == 200
    review_data = review_response.json()["data"]
    assert review_data["status"] == "review_passed"
    assert review_data["review_status"] == "passed"

    detail_response = await client.get(f"/api/v2/demands/{task_data['demand_id']}")
    assert detail_response.status_code == 200
    gates = detail_response.json()["data"]["gate_checks"]
    assert any(gate["gate_type"] == "review_passed" and gate["status"] == "passed" for gate in gates)


@pytest.mark.asyncio
async def test_delivery_v2_rejects_remote_review_sync_for_local_merge_request(client, generated_worktrees):
    task_data, _run_data = await create_succeeded_execution(client, generated_worktrees)
    mr_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/merge-request",
        json={"provider": "local"},
    )
    assert mr_response.status_code == 201
    mr_data = mr_response.json()["data"]

    sync_response = await client.post(f"/api/v2/merge-requests/{mr_data['id']}/sync-review")

    assert sync_response.status_code == 400
    assert "does not support remote review sync" in sync_response.json()["message"]


@pytest.mark.asyncio
async def test_delivery_v2_creates_deployment_after_review_passes(client, generated_worktrees):
    task_data, _run_data, mr_data = await create_review_passed_merge_request(client, generated_worktrees)

    deploy_response = await client.post(
        f"/api/v2/merge-requests/{mr_data['id']}/deployments",
        json={"provider": "local", "environment": "test"},
    )
    assert deploy_response.status_code == 201
    deploy_data = deploy_response.json()["data"]
    assert deploy_data["merge_request_id"] == mr_data["id"]
    assert deploy_data["coding_task_id"] == task_data["id"]
    assert deploy_data["status"] == "deployed"
    assert deploy_data["environment"] == "test"
    assert deploy_data["url"] == f"local://deployments/{deploy_data['id']}"
    assert deploy_data["created_by_ref"] == "local_operator"
    assert deploy_data["created_by_user_id"] is None

    detail_response = await client.get(f"/api/v2/demands/{task_data['demand_id']}")
    assert detail_response.status_code == 200
    gates = detail_response.json()["data"]["gate_checks"]
    assert any(gate["gate_type"] == "test_deployed" and gate["status"] == "passed" for gate in gates)


@pytest.mark.asyncio
async def test_delivery_v2_blocks_deployment_before_review_passes(client, generated_worktrees):
    task_data, _run_data = await create_succeeded_execution(client, generated_worktrees)
    mr_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/merge-request",
        json={"provider": "local"},
    )
    assert mr_response.status_code == 201
    mr_data = mr_response.json()["data"]

    deploy_response = await client.post(
        f"/api/v2/merge-requests/{mr_data['id']}/deployments",
        json={"provider": "local", "environment": "test"},
    )
    assert deploy_response.status_code == 400
    assert "passed merge request review" in deploy_response.json()["message"]


@pytest.mark.asyncio
async def test_delivery_v2_records_verification_gate(client, generated_worktrees):
    task_data, _run_data, mr_data = await create_review_passed_merge_request(client, generated_worktrees)
    deploy_response = await client.post(
        f"/api/v2/merge-requests/{mr_data['id']}/deployments",
        json={"provider": "local", "environment": "test"},
    )
    assert deploy_response.status_code == 201
    deploy_data = deploy_response.json()["data"]

    verification_response = await client.post(
        f"/api/v2/deployments/{deploy_data['id']}/verification",
        json={
            "status": "passed",
            "verifier_ref": "local_operator",
            "summary": "Manual verification passed.",
            "evidence_links": [deploy_data["url"]],
        },
    )
    assert verification_response.status_code == 201
    verification_data = verification_response.json()["data"]
    assert verification_data["deploy_record_id"] == deploy_data["id"]
    assert verification_data["status"] == "passed"
    assert verification_data["verifier_ref"] == "local_operator"
    assert verification_data["verifier_user_id"] is None

    detail_response = await client.get(f"/api/v2/demands/{task_data['demand_id']}")
    assert detail_response.status_code == 200
    detail_data = detail_response.json()["data"]
    nested_deploy = detail_data["coding_tasks"][0]["merge_requests"][0]["deploy_records"][0]
    assert nested_deploy["verification_records"][0]["id"] == verification_data["id"]
    assert any(
        gate["gate_type"] == "verification_passed" and gate["status"] == "passed"
        for gate in detail_data["gate_checks"]
    )


@pytest.mark.asyncio
async def test_delivery_v2_lists_execution_queue(client):
    task_data = await create_ready_coding_task(client)
    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    queue_response = await client.get("/api/v2/execution-runs?statuses=queued&limit=10")
    assert queue_response.status_code == 200
    queue_data = queue_response.json()["data"]
    assert any(item["id"] == run_data["id"] for item in queue_data)
    item = next(item for item in queue_data if item["id"] == run_data["id"])
    assert item["status"] == "queued"
    assert item["coding_task_title"] == task_data["title"]
    assert item["demand_id"] == task_data["demand_id"]


@pytest.mark.asyncio
async def test_delivery_v2_create_execution_run_is_idempotent_for_active_task(client):
    task_data = await create_ready_coding_task(client)
    first_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    second_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert second_response.json()["data"]["id"] == first_response.json()["data"]["id"]

    queue_response = await client.get("/api/v2/execution-runs?statuses=queued&limit=10")
    assert queue_response.status_code == 200
    matching = [
        item for item in queue_response.json()["data"]
        if item["coding_task_id"] == task_data["id"]
    ]
    assert len(matching) == 1


@pytest.mark.asyncio
async def test_delivery_v2_dispatch_respects_concurrency_limit(client, db_session):
    first_task_data = await create_ready_coding_task(client)
    second_task_data = await create_ready_coding_task(client)
    first_response = await client.post(
        f"/api/v2/coding-tasks/{first_task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    second_response = await client.post(
        f"/api/v2/coding-tasks/{second_task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert first_response.status_code == 201
    assert second_response.status_code == 201

    first_run = await delivery_repository.get_execution_run(db_session, first_response.json()["data"]["id"])
    assert first_run is not None
    await delivery_repository.update_execution_run(db_session, first_run, status=ExecutionRunStatus.RUNNING)
    await db_session.commit()

    dispatch_response = await client.post(
        f"/api/v2/execution-runs/{second_response.json()['data']['id']}/dispatch"
    )
    assert dispatch_response.status_code == 400
    assert "concurrency limit" in dispatch_response.json()["message"]


@pytest.mark.asyncio
async def test_delivery_v2_derives_task_scope_from_local_context(client):
    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Update the delivery dashboard page and backend delivery status API.",
            "source_type": "new_requirement",
        },
    )
    assert demand_response.status_code == 201
    demand_id = demand_response.json()["data"]["id"]

    spec_response = await client.post(
        f"/api/v2/demands/{demand_id}/spec",
        json={"auto_approve_low_risk": True},
    )
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]

    repo_context_response = await client.post(
        f"/api/v2/demands/{demand_id}/repo-context",
        json={},
    )
    assert repo_context_response.status_code == 201
    repo_context_data = repo_context_response.json()["data"]
    assert repo_context_data["provider"] == "local"
    assert "frontend/src/app/pages/DeliveryV2Page.tsx" in repo_context_data["discovered_files_json"]
    assert "backend/app/modules/delivery/service.py" in repo_context_data["discovered_files_json"]

    impact_response = await client.post(
        f"/api/v2/demands/{demand_id}/impact-analysis",
        json={"repo_context_id": repo_context_data["id"]},
    )
    assert impact_response.status_code == 201
    impact_data = impact_response.json()["data"]
    assert "frontend/src/app/pages/DeliveryV2Page.tsx" in impact_data["affected_files_json"]
    assert "backend/app/modules/delivery/service.py" in impact_data["affected_files_json"]

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={},
    )
    assert task_response.status_code == 201
    task_data = task_response.json()["data"]
    assert "frontend/src/app/pages" in task_data["allowed_paths_json"]
    assert "backend/app/modules/delivery" in task_data["allowed_paths_json"]
    assert "README.md" not in task_data["allowed_paths_json"]
    assert "frontend/package.json" not in task_data["allowed_paths_json"]
    assert "npm run build" in task_data["required_checks_json"]
    assert "python -m pytest" in task_data["required_checks_json"]


@pytest.mark.asyncio
async def test_delivery_v2_failed_checks_record_evidence_and_can_retry(client, generated_worktrees):
    failing_check = "python -m pytest tests/not_exists_for_delivery_failure.py -q"
    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Add a compact execution status badge to the delivery dashboard.",
            "source_type": "new_requirement",
        },
    )
    assert demand_response.status_code == 201
    demand_id = demand_response.json()["data"]["id"]

    spec_response = await client.post(
        f"/api/v2/demands/{demand_id}/spec",
        json={"auto_approve_low_risk": True},
    )
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]

    repo_context_response = await client.post(
        f"/api/v2/demands/{demand_id}/repo-context",
        json={},
    )
    assert repo_context_response.status_code == 201
    repo_context_data = repo_context_response.json()["data"]

    impact_response = await client.post(
        f"/api/v2/demands/{demand_id}/impact-analysis",
        json={"repo_context_id": repo_context_data["id"]},
    )
    assert impact_response.status_code == 201

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={
            "allowed_paths": ["backend/app"],
            "required_checks": [failing_check],
        },
    )
    assert task_response.status_code == 201
    task_data = task_response.json()["data"]

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    failed_run = dispatch_response.json()["data"]
    remember_worktree(failed_run, generated_worktrees)
    assert failed_run["status"] == "failed"
    assert failed_run["result_summary"] == "Required checks failed (0/1 passed)."

    check_result = failed_run["evidence_json"]["dispatch"]["check_results"][0]
    assert check_result["command"] == failing_check
    assert check_result["status"] == "failed"
    assert check_result["exit_code"] != 0
    assert check_result["stdout_tail"] or check_result["stderr_tail"] or check_result["error"]
    assert any(log["level"] == "error" and failing_check in log["message"] for log in failed_run["logs"])

    failed_detail_response = await client.get(f"/api/v2/demands/{demand_id}")
    assert failed_detail_response.status_code == 200
    failed_detail = failed_detail_response.json()["data"]
    assert failed_detail["coding_tasks"][0]["status"] == "blocked"
    assert any(
        gate["gate_type"] == "self_test_passed" and gate["status"] == "failed"
        for gate in failed_detail["gate_checks"]
    )

    retry_response = await client.post(f"/api/v2/coding-tasks/{task_data['id']}/retry")
    assert retry_response.status_code == 200
    retry_data = retry_response.json()["data"]
    remember_worktree(retry_data, generated_worktrees)
    assert retry_data["status"] == "failed"
    assert retry_data["trigger_mode"] == "manual_retry"
    assert retry_data["evidence_json"]["dispatch"]["check_results"][0]["status"] == "failed"

    retry_detail_response = await client.get(f"/api/v2/demands/{demand_id}")
    assert retry_detail_response.status_code == 200
    retry_detail = retry_detail_response.json()["data"]
    assert retry_detail["coding_tasks"][0]["status"] == "blocked"
    assert len(retry_detail["coding_tasks"][0]["execution_runs"]) == 2


@pytest.mark.asyncio
async def test_delivery_v2_dispatch_redacts_sensitive_evidence_and_logs(client, generated_worktrees):
    raw_token = "secret-token-1234567890"
    failing_check = f"python -m pytest tests/not_exists_for_delivery_failure.py --token {raw_token} -q"
    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Add a compact execution status badge to the delivery dashboard.",
            "source_type": "new_requirement",
        },
    )
    assert demand_response.status_code == 201
    demand_id = demand_response.json()["data"]["id"]

    spec_response = await client.post(
        f"/api/v2/demands/{demand_id}/spec",
        json={"auto_approve_low_risk": True},
    )
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={
            "allowed_paths": ["backend/app"],
            "required_checks": [failing_check],
        },
    )
    assert task_response.status_code == 201
    task_data = task_response.json()["data"]

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    failed_run = dispatch_response.json()["data"]
    remember_worktree(failed_run, generated_worktrees)

    persisted_text = json.dumps(
        {
            "evidence_json": failed_run["evidence_json"],
            "result_summary": failed_run["result_summary"],
            "logs": failed_run["logs"],
        },
        ensure_ascii=False,
    )
    assert raw_token not in persisted_text
    assert "[REDACTED]" in persisted_text


@pytest.mark.asyncio
async def test_delivery_v2_codex_command_hook_records_invocation(client, generated_worktrees, monkeypatch):
    monkeypatch.setattr(settings, "execution_codex_enabled", True)
    monkeypatch.setattr(
        settings,
        "execution_codex_command_template",
        "python -c \"from pathlib import Path; Path('backend/app/codex_hook_output.py').write_text('GENERATED = True\\n', encoding='utf-8')\"",
    )
    monkeypatch.setattr(settings, "execution_codex_preflight_command", "python --version")
    monkeypatch.setattr(settings, "execution_codex_preflight_timeout_seconds", 30)
    monkeypatch.setattr(settings, "execution_codex_timeout_seconds", 30)

    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Add a compact execution status badge to the delivery dashboard.",
            "source_type": "new_requirement",
        },
    )
    assert demand_response.status_code == 201
    demand_id = demand_response.json()["data"]["id"]

    spec_response = await client.post(
        f"/api/v2/demands/{demand_id}/spec",
        json={"auto_approve_low_risk": True},
    )
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={
            "allowed_paths": ["backend/app"],
            "required_checks": ["python -m compileall app"],
        },
    )
    assert task_response.status_code == 201
    task_data = task_response.json()["data"]

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    dispatched_run = dispatch_response.json()["data"]
    remember_worktree(dispatched_run, generated_worktrees)

    dispatch = dispatched_run["evidence_json"]["dispatch"]
    invocation = dispatch["codex_invocation"]
    assert dispatched_run["status"] == "succeeded"
    assert invocation["enabled"] is True
    assert invocation["status"] == "passed"
    assert invocation["exit_code"] == 0
    assert invocation["preflight"]["status"] == "passed"
    assert invocation["preflight"]["exit_code"] == 0
    assert (
        Path(dispatch["workspace_root"], "backend/app/codex_hook_output.py").read_text(encoding="utf-8")
        == "GENERATED = True\n"
    )
    assert Path(invocation["prompt_file"]).exists()
    assert "backend/app/codex_hook_output.py" in invocation["changed_files"]
    assert dispatch["check_results"][0]["status"] == "passed"
    assert any(log["message"] == "Codex execution command completed." for log in dispatched_run["logs"])


@pytest.mark.asyncio
async def test_delivery_v2_codex_preflight_failure_blocks_execution(
    client,
    generated_worktrees,
    monkeypatch,
):
    monkeypatch.setattr(settings, "execution_codex_enabled", True)
    monkeypatch.setattr(
        settings,
        "execution_codex_preflight_command",
        "python -c \"raise SystemExit(9)\"",
    )
    monkeypatch.setattr(settings, "execution_codex_preflight_timeout_seconds", 30)
    monkeypatch.setattr(
        settings,
        "execution_codex_command_template",
        "python -c \"from pathlib import Path; Path('backend/app/should_not_run.py').write_text('bad', encoding='utf-8')\"",
    )
    monkeypatch.setattr(settings, "execution_codex_timeout_seconds", 30)

    task_data = await create_ready_coding_task(client)

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    dispatched_run = dispatch_response.json()["data"]
    remember_worktree(dispatched_run, generated_worktrees)

    dispatch = dispatched_run["evidence_json"]["dispatch"]
    invocation = dispatch["codex_invocation"]
    assert dispatched_run["status"] == "failed"
    assert dispatched_run["result_summary"] == "Codex execution preflight failed."
    assert invocation["status"] == "failed"
    assert invocation["preflight"]["status"] == "failed"
    assert invocation["preflight"]["exit_code"] == 9
    assert invocation["error"] == "Codex execution preflight failed."
    assert dispatch["check_results"] == []
    assert not Path(dispatch["workspace_root"], "backend/app/should_not_run.py").exists()


@pytest.mark.asyncio
async def test_delivery_v2_codex_command_hook_blocks_out_of_scope_changes(
    client,
    generated_worktrees,
    monkeypatch,
):
    monkeypatch.setattr(settings, "execution_codex_enabled", True)
    monkeypatch.setattr(
        settings,
        "execution_codex_command_template",
        "python -c \"from pathlib import Path; Path('codex-hook-output.txt').write_text('ok', encoding='utf-8')\"",
    )
    monkeypatch.setattr(settings, "execution_codex_timeout_seconds", 30)

    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Add a compact execution status badge to the delivery dashboard.",
            "source_type": "new_requirement",
        },
    )
    assert demand_response.status_code == 201
    demand_id = demand_response.json()["data"]["id"]

    spec_response = await client.post(
        f"/api/v2/demands/{demand_id}/spec",
        json={"auto_approve_low_risk": True},
    )
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={
            "allowed_paths": ["backend/app"],
            "required_checks": ["python -m compileall app"],
        },
    )
    assert task_response.status_code == 201
    task_data = task_response.json()["data"]

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    dispatched_run = dispatch_response.json()["data"]
    remember_worktree(dispatched_run, generated_worktrees)

    dispatch = dispatched_run["evidence_json"]["dispatch"]
    invocation = dispatch["codex_invocation"]
    assert dispatched_run["status"] == "failed"
    assert dispatched_run["result_summary"] == "Codex execution changed files outside allowed paths."
    assert invocation["status"] == "failed"
    assert invocation["changed_files"] == ["codex-hook-output.txt"]
    assert invocation["changed_file_violations"] == ["codex-hook-output.txt"]
    assert invocation["error"] == "Changed files are outside the allowed paths."
    assert dispatch["check_results"] == []


@pytest.mark.asyncio
async def test_delivery_v2_codex_command_hook_records_command_failure(
    client,
    generated_worktrees,
    monkeypatch,
):
    monkeypatch.setattr(settings, "execution_codex_enabled", True)
    monkeypatch.setattr(
        settings,
        "execution_codex_command_template",
        "python -c \"raise SystemExit(7)\"",
    )
    monkeypatch.setattr(settings, "execution_codex_timeout_seconds", 30)

    task_data = await create_ready_coding_task(client)

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    dispatched_run = dispatch_response.json()["data"]
    remember_worktree(dispatched_run, generated_worktrees)

    dispatch = dispatched_run["evidence_json"]["dispatch"]
    invocation = dispatch["codex_invocation"]
    assert dispatched_run["status"] == "failed"
    assert dispatched_run["result_summary"] == "Codex execution command failed."
    assert invocation["status"] == "failed"
    assert invocation["exit_code"] == 7
    assert invocation["changed_files"] == []
    assert dispatch["check_results"] == []


@pytest.mark.asyncio
async def test_delivery_v2_codex_command_hook_records_timeout(
    client,
    generated_worktrees,
    monkeypatch,
):
    monkeypatch.setattr(settings, "execution_codex_enabled", True)
    monkeypatch.setattr(
        settings,
        "execution_codex_command_template",
        "python -c \"import time; time.sleep(3)\"",
    )
    monkeypatch.setattr(settings, "execution_codex_timeout_seconds", 1)

    task_data = await create_ready_coding_task(client)

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    dispatched_run = dispatch_response.json()["data"]
    remember_worktree(dispatched_run, generated_worktrees)

    dispatch = dispatched_run["evidence_json"]["dispatch"]
    invocation = dispatch["codex_invocation"]
    assert dispatched_run["status"] == "failed"
    assert dispatched_run["result_summary"] == "Codex execution timed out."
    assert invocation["status"] == "failed"
    assert invocation["exit_code"] is None
    assert "Timed out after 1 seconds." in invocation["error"]
    assert invocation["changed_files"] == []
    assert invocation["changed_file_violations"] == []
    assert dispatch["check_results"] == []


@pytest.mark.asyncio
async def test_delivery_v2_auto_repair_uses_failed_check_context(
    client,
    generated_worktrees,
    monkeypatch,
):
    monkeypatch.setattr(settings, "execution_codex_enabled", True)
    monkeypatch.setattr(settings, "execution_codex_preflight_command", "")
    monkeypatch.setattr(
        settings,
        "execution_codex_command_template",
        (
            "python -c \"from pathlib import Path; "
            "prompt=Path(r'{prompt_file}').read_text(encoding='utf-8'); "
            "target=Path('backend/app/auto_repair_probe.py'); "
            "target.write_text('FIXED = True\\n' if 'Repair Context' in prompt else 'def broken(:\\n', encoding='utf-8')\""
        ),
    )
    monkeypatch.setattr(settings, "execution_codex_timeout_seconds", 30)
    monkeypatch.setattr(settings, "execution_auto_repair_max_attempts", 1)

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    failed_run = dispatch_response.json()["data"]
    remember_worktree(failed_run, generated_worktrees)
    assert failed_run["status"] == "failed"
    assert failed_run["evidence_json"]["dispatch"]["check_results"][0]["status"] == "failed"

    repair_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/auto-repair",
        json={"executor_type": "codex", "max_attempts": 1},
    )
    assert repair_response.status_code == 200
    repair_runs = repair_response.json()["data"]
    assert len(repair_runs) == 1
    repaired_run = repair_runs[0]
    remember_worktree(repaired_run, generated_worktrees)

    assert repaired_run["status"] == "succeeded"
    assert repaired_run["trigger_mode"] == "auto_repair"
    repair_context = repaired_run["evidence_json"]["execution_allowed"]["repair_context"]
    assert repair_context["source_run_id"] == failed_run["id"]
    assert repair_context["attempt"] == 1
    assert repair_context["max_attempts"] == 1
    assert repair_context["failed_checks"][0]["command"] == "python -m compileall app"
    assert repair_context["repair_chain"] == [failed_run["id"]]
    assert repaired_run["evidence_json"]["dispatch"]["check_results"][0]["status"] == "passed"

    prompt_file = repaired_run["evidence_json"]["dispatch"]["codex_invocation"]["prompt_file"]
    assert "Repair Context" in Path(prompt_file).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_delivery_v2_auto_repair_stops_after_max_attempts(
    client,
    generated_worktrees,
    monkeypatch,
):
    monkeypatch.setattr(settings, "execution_codex_enabled", True)
    monkeypatch.setattr(settings, "execution_codex_preflight_command", "")
    monkeypatch.setattr(
        settings,
        "execution_codex_command_template",
        "python -c \"from pathlib import Path; Path('backend/app/auto_repair_probe.py').write_text('def broken(:\\n', encoding='utf-8')\"",
    )
    monkeypatch.setattr(settings, "execution_codex_timeout_seconds", 30)

    task_data = await create_ready_coding_task(client, allowed_paths=["backend/app"])

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    failed_run = dispatch_response.json()["data"]
    remember_worktree(failed_run, generated_worktrees)
    assert failed_run["status"] == "failed"

    repair_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/auto-repair",
        json={"executor_type": "codex", "max_attempts": 1},
    )
    assert repair_response.status_code == 200
    repair_runs = repair_response.json()["data"]
    assert len(repair_runs) == 1
    repair_run = repair_runs[0]
    remember_worktree(repair_run, generated_worktrees)
    assert repair_run["status"] == "failed"
    assert repair_run["trigger_mode"] == "auto_repair"
    assert repair_run["evidence_json"]["execution_allowed"]["repair_context"]["source_run_id"] == failed_run["id"]


@pytest.mark.asyncio
async def test_delivery_v2_auto_repair_blocks_high_risk_tasks(client, generated_worktrees):
    failing_check = "python -m pytest tests/not_exists_for_auto_repair_high_risk.py -q"
    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Change login permission logic and migrate production user tokens.",
            "source_type": "bug_report",
        },
    )
    assert demand_response.status_code == 201
    demand_id = demand_response.json()["data"]["id"]

    spec_response = await client.post(f"/api/v2/demands/{demand_id}/spec", json={})
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]
    assert spec_data["status"] == "manual_review"

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={
            "allowed_paths": ["backend/app"],
            "required_checks": [failing_check],
        },
    )
    assert task_response.status_code == 201
    task_data = task_response.json()["data"]

    approval_response = await client.post(
        f"/api/v2/demands/{demand_id}/manual-approval",
        json={
            "approved": True,
            "approver_ref": "tester",
            "note": "Approved only for manual execution; automatic repair remains blocked.",
        },
    )
    assert approval_response.status_code == 200
    approval_data = approval_response.json()["data"]
    assert approval_data["manual_approval_status"] == "approved"
    assert approval_data["manual_approval_ref"] == "tester"
    assert approval_data["manual_approval_user_id"] is None
    assert approval_data["manual_approval_at"]

    run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert run_response.status_code == 201
    run_data = run_response.json()["data"]

    dispatch_response = await client.post(f"/api/v2/execution-runs/{run_data['id']}/dispatch")
    assert dispatch_response.status_code == 200
    failed_run = dispatch_response.json()["data"]
    remember_worktree(failed_run, generated_worktrees)
    assert failed_run["status"] == "failed"

    repair_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/auto-repair",
        json={"executor_type": "codex", "max_attempts": 1},
    )
    assert repair_response.status_code == 400
    assert "Automatic repair is blocked for L2/L3 risk tasks" in repair_response.text


@pytest.mark.asyncio
async def test_delivery_v2_high_risk_requires_manual_review(client, generated_worktrees):
    demand_response = await client.post(
        "/api/v2/demands",
        json={
            "raw_input": "Change login permission logic and migrate production user tokens.",
            "source_type": "bug_report",
        },
    )
    assert demand_response.status_code == 201
    demand_id = demand_response.json()["data"]["id"]

    spec_response = await client.post(f"/api/v2/demands/{demand_id}/spec", json={})
    assert spec_response.status_code == 201
    spec_data = spec_response.json()["data"]
    assert spec_data["status"] == "manual_review"

    detail_response = await client.get(f"/api/v2/demands/{demand_id}")
    detail_data = detail_response.json()["data"]
    assert detail_data["status"] == "spec_manual_required"
    assert detail_data["risk_level"] == "L2"
    assert any(gate["status"] == "manual_required" for gate in detail_data["gate_checks"])

    task_response = await client.post(
        f"/api/v2/spec-cards/{spec_data['id']}/coding-task",
        json={
            "allowed_paths": ["backend/app"],
            "required_checks": ["python -m compileall app"],
        },
    )
    assert task_response.status_code == 201
    task_data = task_response.json()["data"]
    assert task_data["status"] == "draft"

    blocked_run_response = await client.post(
        f"/api/v2/coding-tasks/{task_data['id']}/runs",
        json={"executor_type": "codex", "trigger_mode": "manual"},
    )
    assert blocked_run_response.status_code == 201
    blocked_run = blocked_run_response.json()["data"]
    assert blocked_run["status"] == "blocked"

    approval_response = await client.post(
        f"/api/v2/demands/{demand_id}/manual-approval",
        json={
            "approved": True,
            "approver_ref": "tester",
            "note": "Scope and execution risk accepted for test.",
        },
    )
    assert approval_response.status_code == 200
    approved_detail = approval_response.json()["data"]
    assert approved_detail["manual_approval_status"] == "approved"
    assert approved_detail["manual_approval_ref"] == "tester"
    assert approved_detail["manual_approval_user_id"] is None
    assert approved_detail["manual_approval_at"]
    assert approved_detail["spec_cards"][0]["status"] == "approved"
    assert approved_detail["coding_tasks"][0]["status"] == "ready"
    assert any(
        gate["gate_type"] == "execution_allowed"
        and gate["status"] == "passed"
        and gate["evidence_json"]["approval_type"] == "manual"
        for gate in approved_detail["gate_checks"]
    )

    retry_response = await client.post(f"/api/v2/coding-tasks/{task_data['id']}/retry")
    assert retry_response.status_code == 200
    retry_data = retry_response.json()["data"]
    remember_worktree(retry_data, generated_worktrees)
    assert retry_data["status"] == "succeeded"
    assert retry_data["trigger_mode"] == "manual_retry"
    assert retry_data["evidence_json"]["execution_allowed"]["manual_approved"] is True
