"""Item API tests"""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_create_draft(client: AsyncClient):
    """Test creating a draft item"""
    response = await client.post(
        "/api/v1/items/draft",
        json={
            "raw_input": "客户希望审批节点支持抄送",
            "source_type": "customer_feedback"
        }
    )
    assert response.status_code == 201
    
    data = response.json()
    assert data["code"] == 201
    assert "id" in data["data"]
    assert data["data"]["status"] == "draft"
    assert data["data"]["source_type"] == "customer_feedback"


@pytest.mark.asyncio
async def test_understand_item(client: AsyncClient):
    """Test understanding an item"""
    # First create a draft
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={
            "raw_input": "客户希望审批节点支持抄送",
            "source_type": "customer_feedback"
        }
    )
    item_id = draft_response.json()["data"]["id"]
    
    # Then understand it
    response = await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": False}
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["data"]["status"] == "pending_confirm"
    assert "suggestion" in data["data"]
    assert data["data"]["suggestion"]["type_suggestion"] == "improvement"


@pytest.mark.asyncio
async def test_get_item(client: AsyncClient):
    """Test getting an item"""
    # Create and understand an item
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={
            "raw_input": "客户希望审批节点支持抄送",
            "source_type": "customer_feedback"
        }
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": False}
    )
    
    # Get item
    response = await client.get(f"/api/v1/items/{item_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["data"]["id"] == item_id
    assert data["data"]["status"] == "pending_confirm"
    assert "suggestion" in data["data"]


@pytest.mark.asyncio
async def test_confirm_item_accept(client: AsyncClient):
    """Test confirming an item (accept mode)"""
    # Create and understand an item
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={
            "raw_input": "客户希望审批节点支持抄送",
            "source_type": "customer_feedback"
        }
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": False}
    )
    
    # Confirm (accept mode)
    response = await client.post(
        f"/api/v1/items/{item_id}/confirm",
        json={"confirm_mode": "accept"}
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["data"]["status"] == "confirmed"
    assert data["data"]["title_final"] is not None


@pytest.mark.asyncio
async def test_full_item_lifecycle(client: AsyncClient):
    """Test full item lifecycle: draft -> understand -> confirm"""
    # 1. Create draft
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={
            "raw_input": "客户希望审批节点支持抄送",
            "source_type": "customer_feedback"
        }
    )
    assert draft_response.status_code == 201
    item_id = draft_response.json()["data"]["id"]
    assert draft_response.json()["data"]["status"] == "draft"
    
    # 2. Understand
    understand_response = await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": False}
    )
    assert understand_response.status_code == 200
    assert understand_response.json()["data"]["status"] == "pending_confirm"
    
    # 3. Get item
    get_response = await client.get(f"/api/v1/items/{item_id}")
    assert get_response.status_code == 200
    assert get_response.json()["data"]["suggestion"] is not None
    
    # 4. Confirm
    confirm_response = await client.post(
        f"/api/v1/items/{item_id}/confirm",
        json={"confirm_mode": "accept"}
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["data"]["status"] == "confirmed"


# ==================== understand 边界测试 ====================

@pytest.mark.asyncio
async def test_understand_idempotent(client: AsyncClient, db_session: AsyncSession):
    """Test understand idempotency: pending_confirm + force_refresh=false"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    # First understand
    response1 = await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": False}
    )
    suggestion_id_1 = response1.json()["data"]["suggestion"]["id"]

    # Count action_logs
    from app.modules.audit.models import ActionLog
    from sqlalchemy import select
    result = await db_session.execute(
        select(ActionLog).where(ActionLog.biz_id == item_id)
    )
    logs_after_first = result.scalars().all()
    assert len(logs_after_first) == 2  # item_created + item_understood

    # Second understand (idempotent)
    response2 = await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": False}
    )
    suggestion_id_2 = response2.json()["data"]["suggestion"]["id"]
    assert suggestion_id_1 == suggestion_id_2

    # Should NOT write another action_log
    result = await db_session.execute(
        select(ActionLog).where(ActionLog.biz_id == item_id)
    )
    logs_after_second = result.scalars().all()
    assert len(logs_after_second) == 2  # Still 2, no duplicate


@pytest.mark.asyncio
async def test_understand_force_refresh_unsupported(client: AsyncClient):
    """Test understand with force_refresh=true returns 400"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})

    response = await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": True}
    )
    assert response.status_code == 400
    assert "Force refresh is not supported" in response.json()["message"]


