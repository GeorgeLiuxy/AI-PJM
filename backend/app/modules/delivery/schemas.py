"""Delivery v2 request and response schemas."""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from app.modules.delivery.enums import (
    CodingTaskStatus,
    DeliveryRiskLevel,
    DemandStatus,
    DeploymentStatus,
    ExecutionLogLevel,
    ExecutionRunStatus,
    GateStatus,
    GateType,
    ImpactAnalysisStatus,
    MergeRequestStatus,
    RepoContextStatus,
    ReviewStatus,
    SpecStatus,
    VerificationStatus,
)


class DemandCreateRequest(BaseModel):
    """Create a demand item from raw business input."""

    project_id: Optional[int] = None
    raw_input: str = Field(..., min_length=1, max_length=20000)
    source_type: str = Field(default="other", max_length=50)
    title: Optional[str] = Field(default=None, max_length=500)
    requester_ref: Optional[str] = Field(default=None, max_length=200)
    context_payload: Optional[dict[str, Any]] = None


class DemandResponse(BaseModel):
    """Demand item response."""

    id: int
    trace_id: Optional[str] = None
    project_id: Optional[int] = None
    created_by_user_id: Optional[int] = None
    raw_input: str
    source_type: str
    title: Optional[str] = None
    requester_ref: Optional[str] = None
    status: DemandStatus
    risk_level: Optional[DeliveryRiskLevel] = None
    confidence_score: Optional[float] = None
    context_payload: Optional[dict[str, Any]] = None
    manual_approval_status: Optional[str] = None
    manual_approval_user_id: Optional[int] = None
    manual_approval_ref: Optional[str] = None
    manual_approval_note: Optional[str] = None
    manual_approval_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SpecGenerateRequest(BaseModel):
    """Generate a spec card for a demand."""

    auto_approve_low_risk: bool = True


class ManualApprovalRequest(BaseModel):
    """Record a human approval or rejection for a demand."""

    approved: bool = True
    approver_ref: Optional[str] = Field(default=None, max_length=200)
    note: Optional[str] = Field(default=None, max_length=2000)


