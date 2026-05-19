"""Delivery v2 API tests."""

import pytest


@pytest.mark.asyncio
async def test_delivery_v2_demand_to_coding_task(client):
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
    assert dispatched_run["status"] == "succeeded"
    assert dispatched_run["result_summary"] == "Required checks passed (1/1)."
    assert dispatched_run["evidence_json"]["dispatch"]["check_results"][0]["status"] == "passed"
    assert any(log["message"].startswith("Check passed") for log in dispatched_run["logs"])

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


@pytest.mark.asyncio
async def test_delivery_v2_high_risk_requires_manual_review(client):
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
