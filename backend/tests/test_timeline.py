"""Timeline API tests"""

import pytest
from httpx import AsyncClient


async def test_get_item_timeline_full_lifecycle(client: AsyncClient):
    """Test timeline includes all actions from full lifecycle"""
    # Create complete item lifecycle
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item for timeline", "source_type": "customer_feedback"}
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

    # Get timeline
    response = await client.get(f"/api/v1/items/{item_id}/timeline")
    assert response.status_code == 200

    data = response.json()["data"]
    assert data["item_id"] == item_id
    assert "timeline" in data
    assert "total" in data

    timeline = data["timeline"]
    assert len(timeline) > 0

    # Verify timeline contains all action types
    action_types = [event["action_type"] for event in timeline]

    # Item actions
    assert "item_created" in action_types
    assert "item_understood" in action_types
    assert "item_confirmed" in action_types

    # Analysis actions
    assert "analysis_created" in action_types
    assert "analysis_started" in action_types
    assert "analysis_completed" in action_types
    assert "analysis_confirmed" in action_types

    # Output actions
    assert "output_generated" in action_types
    assert "output_confirmed" in action_types
    assert "output_adopted" in action_types


async def test_get_item_timeline_chronological_order(client: AsyncClient):
    """Test timeline is in chronological order (created_at ASC)"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item for ordering", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    # Get timeline
    response = await client.get(f"/api/v1/items/{item_id}/timeline")
    assert response.status_code == 200

    data = response.json()["data"]
    timeline = data["timeline"]

    # Verify chronological order
    for i in range(len(timeline) - 1):
        assert timeline[i]["created_at"] <= timeline[i + 1]["created_at"]


async def test_get_item_timeline_includes_all_biz_types(client: AsyncClient):
    """Test timeline includes item, analysis, and output logs"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item for biz types", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]

    await client.post(f"/api/v1/analysis/{analysis_id}/run")

    # Get timeline
    response = await client.get(f"/api/v1/items/{item_id}/timeline")
    assert response.status_code == 200

    data = response.json()["data"]
    timeline = data["timeline"]

    # Verify all biz types are present
    biz_types = [event["biz_type"] for event in timeline]
    assert "item" in biz_types
    assert "analysis" in biz_types


async def test_get_item_timeline_item_not_found(client: AsyncClient):
    """Test timeline request for non-existent item"""
    response = await client.get("/api/v1/items/99999/timeline")
    assert response.status_code == 404


async def test_get_item_timeline_no_logs(client: AsyncClient):
    """Test timeline for item with no action logs (should not happen in practice)"""
    # This test is theoretical - in practice, creating an item always creates logs
    # But we can test the structure
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    # Get timeline immediately after creation
    response = await client.get(f"/api/v1/items/{item_id}/timeline")
    assert response.status_code == 200

    data = response.json()["data"]
    # Should have at least item_created log
    assert data["total"] >= 1
    assert len(data["timeline"]) >= 1


async def test_timeline_event_structure(client: AsyncClient):
    """Test timeline events have correct structure"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item structure", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    response = await client.get(f"/api/v1/items/{item_id}/timeline")
    assert response.status_code == 200

    data = response.json()["data"]
    timeline = data["timeline"]

    # Check first event structure
    event = timeline[0]
    required_fields = [
        "id", "action_type", "biz_type", "biz_id",
        "operator_type", "operator_ref",
        "from_status", "to_status", "comment", "created_at"
    ]

    for field in required_fields:
        assert field in event


async def test_timeline_multiple_analyses_outputs(client: AsyncClient):
    """Test timeline includes multiple analyses and outputs if they exist"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "Test item for multiple", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    # Create, run, and confirm analysis
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

    # Get timeline
    response = await client.get(f"/api/v1/items/{item_id}/timeline")
    assert response.status_code == 200

    data = response.json()["data"]
    timeline = data["timeline"]

    # Verify analysis and output events are included
    biz_ids = [event["biz_id"] for event in timeline]
    assert analysis_id in biz_ids
    assert output_id in biz_ids
