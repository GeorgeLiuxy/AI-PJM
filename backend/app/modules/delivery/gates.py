"""Hard gate rules for the delivery workflow."""

from dataclasses import dataclass, field

from app.modules.delivery.enums import (
    CodingTaskStatus,
    DeliveryRiskLevel,
    GateStatus,
    GateType,
    SpecStatus,
)


HIGH_RISK_KEYWORDS = {
    "permission",
    "auth",
    "login",
    "payment",
    "billing",
    "delete",
    "migration",
    "production",
    "secret",
    "token",
    "\u6743\u9650",
    "\u767b\u5f55",
    "\u652f\u4ed8",
    "\u8ba1\u8d39",
    "\u5220\u9664",
    "\u8fc1\u79fb",
    "\u751f\u4ea7",
    "\u5bc6\u94a5",
    "\u4ee4\u724c",
}


@dataclass(frozen=True)
class GateDecision:
    """A deterministic gate result."""

    gate_type: str
    status: str
    reason: str
    evidence: dict = field(default_factory=dict)


class DeliveryGateEngine:
    """Central rule engine for workflow gates.

    AI providers may propose content, but these rules decide whether the workflow
    can advance automatically.
    """

    def classify_risk(self, raw_input: str) -> str:
        normalized = raw_input.lower()
        if any(keyword in normalized for keyword in HIGH_RISK_KEYWORDS):
            return DeliveryRiskLevel.L2
        if len(raw_input) < 80:
            return DeliveryRiskLevel.L1
        return DeliveryRiskLevel.L0

    def estimate_confidence(self, raw_input: str) -> float:
        if len(raw_input.strip()) < 20:
            return 0.45
        if "?" in raw_input or "\uff1f" in raw_input:
            return 0.65
        return 0.82

    def decide_spec_status(
        self,
        risk_level: str,
        confidence_score: float,
        auto_approve_low_risk: bool,
    ) -> str:
        if risk_level in {DeliveryRiskLevel.L2, DeliveryRiskLevel.L3}:
            return SpecStatus.MANUAL_REVIEW
        if confidence_score < 0.7:
            return SpecStatus.MANUAL_REVIEW
        return SpecStatus.APPROVED if auto_approve_low_risk else SpecStatus.MANUAL_REVIEW

    def evaluate_spec_ready(
        self,
        *,
        spec_card_id: int,
        user_story: str,
        scope: str | None,
        acceptance_criteria: list[str],
        constraints: list[str],
        risks: list[str],
    ) -> GateDecision:
        missing_fields: list[str] = []
        if not user_story.strip():
            missing_fields.append("user_story")
        if not scope or not scope.strip():
            missing_fields.append("scope")
        if not acceptance_criteria:
            missing_fields.append("acceptance_criteria")
        if not constraints:
            missing_fields.append("constraints")
        if not risks:
            missing_fields.append("risks")

        if missing_fields:
            return GateDecision(
                gate_type=GateType.SPEC_READY,
                status=GateStatus.FAILED,
                reason="Spec is missing required fields.",
                evidence={"spec_card_id": spec_card_id, "missing_fields": missing_fields},
            )

        return GateDecision(
            gate_type=GateType.SPEC_READY,
            status=GateStatus.PASSED,
            reason="Spec contains user story, scope, acceptance criteria, constraints, and risks.",
            evidence={"spec_card_id": spec_card_id},
        )

    def evaluate_risk_classified(
        self,
        *,
        risk_level: str,
        confidence_score: float,
        auto_approve_low_risk: bool,
    ) -> GateDecision:
        spec_status = self.decide_spec_status(
            risk_level=risk_level,
            confidence_score=confidence_score,
            auto_approve_low_risk=auto_approve_low_risk,
        )
        return GateDecision(
            gate_type=GateType.RISK_CLASSIFIED,
            status=GateStatus.PASSED if spec_status == SpecStatus.APPROVED else GateStatus.MANUAL_REQUIRED,
            reason=f"Risk classified as {risk_level}.",
            evidence={
                "risk_level": risk_level,
                "confidence_score": confidence_score,
                "auto_approve_low_risk": auto_approve_low_risk,
            },
        )

    def evaluate_repo_context(
        self,
        *,
        repo_context_id: int,
        confidence_score: float,
        source_refs: list[str],
    ) -> GateDecision:
        if confidence_score < 0.6:
            return GateDecision(
                gate_type=GateType.REPO_CONTEXT_READY,
                status=GateStatus.MANUAL_REQUIRED,
                reason="Repository context confidence is below the automation threshold.",
                evidence={
                    "repo_context_id": repo_context_id,
                    "confidence_score": confidence_score,
                    "source_refs": source_refs,
                },
            )

        return GateDecision(
            gate_type=GateType.REPO_CONTEXT_READY,
            status=GateStatus.PASSED,
            reason="Repository context is sufficient for impact analysis.",
            evidence={
                "repo_context_id": repo_context_id,
                "confidence_score": confidence_score,
                "source_refs": source_refs,
            },
        )

    def decide_coding_task_status(self, *, spec_status: str, risk_level: str | None) -> str:
        if spec_status == SpecStatus.APPROVED and risk_level in {DeliveryRiskLevel.L0, DeliveryRiskLevel.L1}:
            return CodingTaskStatus.READY
        return CodingTaskStatus.DRAFT

    def evaluate_execution_allowed(
        self,
        *,
        coding_task_id: int,
        coding_task_status: str,
        risk_level: str | None,
    ) -> GateDecision:
        if coding_task_status != CodingTaskStatus.READY:
            return GateDecision(
                gate_type=GateType.EXECUTION_ALLOWED,
                status=GateStatus.MANUAL_REQUIRED,
                reason="Coding task is not ready for automatic execution.",
                evidence={"coding_task_id": coding_task_id, "coding_task_status": coding_task_status},
            )

        if risk_level in {DeliveryRiskLevel.L2, DeliveryRiskLevel.L3}:
            return GateDecision(
                gate_type=GateType.EXECUTION_ALLOWED,
                status=GateStatus.MANUAL_REQUIRED,
                reason="High-risk demand requires human approval before execution.",
                evidence={"coding_task_id": coding_task_id, "risk_level": risk_level},
            )

        return GateDecision(
            gate_type=GateType.EXECUTION_ALLOWED,
            status=GateStatus.PASSED,
            reason="Coding task can be queued for executor dispatch.",
            evidence={"coding_task_id": coding_task_id, "risk_level": risk_level},
        )


gate_engine = DeliveryGateEngine()
