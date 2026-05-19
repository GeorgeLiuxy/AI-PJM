"""Provider contracts for AI workflow orchestration."""

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.modules.delivery.models import DemandItem, RepoContext, SpecCard


@dataclass(frozen=True)
class SpecDraft:
    """Structured spec content returned by an AI workflow provider."""

    title: str
    user_story: str
    scope: str
    acceptance_criteria: list[str]
    constraints: list[str]
    risks: list[str]
    open_questions: list[str] = field(default_factory=list)
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RepoContextDraft:
    """Structured repository context returned by a workflow provider."""

    summary: str
    source_refs: list[str]
    discovered_files: list[str]
    dependency_refs: list[str]
    confidence_score: float
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ImpactAnalysisDraft:
    """Structured impact analysis returned by a workflow provider."""

    summary: str
    impacted_areas: list[str]
    affected_files: list[str]
    recommendations: list[str]
    risk_level: str
    confidence_score: float
    provider_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CodingTaskDraft:
    """Codex-ready task package returned by a workflow provider."""

    title: str
    task_prompt: str
    forbidden_actions: list[str]
    expected_evidence: list[str]
    provider_metadata: dict[str, Any] = field(default_factory=dict)


class WorkflowProvider(Protocol):
    """External AI/workflow provider contract.

    Implementations must return structured data only. They must not mutate
    workflow state, bypass gate checks, or execute code.
    """

    name: str

    async def generate_spec(self, demand: DemandItem) -> SpecDraft:
        """Generate a spec draft from a demand."""

    async def collect_repo_context(self, demand: DemandItem) -> RepoContextDraft:
        """Collect repository and documentation context for a demand."""

    async def analyze_impact(
        self,
        demand: DemandItem,
        spec: SpecCard | None,
        repo_context: RepoContext | None,
    ) -> ImpactAnalysisDraft:
        """Analyze code and delivery impact."""

    async def create_coding_task(
        self,
        demand: DemandItem,
        spec: SpecCard,
        allowed_paths: list[str],
        required_checks: list[str],
    ) -> CodingTaskDraft:
        """Create a Codex-ready task package."""