@pytest.mark.asyncio
async def test_understand_wrong_status(client: AsyncClient):
    """Test understand on confirmed status returns 400"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    response = await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": False}
    )
    assert response.status_code == 400
    assert "Only draft items can be understood" in response.json()["message"]

@pytest.mark.asyncio
async def test_understand_inconsistent_state(client: AsyncClient, db_session: AsyncSession):
    """Test understand on item with draft status but existing suggestion returns 400"""
    from app.modules.item.models import Item, ItemSuggestion
    from app.common.enums import ItemStatus
    from sqlalchemy import select

    # Create an item in draft status
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    # Manually create a suggestion for this item (simulating inconsistent state)
    # This simulates a case where the item has draft status but already has a suggestion
    suggestion = ItemSuggestion(
        item_id=item_id,
        title_suggestion="审批节点支持抄送",
        type_suggestion="improvement",
        priority_suggestion="medium",
        project_suggestion="流程审批项目",
        modules_suggestion_json=["approval", "notification"],
        impact_scope_suggestion="影响审批流程模块",
        pending_questions_json=["是否需要支持多级抄送?"],
        similar_cases_json=[{"case": "类似的抄送功能"}],
        recommendation_suggestion="建议实现此功能",
        confidence_score=85.50,
        evidence_summary="客户多次提及此需求",
        ai_model_version="mock-v1",
        is_confirmed=False
    )
    db_session.add(suggestion)
    await db_session.commit()

    # Count action_logs before the call
    from app.modules.audit.models import ActionLog
    result = await db_session.execute(
        select(ActionLog).where(ActionLog.biz_id == item_id)
    )
    logs_before = result.scalars().all()
    count_before = len(logs_before)

    # Try to understand - should fail because item is draft but has suggestion (inconsistent state)
    response = await client.post(
        f"/api/v1/items/{item_id}/understand",
        json={"force_refresh": False}
    )
    
    # Should return 400 with inconsistent state error
    assert response.status_code == 400
    assert "inconsistent state" in response.json()["message"].lower() or "draft.*suggestion" in response.json()["message"].lower()

    # Verify no duplicate action_log was written
    result = await db_session.execute(
        select(ActionLog).where(ActionLog.biz_id == item_id)
    )
    logs_after = result.scalars().all()
    count_after = len(logs_after)
    
    # Count should be the same (no new action_log written)
    assert count_after == count_before


# ==================== confirm 边界测试 ====================

@pytest.mark.asyncio
async def test_confirm_modify_mode(client: AsyncClient):
    """Test confirm with modify mode"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})

    response = await client.post(
        f"/api/v1/items/{item_id}/confirm",
        json={
            "confirm_mode": "modify",
            "overrides": {
                "title_final": "修改后的标题",
                "final_type": "improvement",
                "final_priority": "medium",
                "final_project": "新项目"
            }
        }
    )
    assert response.status_code == 200
    data = response.json()
    assert data["data"]["title_final"] == "修改后的标题"
    assert data["data"]["final_priority"] == "medium"


@pytest.mark.asyncio
async def test_confirm_no_suggestion(client: AsyncClient):
    """Test confirm without suggestion returns 400"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    response = await client.post(
        f"/api/v1/items/{item_id}/confirm",
        json={"confirm_mode": "accept"}
    )
    assert response.status_code == 400
    assert "has no suggestion to confirm" in response.json()["message"]


@pytest.mark.asyncio
async def test_confirm_wrong_status(client: AsyncClient):
    """Test confirm on already confirmed item returns 400"""
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    response = await client.post(
        f"/api/v1/items/{item_id}/confirm",
        json={"confirm_mode": "accept"}
    )
    assert response.status_code == 400
    assert "Only pending_confirm items can be confirmed" in response.json()["message"]


# ==================== action_logs 验证测试 ====================

@pytest.mark.asyncio
async def test_action_logs_item_created(client: AsyncClient, db_session: AsyncSession):
    """Test action log for item_created event"""
    from app.modules.audit.models import ActionLog
    from sqlalchemy import select

    response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = response.json()["data"]["id"]

    result = await db_session.execute(
        select(ActionLog).where(ActionLog.biz_id == item_id)
    )
    logs = result.scalars().all()

    assert len(logs) == 1
    log = logs[0]
    assert log.biz_type == "item"
    assert log.action_type == "item_created"
    assert log.operator_type == "user"
    assert log.from_status is None
    assert log.to_status == "draft"


@pytest.mark.asyncio
async def test_action_logs_item_understood(client: AsyncClient, db_session: AsyncSession):
    """Test action log for item_understood event"""
    from app.modules.audit.models import ActionLog
    from sqlalchemy import select

    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})

    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == item_id)
        .where(ActionLog.action_type == "item_understood")
    )
    log = result.scalar_one()

    assert log.biz_type == "item"
    assert log.action_type == "item_understood"
    assert log.operator_type == "ai"
    assert log.from_status == "draft"
    assert log.to_status == "pending_confirm"
    assert "suggestion_id" in log.action_payload


@pytest.mark.asyncio
async def test_action_logs_item_confirmed(client: AsyncClient, db_session: AsyncSession):
    """Test action log for item_confirmed event"""
    from app.modules.audit.models import ActionLog
    from sqlalchemy import select

    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == item_id)
        .where(ActionLog.action_type == "item_confirmed")
    )
    log = result.scalar_one()

    assert log.biz_type == "item"
    assert log.action_type == "item_confirmed"
    assert log.operator_type == "user"
    assert log.from_status == "pending_confirm"
    assert log.to_status == "confirmed"
    assert "changes" in log.action_payload
