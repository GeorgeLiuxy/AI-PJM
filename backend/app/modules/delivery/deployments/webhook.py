"""Webhook deployment client."""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.modules.delivery.deployments.base import DeployDraft
from app.modules.delivery.enums import DeploymentStatus
from app.modules.delivery.models import CodingTask, MergeRequestRecord
from app.modules.delivery.provider_credentials import ProviderCredential


class WebhookDeployClient:
    """Trigger a test deployment through a configured webhook endpoint."""

    provider = "webhook"

    def __init__(
        self,
        *,
        credential: ProviderCredential,
        webhook_url: str | None = None,
    ) -> None:
        self._credential = credential
        self._webhook_url = (webhook_url if webhook_url is not None else settings.deploy_webhook_url).strip()

    async def create_deployment(
        self,
        *,
        task: CodingTask,
        merge_request: MergeRequestRecord,
        environment: str,
        url: str | None = None,
    ) -> DeployDraft:
        self._require_config()
        payload = {
            "merge_request_id": merge_request.id,
            "merge_request_url": merge_request.url,
            "coding_task_id": task.id,
            "source_branch": merge_request.source_branch,
            "target_branch": merge_request.target_branch,
            "commit_sha": self._commit_sha(merge_request),
            "environment": environment,
            "requested_url": url,
        }
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.post(
                    self._webhook_url,
                    headers={"Authorization": f"Bearer {self._credential.value}"},
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BadRequestException(f"Deployment webhook failed: {exc}") from exc

        body = self._response_body(response)
        status = self._status(body)
        deployment_url = url or self._str_or_none(body.get("url")) or self._str_or_none(body.get("deployment_url"))
        return DeployDraft(
            provider=self.provider,
            status=status,
            url=deployment_url,
            evidence={
                "mode": "webhook",
                "webhook_url": self._webhook_url,
                "environment": environment,
                "external_id": self._str_or_none(body.get("id")) or self._str_or_none(body.get("external_id")),
                "commit_sha": payload["commit_sha"],
                "credential": self._credential.metadata(secret_name_key="token_secret_name"),
            },
        )

    def _require_config(self) -> None:
        if not self._webhook_url:
            raise BadRequestException("Webhook deployment provider is missing configuration: DEPLOY_WEBHOOK_URL")

    def _response_body(self, response: httpx.Response) -> dict:
        try:
            body = response.json()
        except ValueError:
            return {}
        return body if isinstance(body, dict) else {}

    def _status(self, body: dict) -> str:
        raw_status = self._str_or_none(body.get("status"))
        if raw_status == DeploymentStatus.FAILED:
            return DeploymentStatus.FAILED
        return DeploymentStatus.DEPLOYED

    def _commit_sha(self, merge_request: MergeRequestRecord) -> str | None:
        evidence = merge_request.evidence_json or {}
        return self._str_or_none(evidence.get("commit_sha"))

    def _str_or_none(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
