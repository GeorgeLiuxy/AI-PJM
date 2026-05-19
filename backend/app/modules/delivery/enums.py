"""Delivery v2 enum definitions."""

from enum import Enum


class DemandStatus(str, Enum):
    """Demand item lifecycle status."""

    INTAKE = "intake"
    CONTEXT_READY = "context_ready"
    SPEC_GENERATED = "spec_generated"
    SPEC_MANUAL_REQUIRED = "spec_manual_required"
    SPEC_APPROVED = "spec_approved"
    PLANNED = "planned"
    BLOCKED = "blocked"


class DeliveryRiskLevel(str, Enum):
    """Automation risk level."""

    L0 = "L0"
    L1 = "L1"
    L2 = "L2"
    L3 = "L3"


class GateType(str, Enum):
    """Hard gate type."""

    SPEC_READY = "spec_ready"
    RISK_CLASSIFIED = "risk_classified"
    REPO_CONTEXT_READY = "repo_context_ready"
    IMPACT_ANALYZED = "impact_analyzed"
    CODING_TASK_READY = "coding_task_ready"
    EXECUTION_ALLOWED = "execution_allowed"
    SELF_TEST_PASSED = "self_test_passed"
    REVIEW_PASSED = "review_passed"
    TEST_DEPLOYED = "test_deployed"
    VERIFICATION_PASSED = "verification_passed"


class GateStatus(str, Enum):
    """Gate evaluation result."""

    PASSED = "passed"
    FAILED = "failed"
    MANUAL_REQUIRED = "manual_required"


class SpecStatus(str, Enum):
    """Spec card status."""

    DRAFT = "draft"
    MANUAL_REVIEW = "manual_review"
    APPROVED = "approved"
    SUPERSEDED = "superseded"


class CodingTaskStatus(str, Enum):
    """Coding task package status."""

    DRAFT = "draft"
    READY = "ready"
    RUNNING = "running"
    BLOCKED = "blocked"
    COMPLETED = "completed"


class RepoContextStatus(str, Enum):
    """Repository context status."""

    READY = "ready"
    INSUFFICIENT = "insufficient"


class ImpactAnalysisStatus(str, Enum):
    """Impact analysis status."""

    READY = "ready"
    MANUAL_REVIEW = "manual_review"


class ExecutionRunStatus(str, Enum):
    """Executor run status."""

    QUEUED = "queued"
    RUNNING = "running"
    BLOCKED = "blocked"
    FAILED = "failed"
    SUCCEEDED = "succeeded"


class ExecutionLogLevel(str, Enum):
    """Executor run log level."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
