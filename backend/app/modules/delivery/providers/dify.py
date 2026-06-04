"""Dify workflow provider boundary.

This provider only accepts structured workflow outputs. It does not mutate
delivery state or execute code; gates remain owned by the platform service.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AIServiceException
from app.modules.delivery.models import DemandItem, RepoContext, SpecCard
from app.modules.delivery.providers.base import ImpactAnalysisDraft, SpecDraft
from app.modules.delivery.providers.local import LocalWorkflowProvider


class DifyWorkflowProvider(LocalWorkflowProvider):
    """Workflow provider that can delegate Spec and impact drafts to Dify."""

    name = "dify"
    spec_schema_name = "ai_pjm_spec_draft"
    impact_schema_name = "ai_pjm_impact_analysis"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        credential_source: str = "settings",
        credential_project_id: int | None = None,
        api_key_secret_name: str | None = None,
    ) -> None:
        super().__init__()
        self._api_key_override = api_key
        self._credential_source = credential_source
        self._credential_project_id = credential_project_id
        self._api_key_secret_name = api_key_secret_name

    async def generate_spec(self, demand: DemandItem) -> SpecDraft:
        workflow_id = self._spec_workflow_id()
        self._require_workflow(workflow_id, "Dify spec workflow")
        outputs = await self._run_workflow(
            workflow_id=workflow_id,
            inputs={
                "demand_id": demand.id,
                "raw_input": demand.raw_input,
                "title": demand.title,
                "source_type": demand.source_type,
                "context_payload": demand.context_payload or {},
            },
        )
        return SpecDraft(
            title=self._required_str(outputs, "title"),
            user_story=self._required_str(outputs, "user_story"),
            scope=self._required_str(outputs, "scope"),
            acceptance_criteria=self._string_list(outputs, "acceptance_criteria"),
            constraints=self._string_list(outputs, "constraints"),
            risks=self._string_list(outputs, "risks"),
            open_questions=self._string_list(outputs, "open_questions", required=False),
            provider_metadata={
                "provider": self.name,
                "workflow_id": workflow_id,
                "source": "dify_workflow",
                **self._contract_metadata(self.spec_schema_name),
                **self._credential_metadata(),
            },
        )

    async def analyze_impact(
        self,
        demand: DemandItem,
        spec: SpecCard | None,
        repo_context: RepoContext | None,
    ) -> ImpactAnalysisDraft:
        workflow_id = self._impact_workflow_id()
        self._require_workflow(workflow_id, "Dify impact workflow")
        outputs = await self._run_workflow(
            workflow_id=workflow_id,
            inputs={
                "demand_id": demand.id,
                "raw_input": demand.raw_input,
                "risk_level": demand.risk_level,
                "spec": self._spec_payload(spec),
                "repo_context": self._repo_context_payload(repo_context),
            },
        )
        return ImpactAnalysisDraft(
            summary=self._required_str(outputs, "summary"),
            impacted_areas=self._string_list(outputs, "impacted_areas"),
            affected_files=self._string_list(outputs, "affected_files", required=False),
            recommendations=self._string_list(outputs, "recommendations", required=False),
            risk_level=self._risk_level(outputs.get("risk_level")),
            confidence_score=self._confidence(outputs.get("confidence_score")),
            provider_metadata={
                "provider": self.name,
                "workflow_id": workflow_id,
                "source": "dify_workflow",
                **self._contract_metadata(self.impact_schema_name),
                "spec_card_id": spec.id if spec else None,
                "repo_context_id": repo_context.id if repo_context else None,
                **self._credential_metadata(),
            },
        )

    async def _run_workflow(self, *, workflow_id: str, inputs: dict[str, Any]) -> dict[str, Any]:
        self._require_base_config()
        url = f"{self._api_base_url().rstrip('/')}/v1/workflows/run"
        payload = {
            "inputs": {
                **inputs,
                "workflow_id": workflow_id,
            },
            "response_mode": "blocking",
            "user": "ai-pjm",
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self._api_key()}"},
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise AIServiceException(f"Dify workflow request failed: {exc}") from exc

        body = response.json()
        outputs = body.get("data", {}).get("outputs")
        if not isinstance(outputs, dict):
            raise AIServiceException("Dify workflow response does not contain structured outputs")
        return outputs

    def _require_base_config(self) -> None:
        missing = []
        if not self._api_base_url():
            missing.append("DIFY_API_BASE_URL")
        if not self._api_key():
            missing.append("DIFY_API_KEY")
        if missing:
            raise AIServiceException(f"Dify provider is missing configuration: {', '.join(missing)}")

    def _require_workflow(self, workflow_id: str, label: str) -> None:
        self._require_base_config()
        if not workflow_id:
            raise AIServiceException(f"{label} is not configured")

    def _api_base_url(self) -> str:
        return settings.dify_api_base_url.strip()

    def _api_key(self) -> str:
        return (self._api_key_override or settings.dify_api_key).strip()

    def _spec_workflow_id(self) -> str:
        return settings.dify_spec_workflow_id.strip()

    def _impact_workflow_id(self) -> str:
        return settings.dify_impact_workflow_id.strip()

    def _credential_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {"credential_source": self._credential_source}
        if self._credential_project_id is not None:
            metadata["credential_project_id"] = self._credential_project_id
        if self._api_key_secret_name:
            metadata["api_key_secret_name"] = self._api_key_secret_name
        return metadata

    def _contract_metadata(self, schema_name: str) -> dict[str, Any]:
        return {
            "schema_name": schema_name,
            "schema_version": settings.ai_workflow_provider_schema_version.strip(),
            "prompt_version": settings.ai_workflow_provider_prompt_version.strip(),
        }

    def _required_str(self, outputs: dict[str, Any], key: str) -> str:
        value = outputs.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AIServiceException(f"Dify workflow output '{key}' must be a non-empty string")
        return value.strip()

    def _string_list(self, outputs: dict[str, Any], key: str, required: bool = True) -> list[str]:
        value = outputs.get(key)
        if value is None and not required:
            return []
        if isinstance(value, str):
            items = [item.strip() for item in value.splitlines() if item.strip()]
        elif isinstance(value, list):
            items = [str(item).strip() for item in value if str(item).strip()]
        else:
            items = []
        if required and not items:
            raise AIServiceException(f"Dify workflow output '{key}' must be a non-empty list")
        return items

    def _confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError) as exc:
            raise AIServiceException("Dify workflow output 'confidence_score' must be numeric") from exc
        return min(max(confidence, 0.0), 1.0)

    def _risk_level(self, value: Any) -> str:
        if not isinstance(value, str) or value.strip() not in {"L0", "L1", "L2", "L3"}:
            raise AIServiceException("Dify workflow output 'risk_level' must be one of L0, L1, L2, L3")
        return value.strip()

    def _spec_payload(self, spec: SpecCard | None) -> dict[str, Any] | None:
        if not spec:
            return None
        return {
            "id": spec.id,
            "title": spec.title,
            "user_story": spec.user_story,
            "scope": spec.scope,
            "acceptance_criteria": spec.acceptance_criteria_json,
            "constraints": spec.constraints_json,
            "risks": spec.risks_json,
        }

    def _repo_context_payload(self, repo_context: RepoContext | None) -> dict[str, Any] | None:
        if not repo_context:
            return None
        return {
            "id": repo_context.id,
            "summary": repo_context.summary,
            "source_refs": repo_context.source_refs_json,
            "discovered_files": repo_context.discovered_files_json,
            "dependency_refs": repo_context.dependency_refs_json,
            "confidence_score": repo_context.confidence_score,
        }
