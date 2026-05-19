"""Deterministic local workflow provider for delivery v2."""

from app.modules.delivery.enums import DeliveryRiskLevel
from app.modules.delivery.models import DemandItem, RepoContext, SpecCard
from app.modules.delivery.providers.base import (
    CodingTaskDraft,
    ImpactAnalysisDraft,
    RepoContextDraft,
    SpecDraft,
)


class MockWorkflowProvider:
    """Local provider used for development and tests.

    This keeps the orchestration path usable before Dify/OpenAI/Codex adapters
    are connected.
    """

    name = "mock"

    async def generate_spec(self, demand: DemandItem) -> SpecDraft:
        return SpecDraft(
            title=demand.title or self._derive_title(demand.raw_input),
            user_story=(
                "As a product or delivery owner, I want this request to be converted "
                "into a scoped engineering change so that an AI coding executor can "
                f"implement it with clear acceptance criteria. Original input: {demand.raw_input}"
            ),
            scope="Implement the smallest safe change that satisfies the accepted user story.",
            acceptance_criteria=[
                "The requested behavior is implemented and demonstrable.",
                "Existing related behavior is not regressed.",
                "Required checks pass and evidence is recorded.",
            ],
            constraints=[
                "Do not bypass hard gates.",
                "Do not perform production, secret, or irreversible data operations automatically.",
                "Keep changes scoped to the confirmed spec.",
            ],
            risks=["No provider-specific high-risk evidence was found in the initial draft."],
            open_questions=[],
            provider_metadata={"provider": self.name},
        )

    async def collect_repo_context(self, demand: DemandItem) -> RepoContextDraft:
        payload = demand.context_payload or {}
        explicit_files = self._as_string_list(payload.get("files"))
        explicit_sources = self._as_string_list(payload.get("sources"))
        explicit_dependencies = self._as_string_list(payload.get("dependencies"))
        path_hints = self._extract_path_hints(demand.raw_input)

        discovered_files = explicit_files or path_hints
        source_refs = explicit_sources or ["demand.raw_input"]
        dependency_refs = explicit_dependencies
        confidence = 0.78 if discovered_files or explicit_sources else 0.72

        return RepoContextDraft(
            summary=(
                "Repository context was collected from demand text and provided context payload. "
                "No external code analysis provider has been invoked in mock mode."
            ),
            source_refs=source_refs,
            discovered_files=discovered_files,
            dependency_refs=dependency_refs,
            confidence_score=confidence,
            provider_metadata={"provider": self.name, "source": "deterministic_mock"},
        )

    async def analyze_impact(
        self,
        demand: DemandItem,
        spec: SpecCard | None,
        repo_context: RepoContext | None,
    ) -> ImpactAnalysisDraft:
        affected_files = repo_context.discovered_files_json if repo_context else []
        impacted_areas = ["application"]
        if affected_files:
            impacted_areas = sorted({path.split("/")[0].split("\\")[0] for path in affected_files})

        risk_level = demand.risk_level or DeliveryRiskLevel.L1
        confidence = min(demand.confidence_score or 0.72, repo_context.confidence_score if repo_context else 0.72)

        return ImpactAnalysisDraft(
            summary=(
                "Impact analysis is based on the generated spec and repository context. "
                "Mock mode marks this as a planning aid, not a full static analysis result."
            ),
            impacted_areas=impacted_areas,
            affected_files=affected_files,
            recommendations=[
                "Keep implementation within the allowed paths declared on the coding task.",
                "Run the required checks before creating a merge request.",
                "Escalate to human review if touched files exceed the analyzed scope.",
            ],
            risk_level=risk_level,
            confidence_score=confidence,
            provider_metadata={
                "provider": self.name,
                "spec_card_id": spec.id if spec else None,
                "repo_context_id": repo_context.id if repo_context else None,
            },
        )

    async def create_coding_task(
        self,
        demand: DemandItem,
        spec: SpecCard,
        allowed_paths: list[str],
        required_checks: list[str],
    ) -> CodingTaskDraft:
        checks = required_checks or ["pytest"]
        return CodingTaskDraft(
            title=f"Implement: {spec.title}",
            task_prompt=self._build_task_prompt(
                demand=demand,
                spec=spec,
                allowed_paths=allowed_paths,
                required_checks=checks,
            ),
            forbidden_actions=[
                "Do not run production deployments.",
                "Do not modify secrets or credentials.",
                "Do not perform destructive database operations.",
                "Do not bypass tests or gate checks.",
            ],
            expected_evidence=[
                "Changed files summary",
                "Test command output",
                "Known residual risk, if any",
            ],
            provider_metadata={"provider": self.name},
        )

    def _build_task_prompt(
        self,
        *,
        demand: DemandItem,
        spec: SpecCard,
        allowed_paths: list[str],
        required_checks: list[str],
    ) -> str:
        allowed_scope = "\n".join(f"- {item}" for item in allowed_paths) or "- No path limit declared"
        checks = "\n".join(f"- {item}" for item in required_checks)
        acceptance = "\n".join(f"- {item}" for item in spec.acceptance_criteria_json)
        constraints = "\n".join(f"- {item}" for item in spec.constraints_json)

        return f"""You are implementing an AI PJM delivery task.

Demand ID: {demand.id}
Spec ID: {spec.id}
Title: {spec.title}

User story:
{spec.user_story}

Scope:
{spec.scope}

Allowed paths:
{allowed_scope}

Acceptance criteria:
{acceptance}

Constraints:
{constraints}

Required checks:
{checks}

Before finishing, run the required checks and report changed files, test results, and residual risks.
"""

    def _derive_title(self, raw_input: str) -> str:
        compact = " ".join(raw_input.split())
        return compact[:80] if compact else "Untitled demand"

    def _as_string_list(self, value: object) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str) and item.strip()]

    def _extract_path_hints(self, raw_input: str) -> list[str]:
        hints: list[str] = []
        for token in raw_input.replace(",", " ").split():
            normalized = token.strip("`'\".()[]{}")
            if "/" in normalized or "\\" in normalized:
                hints.append(normalized)
        return hints