class SpecCardResponse(BaseModel):
    """Spec card response."""

    id: int
    trace_id: Optional[str] = None
    demand_id: int
    status: SpecStatus
    title: str
    user_story: str
    scope: Optional[str] = None
    acceptance_criteria_json: list[str]
    constraints_json: list[str]
    risks_json: list[str]
    open_questions_json: list[str]
    created_by: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class GateCheckResponse(BaseModel):
    """Gate check response."""

    id: int
    trace_id: Optional[str] = None
    demand_id: int
    gate_type: GateType
    status: GateStatus
    reason: Optional[str] = None
    evidence_json: Optional[dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class RepoContextCreateRequest(BaseModel):
    """Collect repository and documentation context for a demand."""

    force_refresh: bool = False


class RepoContextResponse(BaseModel):
    """Repository context response."""

    id: int
    trace_id: Optional[str] = None
    demand_id: int
    status: RepoContextStatus
    provider: str
    summary: str
    source_refs_json: list[str]
    discovered_files_json: list[str]
    dependency_refs_json: list[str]
    confidence_score: float
    provider_metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ImpactAnalysisCreateRequest(BaseModel):
    """Create an impact analysis for a demand."""

    repo_context_id: Optional[int] = None


class ImpactAnalysisResponse(BaseModel):
    """Impact analysis response."""

    id: int
    trace_id: Optional[str] = None
    demand_id: int
    repo_context_id: Optional[int] = None
    status: ImpactAnalysisStatus
    provider: str
    summary: str
    impacted_areas_json: list[str]
    affected_files_json: list[str]
    recommendations_json: list[str]
    risk_level: DeliveryRiskLevel
    confidence_score: float
    provider_metadata_json: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CodingTaskCreateRequest(BaseModel):
    """Create a Codex-ready task package from a spec card."""

    required_checks: list[str] = Field(default_factory=list)
    allowed_paths: list[str] = Field(default_factory=list)


class CodingTaskResponse(BaseModel):
    """Coding task package response."""

    id: int
    trace_id: Optional[str] = None
    demand_id: int
    spec_card_id: int
    status: CodingTaskStatus
    title: str
    task_prompt: str
    allowed_paths_json: list[str]
    forbidden_actions_json: list[str]
    required_checks_json: list[str]
    expected_evidence_json: list[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ExecutionRunCreateRequest(BaseModel):
    """Create an executor run record for a coding task."""

    executor_type: str = Field(default="codex", max_length=50)
    trigger_mode: str = Field(default="manual", max_length=50)


class AutoRepairExecutionRequest(BaseModel):
    """Run a bounded automatic repair loop for a failed coding task."""

    executor_type: str = Field(default="codex", max_length=50)
    max_attempts: int | None = Field(default=None, ge=1, le=3)


class ExecutionRunControlRequest(BaseModel):
    """Operator control request for a queued or running execution run."""

    reason: Optional[str] = Field(default=None, max_length=1000)


class MergeRequestCreateRequest(BaseModel):
    """Create or register a merge request for a completed coding task."""

    execution_run_id: Optional[int] = None
    provider: str = Field(default="local", max_length=50)
    target_branch: Optional[str] = Field(default=None, max_length=500)
    title: Optional[str] = Field(default=None, max_length=500)
    url: Optional[str] = Field(default=None, max_length=1000)


class MergeRequestReviewRequest(BaseModel):
    """Record review result for a merge request."""

    review_status: ReviewStatus = ReviewStatus.PASSED
    review_summary: Optional[str] = Field(default=None, max_length=4000)
    review_comments: list[dict[str, Any]] = Field(default_factory=list)
    blocking_issues: list[str] = Field(default_factory=list)


class DeployRecordCreateRequest(BaseModel):
    """Create or register a test environment deployment."""

    provider: str = Field(default="local", max_length=50)
    environment: str = Field(default="test", max_length=100)
    url: Optional[str] = Field(default=None, max_length=1000)


class VerificationRecordCreateRequest(BaseModel):
    """Record verification result for a test deployment."""

    status: VerificationStatus = VerificationStatus.PASSED
    verifier_ref: Optional[str] = Field(default=None, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=4000)
    evidence_links: list[str] = Field(default_factory=list)


class ExecutionLogResponse(BaseModel):
    """Execution run log response."""

    id: int
    trace_id: Optional[str] = None
    execution_run_id: int
    level: ExecutionLogLevel
    message: str
    event_json: Optional[dict[str, Any]] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExecutionRunResponse(BaseModel):
    """Execution run response."""

    id: int
    trace_id: Optional[str] = None
    coding_task_id: int
    status: ExecutionRunStatus
    executor_type: str
    trigger_mode: str
    worktree_path: Optional[str] = None
    branch_name: Optional[str] = None
    commit_sha: Optional[str] = None
    result_summary: Optional[str] = None
    evidence_json: Optional[dict[str, Any]] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    logs: list[ExecutionLogResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class ExecutionRunQueueItemResponse(ExecutionRunResponse):
    """Execution queue item with task and demand context."""

    coding_task_title: str
    demand_id: int
    demand_title: Optional[str] = None
    risk_level: Optional[DeliveryRiskLevel] = None


class ObservabilityAlertResponse(BaseModel):
    """Actionable operational alert derived from delivery state."""

    id: str
    category: Literal["worker", "queue", "secret", "deployment"]
    severity: Literal["warning", "critical"]
    title: str
    summary: str
    count: int
    entity_type: str
    entity_ids: list[int] = Field(default_factory=list)


class ObservabilitySummaryResponse(BaseModel):
    """Minimal observability snapshot for the delivery workspace."""

    generated_at: datetime
    status: Literal["healthy", "warning", "critical"]
    metrics: dict[str, int]
    alerts: list[ObservabilityAlertResponse] = Field(default_factory=list)


class SymphonyBridgeClaimRequest(BaseModel):
    """Claim a queued Symphony execution run."""

    worker_id: str = Field(..., min_length=1, max_length=200)
    lease_seconds: int | None = Field(default=None, ge=30, le=3600)


class SymphonyBridgeHeartbeatRequest(BaseModel):
    """Refresh a worker lease for a Symphony execution run."""

    worker_id: str = Field(..., min_length=1, max_length=200)
    lease_seconds: int | None = Field(default=None, ge=30, le=3600)


class SymphonyBridgeEventRequest(BaseModel):
    """Append a structured event from a Symphony worker."""

    worker_id: str = Field(..., min_length=1, max_length=200)
    level: ExecutionLogLevel = ExecutionLogLevel.INFO
    message: str = Field(..., min_length=1, max_length=4000)
    event_json: dict[str, Any] = Field(default_factory=dict)


class SymphonyBridgeCompleteRequest(BaseModel):
    """Complete a Symphony execution run."""

    worker_id: str = Field(..., min_length=1, max_length=200)
    status: Literal["succeeded", "failed"]
    summary: str = Field(..., min_length=1, max_length=4000)
    evidence: dict[str, Any] = Field(default_factory=dict)
    worktree_path: Optional[str] = Field(default=None, max_length=1000)
    branch_name: Optional[str] = Field(default=None, max_length=500)
    commit_sha: Optional[str] = Field(default=None, max_length=100)


class SymphonyBridgeTaskPackageResponse(BaseModel):
    """Task package consumed by an external Symphony worker."""

    run_id: int
    trace_id: Optional[str] = None
    coding_task_id: int
    demand_id: int
    demand_title: str
    risk_level: DeliveryRiskLevel
    task_title: str
    task_prompt: str
    allowed_paths: list[str]
    forbidden_actions: list[str]
    required_checks: list[str]
    expected_evidence: list[str]
    acceptance_criteria: list[str] = Field(default_factory=list)
    repo_context_summary: Optional[str] = None
    impact_summary: Optional[str] = None
    execution_evidence: dict[str, Any] = Field(default_factory=dict)


class MergeRequestRecordResponse(BaseModel):
    """Merge request or pull request record response."""

    id: int
    trace_id: Optional[str] = None
    coding_task_id: int
    execution_run_id: int
    provider: str
    status: MergeRequestStatus
    review_status: ReviewStatus
    title: str
    source_branch: str
    target_branch: str
    external_id: Optional[str] = None
    url: Optional[str] = None
    review_summary: Optional[str] = None
    review_comments_json: list[dict[str, Any]]
    evidence_json: Optional[dict[str, Any]] = None
    created_by_user_id: Optional[int] = None
    created_by_ref: Optional[str] = None
    reviewed_by_user_id: Optional[int] = None
    reviewed_by_ref: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    deploy_records: list["DeployRecordResponse"] = Field(default_factory=list)

    class Config:
        from_attributes = True


class VerificationRecordResponse(BaseModel):
    """Verification record response."""

    id: int
    trace_id: Optional[str] = None
    deploy_record_id: int
    status: VerificationStatus
    verifier_user_id: Optional[int] = None
    verifier_ref: Optional[str] = None
    summary: Optional[str] = None
    evidence_links_json: list[str]
    evidence_json: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DeployRecordResponse(BaseModel):
    """Test deployment record response."""

    id: int
    trace_id: Optional[str] = None
    merge_request_id: int
    coding_task_id: int
    provider: str
    status: DeploymentStatus
    environment: str
    url: Optional[str] = None
    evidence_json: Optional[dict[str, Any]] = None
    created_by_user_id: Optional[int] = None
    created_by_ref: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    verification_records: list[VerificationRecordResponse] = Field(default_factory=list)

    class Config:
        from_attributes = True


class CodingTaskDetailResponse(CodingTaskResponse):
    """Coding task response with execution attempts."""

    execution_runs: list[ExecutionRunResponse] = Field(default_factory=list)
    merge_requests: list[MergeRequestRecordResponse] = Field(default_factory=list)


class DemandDetailResponse(DemandResponse):
    """Demand detail with generated artifacts."""

    spec_cards: list[SpecCardResponse] = Field(default_factory=list)
    gate_checks: list[GateCheckResponse] = Field(default_factory=list)
    repo_contexts: list[RepoContextResponse] = Field(default_factory=list)
    impact_analyses: list[ImpactAnalysisResponse] = Field(default_factory=list)
    coding_tasks: list[CodingTaskDetailResponse] = Field(default_factory=list)
