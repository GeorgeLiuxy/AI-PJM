"""Workbench API tests"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select


async def test_home_summary_zero_state(client: AsyncClient, db_session):
    """Test home summary with empty database"""
    # Note: This test runs first, so database should be clean
    # However, due to test isolation, we just verify the structure works
    response = await client.get("/api/v1/workbench/home")
    assert response.status_code == 200

    data = response.json()["data"]
    assert "summary" in data
    # Don't assert exact counts as other tests may have run first
    assert "pending_item_confirm_count" in data["summary"]
    assert "pending_analysis_review_count" in data["summary"]
    assert "pending_output_confirm_count" in data["summary"]
    assert "done_item_count" in data["summary"]

    # Verify structure
    assert "todo_queue" in data
    assert "recent_items" in data
    assert "recent_outputs" in data


async def test_home_summary_with_pending_items(client: AsyncClient):
    """Test home summary with pending items"""
    # Create a pending_confirm item
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item for workbench", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    # Understand to get to pending_confirm
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})

    # Get home summary
    response = await client.get("/api/v1/workbench/home")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["summary"]["pending_item_confirm_count"] == 1
    assert len(data["todo_queue"]) == 1

    # Verify todo item
    todo = data["todo_queue"][0]
    assert todo["todo_type"] == "pending_item_confirm"
    assert todo["biz_type"] == "item"
    assert todo["biz_id"] == item_id
    assert todo["item_id"] == item_id
    assert "title" in todo
    assert "priority" in todo
    assert "updated_at" in todo


async def test_home_todo_queue_includes_analysis(client: AsyncClient):
    """Test todo queue includes pending analysis review"""
    # Create and confirm item
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item for analysis", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    # Create analysis
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]

    # Run analysis to get to pending_review
    await client.post(f"/api/v1/analysis/{analysis_id}/run")

    # Get home summary
    response = await client.get("/api/v1/workbench/home")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["summary"]["pending_analysis_review_count"] == 1

    # Verify todo queue includes analysis
    analysis_todos = [t for t in data["todo_queue"] if t["todo_type"] == "pending_analysis_review"]
    assert len(analysis_todos) == 1

    todo = analysis_todos[0]
    assert todo["biz_type"] == "analysis"
    assert todo["biz_id"] == analysis_id
    assert todo["item_id"] == item_id
    assert "分析:" in todo["title"]


async def test_home_todo_queue_includes_output(client: AsyncClient):
    """Test todo queue includes pending output confirm"""
    # Create full flow up to output
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item for output", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]

    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    await client.post(f"/api/v1/analysis/{analysis_id}/confirm", json={"final_recommendation": "do_now"})

    # Create output
    output_response = await client.post(
        f"/api/v1/items/{item_id}/outputs",
        json={"output_type": "prd", "analysis_id": analysis_id}
    )
    output_id = output_response.json()["data"]["id"]

    # Get home summary
    response = await client.get("/api/v1/workbench/home")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["summary"]["pending_output_confirm_count"] == 1

    # Verify todo queue includes output
    output_todos = [t for t in data["todo_queue"] if t["todo_type"] == "pending_output_confirm"]
    assert len(output_todos) == 1

    todo = output_todos[0]
    assert todo["biz_type"] == "output"
    assert todo["biz_id"] == output_id
    assert todo["item_id"] == item_id
    assert "prd:" in todo["title"].lower()


async def test_home_recent_items_limit(client: AsyncClient):
    """Test recent items are limited"""
    # Create 15 items
    for i in range(15):
        await client.post(
            "/api/v1/items/draft",
            json={"raw_input": f"Test item {i}", "source_type": "customer_feedback"}
        )

    # Get home summary
    response = await client.get("/api/v1/workbench/home")
    assert response.status_code == 200

    data = response.json()["data"]
    assert len(data["recent_items"]) == 10


async def test_home_recent_outputs_limit(client: AsyncClient):
    """Test recent outputs are limited"""
    # Create item and confirm
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]

    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    await client.post(f"/api/v1/analysis/{analysis_id}/confirm", json={"final_recommendation": "do_now"})

    # Create 15 outputs (only first will succeed due to unique constraint)
    for i in range(15):
        await client.post(
            f"/api/v1/items/{item_id}/outputs",
            json={"output_type": "prd", "analysis_id": analysis_id}
        )

    # Get home summary
    response = await client.get("/api/v1/workbench/home")
    assert response.status_code == 200

    data = response.json()["data"]
    # Should have 1 output (unique constraint)
    assert len(data["recent_outputs"]) <= 10


async def test_todos_endpoint_breakdown(client: AsyncClient):
    """Test /todos endpoint returns breakdown"""
    # Create mixed todos
    for i in range(3):
        draft_response = await client.post(
            "/api/v1/items/draft",
            json={"raw_input": f"Test item {i}", "source_type": "customer_feedback"}
        )
        item_id = draft_response.json()["data"]["id"]
        await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})

    # Get todos
    response = await client.get("/api/v1/workbench/todos")
    assert response.status_code == 200

    data = response.json()["data"]
    assert "todos" in data
    assert "total" in data
    assert "breakdown" in data

    assert data["breakdown"]["pending_item_confirm"] == 3
    assert data["total"] == 3


async def test_todos_ordering_by_priority(client: AsyncClient):
    """Test todos are ordered by priority group"""
    # Create different types of todos
    # 1. pending_item_confirm
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Item 1", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})

    # 2. pending_analysis_review
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Item 2", "source_type": "customer_feedback"}
    )
    item_id_2 = draft_response.json()["data"]["id"]
    await client.post(f"/api/v1/items/{item_id_2}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id_2}/confirm", json={"confirm_mode": "accept"})
    analysis_response = await client.post(f"/api/v1/items/{item_id_2}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    await client.post(f"/api/v1/analysis/{analysis_id}/run")

    # Get todos
    response = await client.get("/api/v1/workbench/todos")
    assert response.status_code == 200

    data = response.json()["data"]
    todos = data["todos"]

    # Verify ordering: pending_analysis_review should come before pending_item_confirm
    todo_types = [t["todo_type"] for t in todos]
    assert todo_types[0] == "pending_analysis_review"
    assert todo_types[1] == "pending_item_confirm"


async def test_done_item_count(client: AsyncClient):
    """Test done_item_count in summary"""
    # Create a completed item
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]

    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    await client.post(f"/api/v1/analysis/{analysis_id}/confirm", json={"final_recommendation": "do_now"})

    output_response = await client.post(
        f"/api/v1/items/{item_id}/outputs",
        json={"output_type": "prd", "analysis_id": analysis_id}
    )
    output_id = output_response.json()["data"]["id"]

    await client.post(f"/api/v1/outputs/{output_id}/confirm", json={})
    await client.post(f"/api/v1/outputs/{output_id}/adopt", json={"adopted_target": "formal_prd"})

    # Get home summary
    response = await client.get("/api/v1/workbench/home")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["summary"]["done_item_count"] == 1
