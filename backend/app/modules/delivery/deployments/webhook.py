"""Webhook deployment client."""

from __future__ import annotations

import json

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.modules.delivery.deployments.base import DeployDraft, DeployRemoteStatus
from app.modules.delivery.enums import DeploymentStatus
from app.modules.delivery.models import CodingTask, DeployRecord, MergeRequestRecord
from app.modules.delivery.provider_credentials import ProviderCredential
from app.modules.delivery.redaction import redact_text


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
        status_url = self._str_or_none(body.get("status_url")) or self._str_or_none(body.get("deployment_status_url"))
        return DeployDraft(
            provider=self.provider,
            status=status,
            url=deployment_url,
            evidence={
                "mode": "webhook",
                "webhook_url": self._webhook_url,
                "environment": environment,
                "external_id": self._str_or_none(body.get("id")) or self._str_or_none(body.get("external_id")),
                "status_url": status_url,
                "commit_sha": payload["commit_sha"],
                "credential": self._credential.metadata(secret_name_key="token_secret_name"),
                **self._log_evidence(body),
            },
        )

    async def fetch_deployment_status(
        self,
        *,
        deploy_record: DeployRecord,
    ) -> DeployRemoteStatus:
        status_url = self._status_url(deploy_record)
        if not status_url:
            raise BadRequestException("Webhook deployment status sync requires status_url evidence")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(
                    status_url,
                    headers={"Authorization": f"Bearer {self._credential.value}"},
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BadRequestException(f"Deployment status sync failed: {exc}") from exc

        body = self._response_body(response)
        status = self._status(body)
        deployment_url = (
            self._str_or_none(body.get("url"))
            or self._str_or_none(body.get("deployment_url"))
            or deploy_record.url
        )
        return DeployRemoteStatus(
            provider=self.provider,
            status=status,
            url=deployment_url,
            summary=self._str_or_none(body.get("summary")) or f"Deployment status is {status}.",
            evidence={
                "mode": "webhook_status_sync",
                "status_url": status_url,
                "external_id": self._external_id(deploy_record),
                "status": status,
                "credential": self._credential.metadata(secret_name_key="token_secret_name"),
                **self._log_evidence(body),
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
        raw_status = (self._str_or_none(body.get("status")) or "").lower()
        if raw_status in {"failed", "failure", "error", "canceled", "cancelled"}:
            return DeploymentStatus.FAILED
        if raw_status in {"deployed", "succeeded", "success", "passed", "complete", "completed"}:
            return DeploymentStatus.DEPLOYED
        if raw_status in {"pending", "queued", "running", "in_progress", "deploying"}:
            return DeploymentStatus.PENDING
        return DeploymentStatus.DEPLOYED

    def _commit_sha(self, merge_request: MergeRequestRecord) -> str | None:
        evidence = merge_request.evidence_json or {}
        return self._str_or_none(evidence.get("commit_sha"))

    def _status_url(self, deploy_record: DeployRecord) -> str | None:
        evidence = deploy_record.evidence_json or {}
        if isinstance(evidence, dict):
            value = self._str_or_none(evidence.get("status_url"))
            if value:
                return value
            provider_evidence = evidence.get("provider_evidence")
            if isinstance(provider_evidence, dict):
                return self._str_or_none(provider_evidence.get("status_url"))
        return None

    def _external_id(self, deploy_record: DeployRecord) -> str | None:
        evidence = deploy_record.evidence_json or {}
        if isinstance(evidence, dict):
            value = self._str_or_none(evidence.get("external_id"))
            if value:
                return value
            provider_evidence = evidence.get("provider_evidence")
            if isinstance(provider_evidence, dict):
                return self._str_or_none(provider_evidence.get("external_id"))
        return None

    def _log_evidence(self, body: dict) -> dict:
        evidence: dict[str, str] = {}
        log_url = (
            self._str_or_none(body.get("log_url"))
            or self._str_or_none(body.get("logs_url"))
            or self._str_or_none(body.get("deployment_log_url"))
        )
        if log_url:
            evidence["log_url"] = log_url

        raw_logs = body.get("logs")
        if raw_logs is None:
            raw_logs = body.get("log")
        if raw_logs is None:
            raw_logs = body.get("output")
        if raw_logs is not None:
            if isinstance(raw_logs, (dict, list)):
                text = json.dumps(raw_logs, ensure_ascii=False, default=str)
            else:
                text = str(raw_logs)
            evidence["logs_tail"] = redact_text(text)[-4000:]
        return evidence

    def _str_or_none(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
