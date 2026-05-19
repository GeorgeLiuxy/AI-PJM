"""Delivery v2 request and response schemas."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.modules.delivery.enums import (
    CodingTaskStatus,
    DeliveryRiskLevel,
    DemandStatus,
    ExecutionLogLevel,
    ExecutionRunStatus,
    GateStatus,
    GateType,
    ImpactAnalysisStatus,
    RepoContextStatus,
    SpecStatus,
)


class DemandCreateRequest(BaseModel):
    """Create a demand item from raw business input."""

    raw_input: str = Field(..., min_length=1, max_length=20000)
    source_type: str = Field(default="other", max_length=50)
    title: Optional[str] = Field(default=None, max_length=500)
    requester_ref: Optional[str] = Field(default=None, max_length=200)
    context_payload: Optional[dict[str, Any]] = None


class DemandResponse(BaseModel):
    """Demand item response."""

    id: int
    raw_input: str
    source_type: str
    title: Optional[str] = None
    requester_ref: Optional[str] = None
    status: DemandStatus
    risk_level: Optional[DeliveryRiskLevel] = None
    confidence_score: Optional[float] = None
    context_payload: Optional[dict[str, Any]] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SpecGenerateRequest(BaseModel):
    """Generate a spec card for a demand."""

    auto_approve_low_risk: bool = True


class SpecCardResponse(BaseModel):
    """Spec card response."""

    id: int
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


class ExecutionLogResponse(BaseModel):
    """Execution run log response."""

    id: int
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


class DemandDetailResponse(DemandResponse):
    """Demand detail with generated artifacts."""

    spec_cards: list[SpecCardResponse] = Field(default_factory=list)
    gate_checks: list[GateCheckResponse] = Field(default_factory=list)
    repo_contexts: list[RepoContextResponse] = Field(default_factory=list)
    impact_analyses: list[ImpactAnalysisResponse] = Field(default_factory=list)
    coding_tasks: list[CodingTaskResponse] = Field(default_factory=list)
