"""OpenAI workflow provider boundary.

This provider only asks OpenAI for structured planning drafts. It does not
mutate delivery state, execute code, create merge requests, or bypass gates.
"""

from __future__ import annotations

import json
from json import JSONDecodeError
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import AIServiceException
from app.modules.delivery.models import DemandItem, RepoContext, SpecCard
from app.modules.delivery.providers.base import ImpactAnalysisDraft, SpecDraft
from app.modules.delivery.providers.local import LocalWorkflowProvider


class OpenAIWorkflowProvider(LocalWorkflowProvider):
    """Workflow provider that delegates Spec and impact drafts to OpenAI."""

    name = "openai"

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
        outputs, response_id = await self._create_structured_response(
            schema_name="ai_pjm_spec_draft",
            schema=self._spec_schema(),
            system_prompt=(
                "You create concise engineering delivery Spec drafts for AI PJM. "
                "Return only the JSON object required by the schema. Do not claim "
                "that code was changed, tests were run, or delivery gates passed."
            ),
            user_payload={
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
                "model": self._model(),
                "source": "openai_responses_api",
                "response_id": response_id,
                **self._credential_metadata(),
            },
        )

    async def analyze_impact(
        self,
        demand: DemandItem,
        spec: SpecCard | None,
        repo_context: RepoContext | None,
    ) -> ImpactAnalysisDraft:
        outputs, response_id = await self._create_structured_response(
            schema_name="ai_pjm_impact_analysis",
            schema=self._impact_schema(),
            system_prompt=(
                "You create conservative engineering impact analysis drafts for AI PJM. "
                "Use only the supplied demand, Spec, and repository context. Return only "
                "the JSON object required by the schema."
            ),
            user_payload={
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
                "model": self._model(),
                "source": "openai_responses_api",
                "response_id": response_id,
                "spec_card_id": spec.id if spec else None,
                "repo_context_id": repo_context.id if repo_context else None,
                **self._credential_metadata(),
            },
        )

    async def _create_structured_response(
        self,
        *,
        schema_name: str,
        schema: dict[str, Any],
        system_prompt: str,
        user_payload: dict[str, Any],
    ) -> tuple[dict[str, Any], str | None]:
        self._require_base_config()
        url = f"{self._api_base_url().rstrip('/')}/responses"
        request_payload = {
            "model": self._model(),
            "input": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False, default=str),
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "strict": True,
                    "schema": schema,
                }
            },
        }

        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds()) as client:
                response = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {self._api_key()}",
                        "Content-Type": "application/json",
                    },
                    json=request_payload,
                )
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPError as exc:
            raise AIServiceException(f"OpenAI workflow request failed: {exc}") from exc
        except ValueError as exc:
            raise AIServiceException("OpenAI workflow response is not valid JSON") from exc

        if not isinstance(body, dict):
            raise AIServiceException("OpenAI workflow response must be a JSON object")
        text = self._extract_output_text(body)
        try:
            outputs = json.loads(text)
        except JSONDecodeError as exc:
            raise AIServiceException("OpenAI workflow response does not contain structured JSON") from exc
        if not isinstance(outputs, dict):
            raise AIServiceException("OpenAI workflow response must be a JSON object")
        response_id = body.get("id") if isinstance(body.get("id"), str) else None
        return outputs, response_id

    def _extract_output_text(self, body: dict[str, Any]) -> str:
        output_text = body.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        texts: list[str] = []
        refusal: str | None = None
        output_items = body.get("output")
        if isinstance(output_items, list):
            for item in output_items:
                if not isinstance(item, dict):
                    continue
                content_items = item.get("content")
                if not isinstance(content_items, list):
                    continue
                for content in content_items:
                    if not isinstance(content, dict):
                        continue
                    content_type = content.get("type")
                    if content_type == "refusal":
                        raw_refusal = content.get("refusal")
                        if isinstance(raw_refusal, str):
                            refusal = raw_refusal.strip()
                    raw_text = content.get("text")
                    if content_type in {"output_text", "text"} and isinstance(raw_text, str):
                        texts.append(raw_text)

        combined = "".join(texts).strip()
        if combined:
            return combined
        if refusal:
            raise AIServiceException(f"OpenAI workflow refused the request: {refusal}")
        raise AIServiceException("OpenAI workflow response does not contain output text")

    def _require_base_config(self) -> None:
        missing = []
        if not self._api_base_url():
            missing.append("OPENAI_API_BASE_URL")
        if not self._api_key():
            missing.append("OPENAI_API_KEY")
        if not self._model():
            missing.append("OPENAI_MODEL")
        if missing:
            raise AIServiceException(f"OpenAI provider is missing configuration: {', '.join(missing)}")

    def _api_base_url(self) -> str:
        return settings.openai_api_base_url.strip()

    def _api_key(self) -> str:
        return (self._api_key_override or settings.openai_api_key).strip()

    def _model(self) -> str:
        return settings.openai_model.strip()

    def _timeout_seconds(self) -> int:
        return max(settings.openai_request_timeout_seconds, 1)

    def _credential_metadata(self) -> dict[str, Any]:
        metadata: dict[str, Any] = {"credential_source": self._credential_source}
        if self._credential_project_id is not None:
            metadata["credential_project_id"] = self._credential_project_id
        if self._api_key_secret_name:
            metadata["api_key_secret_name"] = self._api_key_secret_name
        return metadata

    def _required_str(self, outputs: dict[str, Any], key: str) -> str:
        value = outputs.get(key)
        if not isinstance(value, str) or not value.strip():
            raise AIServiceException(f"OpenAI workflow output '{key}' must be a non-empty string")
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
            raise AIServiceException(f"OpenAI workflow output '{key}' must be a non-empty list")
        return items

    def _risk_level(self, value: Any) -> str:
        if not isinstance(value, str) or value.strip() not in {"L0", "L1", "L2", "L3"}:
            raise AIServiceException("OpenAI workflow output 'risk_level' must be one of L0, L1, L2, L3")
        return value.strip()

    def _confidence(self, value: Any) -> float:
        try:
            confidence = float(value)
        except (TypeError, ValueError) as exc:
            raise AIServiceException("OpenAI workflow output 'confidence_score' must be numeric") from exc
        return min(max(confidence, 0.0), 1.0)

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

    def _spec_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "title",
                "user_story",
                "scope",
                "acceptance_criteria",
                "constraints",
                "risks",
                "open_questions",
            ],
            "properties": {
                "title": {"type": "string"},
                "user_story": {"type": "string"},
                "scope": {"type": "string"},
                "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                "constraints": {"type": "array", "items": {"type": "string"}},
                "risks": {"type": "array", "items": {"type": "string"}},
                "open_questions": {"type": "array", "items": {"type": "string"}},
            },
        }

    def _impact_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "summary",
                "impacted_areas",
                "affected_files",
                "recommendations",
                "risk_level",
                "confidence_score",
            ],
            "properties": {
                "summary": {"type": "string"},
                "impacted_areas": {"type": "array", "items": {"type": "string"}},
                "affected_files": {"type": "array", "items": {"type": "string"}},
                "recommendations": {"type": "array", "items": {"type": "string"}},
                "risk_level": {"type": "string", "enum": ["L0", "L1", "L2", "L3"]},
                "confidence_score": {"type": "number"},
            },
        }
