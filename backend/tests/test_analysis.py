"""Analysis API tests"""

import pytest
from httpx import AsyncClient
from sqlalchemy import select


# ==================== 基础功能测试 ====================

@pytest.mark.asyncio
async def test_create_analysis(client: AsyncClient):
    """Test creating an analysis"""
    # First create and confirm an item
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    # Create analysis
    response = await client.post(f"/api/v1/items/{item_id}/analysis")
    assert response.status_code == 201
    
    data = response.json()
    assert data["code"] == 201
    assert "id" in data["data"]
    assert data["data"]["item_id"] == item_id
    assert data["data"]["status"] == "pending"
    assert data["data"]["analysis_type"] == "impact_assessment"


@pytest.mark.asyncio
async def test_run_analysis(client: AsyncClient):
    """Test running an analysis"""
    # Create and confirm an item, then create analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    # Run analysis
    response = await client.post(f"/api/v1/analysis/{analysis_id}/run")
    assert response.status_code == 200
    
    data = response.json()
    assert data["data"]["status"] == "pending_review"
    assert data["data"]["business_value_score"] == 5
    assert data["data"]["technical_impact_score"] == 4
    assert data["data"]["risk_level"] == "medium"
    assert data["data"]["ai_recommendation"] == "do_now"


@pytest.mark.asyncio
async def test_get_analysis(client: AsyncClient):
    """Test getting an analysis"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Get analysis
    response = await client.get(f"/api/v1/analysis/{analysis_id}")
    assert response.status_code == 200
    
    data = response.json()
    assert data["data"]["id"] == analysis_id
    assert data["data"]["status"] == "pending_review"


@pytest.mark.asyncio
async def test_confirm_analysis(client: AsyncClient):
    """Test confirming an analysis"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Confirm analysis
    response = await client.post(
        f"/api/v1/analysis/{analysis_id}/confirm",
        json={"final_recommendation": "do_now", "review_comment": "确认立即执行"}
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["data"]["status"] == "confirmed"
    assert data["data"]["final_recommendation"] == "do_now"


@pytest.mark.asyncio
async def test_reject_analysis(client: AsyncClient):
    """Test rejecting an analysis"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Reject analysis
    response = await client.post(
        f"/api/v1/analysis/{analysis_id}/reject",
        json={"review_comment": "分析不够深入，需要补充竞品对比"}
    )
    assert response.status_code == 200
    
    data = response.json()
    assert data["data"]["status"] == "pending"  # Back to pending
    assert data["data"]["review_comment"] == "分析不够深入，需要补充竞品对比"


# ==================== 状态流转测试 ====================

@pytest.mark.asyncio
async def test_create_analysis_wrong_item_status(client: AsyncClient):
    """Test create analysis on non-confirmed item returns 400"""
    # Create a draft item (not confirmed)
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    # Try to create analysis on draft item
    response = await client.post(f"/api/v1/items/{item_id}/analysis")
    assert response.status_code == 400
    assert "not in confirmed status" in response.json()["message"]


@pytest.mark.asyncio
async def test_run_analysis_wrong_status(client: AsyncClient):
    """Test run analysis on non-pending analysis returns 400"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Try to run again (now in pending_review)
    response = await client.post(f"/api/v1/analysis/{analysis_id}/run")
    assert response.status_code == 400
    assert "not in pending status" in response.json()["message"]


@pytest.mark.asyncio
async def test_confirm_analysis_wrong_status(client: AsyncClient):
    """Test confirm analysis on non-pending_review analysis returns 400"""
    # Create item, confirm, create analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    # Try to confirm pending analysis
    response = await client.post(
        f"/api/v1/analysis/{analysis_id}/confirm",
        json={"final_recommendation": "do_now"}
    )
    assert response.status_code == 400
    assert "not in pending_review status" in response.json()["message"]


@pytest.mark.asyncio
async def test_reject_analysis_wrong_status(client: AsyncClient):
    """Test reject analysis on non-pending_review analysis returns 400"""
    # Create item, confirm, create analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    # Try to reject pending analysis
    response = await client.post(
        f"/api/v1/analysis/{analysis_id}/reject",
        json={"review_comment": "驳回"}
    )
    assert response.status_code == 400
    assert "not in pending_review status" in response.json()["message"]


# ==================== 边界条件测试 ====================

@pytest.mark.asyncio
async def test_duplicate_analysis(client: AsyncClient):
    """Test duplicate analysis creation returns 400"""
    # Create item, confirm, create first analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    await client.post(f"/api/v1/items/{item_id}/analysis")

    # Try to create second analysis
    response = await client.post(f"/api/v1/items/{item_id}/analysis")
    assert response.status_code == 400
    # 第二次创建被状态检查拦截（item已经是analyzing状态）
    assert "not in confirmed status" in response.json()["message"]


@pytest.mark.asyncio
async def test_confirm_item_status_change(client: AsyncClient):
    """Test confirm changes item status to decided"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]

    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})

    # Create analysis and get analysis_id
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]

    # Get item status after creating analysis
    item_response = await client.get(f"/api/v1/items/{item_id}")
    assert item_response.json()["data"]["status"] == "analyzing"

    # Run and confirm analysis (使用已创建的 analysis_id)
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    await client.post(f"/api/v1/analysis/{analysis_id}/confirm", json={"final_recommendation": "do_now"})

    # Check item status changed to decided
    item_response = await client.get(f"/api/v1/items/{item_id}")
    assert item_response.json()["data"]["status"] == "decided"


@pytest.mark.asyncio
async def test_reject_item_status_unchanged(client: AsyncClient):
    """Test reject keeps item status as analyzing"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Reject analysis
    await client.post(
        f"/api/v1/analysis/{analysis_id}/reject",
        json={"review_comment": "驳回"}
    )
    
    # Check item status is still analyzing
    item_response = await client.get(f"/api/v1/items/{item_id}")
    assert item_response.json()["data"]["status"] == "analyzing"


@pytest.mark.asyncio
async def test_reject_then_run_again(client: AsyncClient):
    """Test reject then run again"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Reject analysis (goes back to pending)
    response = await client.post(
        f"/api/v1/analysis/{analysis_id}/reject",
        json={"review_comment": "驳回，重新分析"}
    )
    assert response.json()["data"]["status"] == "pending"
    
    # Run again
    response = await client.post(f"/api/v1/analysis/{analysis_id}/run")
    assert response.status_code == 200
    assert response.json()["data"]["status"] == "pending_review"


@pytest.mark.asyncio
async def test_full_analysis_lifecycle(client: AsyncClient):
    """Test full analysis lifecycle"""
    # 1. Create and confirm item
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    # 2. Create analysis
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    assert analysis_response.status_code == 201
    analysis_id = analysis_response.json()["data"]["id"]
    assert analysis_response.json()["data"]["status"] == "pending"
    
    # 3. Run analysis
    run_response = await client.post(f"/api/v1/analysis/{analysis_id}/run")
    assert run_response.status_code == 200
    assert run_response.json()["data"]["status"] == "pending_review"
    
    # 4. Get analysis
    get_response = await client.get(f"/api/v1/analysis/{analysis_id}")
    assert get_response.status_code == 200
    
    # 5. Confirm analysis
    confirm_response = await client.post(
        f"/api/v1/analysis/{analysis_id}/confirm",
        json={"final_recommendation": "do_now"}
    )
    assert confirm_response.status_code == 200
    assert confirm_response.json()["data"]["status"] == "confirmed"


# ==================== Action Logs 验证测试 ====================

@pytest.mark.asyncio
async def test_action_log_analysis_created(client: AsyncClient, db_session: AsyncSession):
    """Test action log for analysis_created event"""
    from app.modules.audit.models import ActionLog
    
    # Create item, confirm, create analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    # Check analysis_created log
    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == analysis_id)
        .where(ActionLog.action_type == "analysis_created")
    )
    log = result.scalar_one()
    
    assert log.biz_type == "analysis"
    assert log.action_type == "analysis_created"
    assert log.operator_type == "user"


@pytest.mark.asyncio
async def test_action_log_analysis_started(client: AsyncClient, db_session: AsyncSession):
    """Test action log for analysis_started event"""
    from app.modules.audit.models import ActionLog
    
    # Create item, confirm, create analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Check analysis_started log
    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == analysis_id)
        .where(ActionLog.action_type == "analysis_started")
    )
    log = result.scalar_one()
    
    assert log.biz_type == "analysis"
    assert log.action_type == "analysis_started"
    assert log.operator_type == "ai"


@pytest.mark.asyncio
async def test_action_log_analysis_completed(client: AsyncClient, db_session: AsyncSession):
    """Test action log for analysis_completed event"""
    from app.modules.audit.models import ActionLog
    
    # Create item, confirm, create analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Check analysis_completed log
    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == analysis_id)
        .where(ActionLog.action_type == "analysis_completed")
    )
    log = result.scalar_one()
    
    assert log.biz_type == "analysis"
    assert log.action_type == "analysis_completed"
    assert log.operator_type == "ai"


@pytest.mark.asyncio
async def test_action_log_analysis_confirmed(client: AsyncClient, db_session: AsyncSession):
    """Test action log for analysis_confirmed event"""
    from app.modules.audit.models import ActionLog
    
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    await client.post(f"/api/v1/analysis/{analysis_id}/confirm", json={"final_recommendation": "do_now"})
    
    # Check analysis_confirmed log
    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == analysis_id)
        .where(ActionLog.action_type == "analysis_confirmed")
    )
    log = result.scalar_one()
    
    assert log.biz_type == "analysis"
    assert log.action_type == "analysis_confirmed"
    assert log.operator_type == "user"


@pytest.mark.asyncio
async def test_action_log_analysis_rejected(client: AsyncClient, db_session: AsyncSession):
    """Test action log for analysis_rejected event"""
    from app.modules.audit.models import ActionLog
    
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    await client.post(f"/api/v1/analysis/{analysis_id}/reject", json={"review_comment": "驳回"})
    
    # Check analysis_rejected log
    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == analysis_id)
        .where(ActionLog.action_type == "analysis_rejected")
    )
    log = result.scalar_one()
    
    assert log.biz_type == "analysis"
    assert log.action_type == "analysis_rejected"
    assert log.operator_type == "user"
    assert log.to_status == "pending"  # Back to pending


@pytest.mark.asyncio
async def test_action_log_item_status_changed_to_analyzing(client: AsyncClient, db_session: AsyncSession):
    """Test action log for item_status_changed_to_analyzing event"""
    from app.modules.audit.models import ActionLog
    
    # Create item, confirm, create analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    await client.post(f"/api/v1/items/{item_id}/analysis")
    
    # Check item_status_changed_to_analyzing log
    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == item_id)
        .where(ActionLog.action_type == "item_status_changed_to_analyzing")
    )
    log = result.scalar_one()
    
    assert log.biz_type == "item"
    assert log.action_type == "item_status_changed_to_analyzing"
    assert log.operator_type == "user"
    assert log.from_status == "confirmed"
    assert log.to_status == "analyzing"


@pytest.mark.asyncio
async def test_action_log_item_status_changed_to_decided(client: AsyncClient, db_session: AsyncSession):
    """Test action log for item_status_changed_to_decided event"""
    from app.modules.audit.models import ActionLog
    
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    await client.post(f"/api/v1/analysis/{analysis_id}/confirm", json={"final_recommendation": "do_now"})
    
    # Check item_status_changed_to_decided log
    result = await db_session.execute(
        select(ActionLog)
        .where(ActionLog.biz_id == item_id)
        .where(ActionLog.action_type == "item_status_changed_to_decided")
    )
    log = result.scalar_one()
    
    assert log.biz_type == "item"
    assert log.action_type == "item_status_changed_to_decided"
    assert log.operator_type == "user"
    assert log.from_status == "analyzing"
    assert log.to_status == "decided"


# ==================== 枚举值验证测试 ====================

@pytest.mark.asyncio
async def test_recommendation_enum_validation(client: AsyncClient):
    """Test final_recommendation must be valid enum value"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Try invalid recommendation
    response = await client.post(
        f"/api/v1/analysis/{analysis_id}/confirm",
        json={"final_recommendation": "invalid_value"}
    )
    assert response.status_code == 422  # Pydantic validation error


@pytest.mark.asyncio
async def test_score_range_validation(client: AsyncClient):
    """Test business_value_score and technical_impact_score are in 1-5"""
    # Create item, confirm, create and run analysis
    draft_response = await client.post(
        "/api/v1/items/draft",
        json={"raw_input": "客户希望审批节点支持抄送", "source_type": "customer_feedback"}
    )
    item_id = draft_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/items/{item_id}/understand", json={"force_refresh": False})
    await client.post(f"/api/v1/items/{item_id}/confirm", json={"confirm_mode": "accept"})
    
    analysis_response = await client.post(f"/api/v1/items/{item_id}/analysis")
    analysis_id = analysis_response.json()["data"]["id"]
    
    await client.post(f"/api/v1/analysis/{analysis_id}/run")
    
    # Get analysis and check scores
    response = await client.get(f"/api/v1/analysis/{analysis_id}")
    data = response.json()["data"]
    
    assert 1 <= data["business_value_score"] <= 5
    assert 1 <= data["technical_impact_score"] <= 5
