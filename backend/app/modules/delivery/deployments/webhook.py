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
        deployment_url = url or self._str_or_none(body.get("url")) or self._str_or_none(body.get("deployment_url"))
        status_url = self._str_or_none(body.get("status_url")) or self._str_or_none(body.get("deployment_status_url"))
        raw_status = self._raw_status(body)
        status = self._normalize_status(raw_status) if raw_status else (
            DeploymentStatus.PENDING if status_url else DeploymentStatus.DEPLOYED
        )
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
                "raw_status": raw_status,
                "normalized_status": self._enum_or_str(status),
                "commit_sha": payload["commit_sha"],
                "credential": self._credential.metadata(secret_name_key="token_secret_name"),
                **self._status_evidence(body),
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
        raw_status = self._raw_status(body)
        status = self._normalize_status(raw_status) if raw_status else DeploymentStatus.PENDING
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
                "raw_status": raw_status,
                "status": self._enum_or_str(status),
                "normalized_status": self._enum_or_str(status),
                "credential": self._credential.metadata(secret_name_key="token_secret_name"),
                **self._status_evidence(body),
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
        return self._normalize_status(self._raw_status(body))

    def _normalize_status(self, raw_value: object | None) -> str:
        raw_status = (self._str_or_none(raw_value) or "").lower().replace("-", "_").replace(" ", "_")
        if raw_status in {
            "failed",
            "failure",
            "error",
            "errored",
            "canceled",
            "cancelled",
            "rejected",
            "timed_out",
            "timeout",
            "skipped",
            "red",
        }:
            return DeploymentStatus.FAILED
        if raw_status in {
            "deployed",
            "succeeded",
            "success",
            "successful",
            "passed",
            "pass",
            "complete",
            "completed",
            "green",
            "ok",
            "ready",
            "available",
        }:
            return DeploymentStatus.DEPLOYED
        if raw_status in {
            "pending",
            "queued",
            "running",
            "in_progress",
            "deploying",
            "created",
            "waiting",
            "preparing",
            "processing",
            "manual",
            "scheduled",
            "blocked",
        }:
            return DeploymentStatus.PENDING
        return DeploymentStatus.DEPLOYED

    def _raw_status(self, body: dict) -> str | None:
        signal = self._status_signal(body)
        if signal:
            return self._str_or_none(signal.get("raw_status"))
        return None

    def _status_signal(self, body: dict, path: str = "") -> dict | None:
        for key in (
            "status",
            "state",
            "result",
            "conclusion",
            "deployment_status",
            "detailed_status",
            "pipeline_status",
            "job_status",
        ):
            value = self._str_or_none(body.get(key))
            if value:
                return {
                    "raw_status": value,
                    "path": self._child_path(path, key),
                    "name": self._status_item_name(body),
                }

        for key in ("pipeline", "job", "deployment", "deploy", "ci", "build"):
            nested = body.get(key)
            if isinstance(nested, dict):
                signal = self._status_signal(nested, self._child_path(path, key))
                if signal:
                    return signal

        list_signal = self._list_status_signal(body, path)
        if list_signal:
            return list_signal
        return None

    def _list_status_signal(self, body: dict, path: str) -> dict | None:
        signals: list[dict] = []
        for key in ("jobs", "stages", "steps", "checks", "tasks", "deployments", "pods", "resources"):
            items = body.get(key)
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                signal = self._status_signal(item, self._child_path(path, f"{key}[{index}]"))
                if signal:
                    signals.append(signal)
        return self._choose_status_signal(signals)

    def _choose_status_signal(self, signals: list[dict]) -> dict | None:
        if not signals:
            return None
        for status in (DeploymentStatus.FAILED, DeploymentStatus.PENDING, DeploymentStatus.DEPLOYED):
            for signal in signals:
                if self._normalize_status(signal.get("raw_status")) == status:
                    return signal
        return signals[0]

    def _status_evidence(self, body: dict) -> dict:
        evidence: dict[str, object] = {}
        signal = self._status_signal(body)
        if signal:
            evidence["status_path"] = signal["path"]
            if signal.get("name"):
                evidence["status_item"] = signal["name"]

        platform = self._status_platform(body)
        if platform:
            evidence["status_platform"] = platform

        items = self._status_items(body)
        if items:
            evidence["status_items"] = items[:20]
            failed_items = [
                item for item in items if item["normalized_status"] == self._enum_or_str(DeploymentStatus.FAILED)
            ]
            pending_items = [
                item for item in items if item["normalized_status"] == self._enum_or_str(DeploymentStatus.PENDING)
            ]
            if failed_items:
                evidence["failed_status_items"] = failed_items[:10]
            if pending_items:
                evidence["pending_status_items"] = pending_items[:10]
        return evidence

    def _status_items(self, body: dict, path: str = "") -> list[dict]:
        items: list[dict] = []
        for key in ("jobs", "stages", "steps", "checks", "tasks", "deployments", "pods", "resources"):
            raw_items = body.get(key)
            if not isinstance(raw_items, list):
                continue
            for index, item in enumerate(raw_items):
                if not isinstance(item, dict):
                    continue
                signal = self._status_signal(item, self._child_path(path, f"{key}[{index}]"))
                if not signal:
                    continue
                items.append(
                    {
                        "name": self._status_item_name(item),
                        "raw_status": signal["raw_status"],
                        "normalized_status": self._enum_or_str(self._normalize_status(signal["raw_status"])),
                        "path": signal["path"],
                        "url": (
                            self._str_or_none(item.get("url"))
                            or self._str_or_none(item.get("web_url"))
                            or self._str_or_none(item.get("html_url"))
                        ),
                    }
                )
        for key in ("pipeline", "job", "deployment", "deploy", "ci", "build", "workflow", "workflow_run"):
            nested = body.get(key)
            if isinstance(nested, dict):
                items.extend(self._status_items(nested, self._child_path(path, key)))
        return items

    def _status_platform(self, body: dict) -> str | None:
        for key in ("platform", "provider", "ci_provider", "system"):
            value = self._str_or_none(body.get(key))
            if value:
                return value.lower()
        if body.get("object_kind") or body.get("project") or body.get("pipeline"):
            return "gitlab"
        if body.get("workflow_run") or body.get("check_suite") or body.get("check_run"):
            return "github"
        if body.get("application") and (body.get("sync") or body.get("health")):
            return "argocd"
        if body.get("build") or body.get("job"):
            return "jenkins"
        return None

    def _status_item_name(self, body: dict) -> str | None:
        for key in ("name", "stage", "job", "job_name", "display_name", "task", "id"):
            value = self._str_or_none(body.get(key))
            if value:
                return value
        return None

    def _child_path(self, path: str, key: str) -> str:
        return f"{path}.{key}" if path else key

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

    def _enum_or_str(self, value: object) -> str:
        return value.value if hasattr(value, "value") else str(value)
