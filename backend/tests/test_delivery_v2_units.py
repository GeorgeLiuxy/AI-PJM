"""Delivery v2 service rule tests that do not require a database."""

from app.modules.delivery.enums import CodingTaskStatus, DeliveryRiskLevel, GateStatus, SpecStatus
from app.modules.delivery.gates import gate_engine
from app.modules.delivery.service import delivery_service


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


def test_delivery_v2_repo_context_gate_uses_confidence_threshold():
    decision = gate_engine.evaluate_repo_context(
        repo_context_id=1,
        confidence_score=0.55,
        source_refs=["demand.raw_input"],
    )

    assert decision.status == GateStatus.MANUAL_REQUIRED
