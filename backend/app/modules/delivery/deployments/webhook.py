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
        deployment_url = url or self._deployment_url(body)
        status_url = self._status_url_from_body(body)
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
                "external_id": self._external_id_from_body(body),
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
        deployment_url = self._deployment_url(body) or deploy_record.url
        return DeployRemoteStatus(
            provider=self.provider,
            status=status,
            url=deployment_url,
            summary=self._status_summary(body, status),
            evidence={
                "mode": "webhook_status_sync",
                "status_url": status_url,
                "external_id": self._external_id_from_body(body) or self._external_id(deploy_record),
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
            "degraded",
            "unhealthy",
            "out_of_sync",
            "outofsync",
            "missing",
            "unknown",
            "unstable",
            "aborted",
            "not_built",
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
            "healthy",
            "synced",
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
            "progressing",
        }:
            return DeploymentStatus.PENDING
        return DeploymentStatus.PENDING

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
            "phase",
        ):
            raw_value = body.get(key)
            if isinstance(raw_value, dict):
                signal = self._status_signal(raw_value, self._child_path(path, key))
                if signal:
                    return signal
                continue
            value = self._str_or_none(raw_value)
            if value:
                return {
                    "raw_status": value,
                    "path": self._child_path(path, key),
                    "name": self._status_item_name(body),
                }

        nested_signals: list[dict] = []
        for key in (
            "pipeline",
            "job",
            "deployment",
            "deploy",
            "ci",
            "build",
            "workflow",
            "workflow_run",
            "check_suite",
            "check_run",
            "application",
            "sync",
            "health",
            "status",
            "operationState",
            "operation_state",
        ):
            nested = body.get(key)
            if isinstance(nested, dict):
                signal = self._status_signal(nested, self._child_path(path, key))
                if signal:
                    nested_signals.append(signal)
        nested_signal = self._choose_status_signal(nested_signals)
        if nested_signal:
            return nested_signal

        list_signal = self._list_status_signal(body, path)
        if list_signal:
            return list_signal
        return None

    def _list_status_signal(self, body: dict, path: str) -> dict | None:
        signals: list[dict] = []
        for key in ("jobs", "stages", "steps", "checks", "tasks", "deployments", "pods", "resources", "nodes"):
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

        identifiers = self._status_identifiers(body)
        if identifiers:
            evidence["status_identifiers"] = identifiers

        failure_reason = self._failure_reason(body)
        if failure_reason:
            evidence["failure_reason"] = failure_reason

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
        for key in ("jobs", "stages", "steps", "checks", "tasks", "deployments", "pods", "resources", "nodes"):
            raw_items = body.get(key)
            if not isinstance(raw_items, list):
                continue
            for index, item in enumerate(raw_items):
                if not isinstance(item, dict):
                    continue
                signal = self._status_signal(item, self._child_path(path, f"{key}[{index}]"))
                if not signal:
                    continue
                item_evidence: dict[str, object] = {
                    "name": self._status_item_name(item),
                    "raw_status": signal["raw_status"],
                    "normalized_status": self._enum_or_str(self._normalize_status(signal["raw_status"])),
                    "path": signal["path"],
                    "url": self._item_url(item),
                }
                failure_reason = self._failure_reason(item)
                if failure_reason:
                    item_evidence["failure_reason"] = failure_reason
                identifiers = self._status_identifiers(item)
                if identifiers:
                    item_evidence["identifiers"] = identifiers
                for source_key, evidence_key in (
                    ("duration_seconds", "duration_seconds"),
                    ("duration", "duration_seconds"),
                    ("started_at", "started_at"),
                    ("finished_at", "finished_at"),
                    ("completed_at", "finished_at"),
                ):
                    value = self._str_or_none(item.get(source_key))
                    if value and evidence_key not in item_evidence:
                        item_evidence[evidence_key] = value
                items.append(item_evidence)
        for key in (
            "pipeline",
            "job",
            "deployment",
            "deploy",
            "ci",
            "build",
            "workflow",
            "workflow_run",
            "check_suite",
            "check_run",
            "application",
            "sync",
            "health",
            "status",
            "operationState",
            "operation_state",
        ):
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
        status = body.get("status")
        if body.get("application") and (body.get("sync") or body.get("health")):
            return "argocd"
        if isinstance(status, dict) and (
            status.get("sync") or status.get("health") or status.get("operationState")
        ):
            return "argocd"
        if body.get("build") or body.get("job"):
            return "jenkins"
        return None

    def _status_item_name(self, body: dict) -> str | None:
        for key in ("name", "stage", "job", "job_name", "display_name", "task", "id"):
            value = self._str_or_none(body.get(key))
            if value:
                return value
        metadata = body.get("metadata")
        if isinstance(metadata, dict):
            value = self._str_or_none(metadata.get("name"))
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

    def _deployment_url(self, body: dict) -> str | None:
        for key in ("url", "deployment_url", "web_url", "html_url", "external_url", "environment_url"):
            value = self._str_or_none(body.get(key))
            if value:
                return value
        return self._linked_url(body, "deployment", "web", "html", "environment", "self")

    def _status_url_from_body(self, body: dict) -> str | None:
        for key in ("status_url", "deployment_status_url", "pipeline_status_url", "job_status_url"):
            value = self._str_or_none(body.get(key))
            if value:
                return value
        return self._linked_url(body, "status", "deployment_status", "pipeline_status", "self")

    def _external_id_from_body(self, body: dict) -> str | None:
        for key in (
            "external_id",
            "id",
            "deployment_id",
            "pipeline_id",
            "job_id",
            "run_id",
            "build_id",
            "workflow_id",
            "workflow_run_id",
        ):
            value = self._str_or_none(body.get(key))
            if value:
                return value
        return None

    def _status_summary(self, body: dict, status: str) -> str:
        summary = self._str_or_none(body.get("summary"))
        if summary:
            return redact_text(summary)
        if status == DeploymentStatus.FAILED:
            failure_reason = self._failure_reason(body)
            if failure_reason:
                return f"Deployment failed: {failure_reason}"
        message = self._str_or_none(body.get("message"))
        if message:
            return redact_text(message)
        return f"Deployment status is {status}."

    def _status_identifiers(self, body: dict) -> dict[str, str]:
        identifiers: dict[str, str] = {}
        for key in (
            "id",
            "external_id",
            "deployment_id",
            "pipeline_id",
            "pipeline_iid",
            "job_id",
            "run_id",
            "build_id",
            "workflow_id",
            "workflow_run_id",
            "check_run_id",
            "commit_sha",
            "sha",
            "revision",
            "sync_revision",
            "ref",
            "branch",
            "environment",
        ):
            value = self._str_or_none(body.get(key))
            if value:
                identifiers[key] = value
        return identifiers

    def _failure_reason(self, body: dict) -> str | None:
        raw_status = self._raw_status(body)
        is_failed = self._normalize_status(raw_status) == DeploymentStatus.FAILED if raw_status else False
        reason = self._direct_failure_reason(body, include_general_message=is_failed)
        if reason:
            return reason

        for key in ("jobs", "stages", "steps", "checks", "tasks", "deployments", "pods", "resources", "nodes"):
            raw_items = body.get(key)
            if not isinstance(raw_items, list):
                continue
            for item in raw_items:
                if not isinstance(item, dict):
                    continue
                item_status = self._raw_status(item)
                if self._normalize_status(item_status) != DeploymentStatus.FAILED:
                    continue
                item_reason = self._direct_failure_reason(item, include_general_message=True)
                if item_reason:
                    item_name = self._status_item_name(item)
                    text = f"{item_name}: {item_reason}" if item_name else item_reason
                    return redact_text(text)[:1000]

        for key in (
            "pipeline",
            "job",
            "deployment",
            "deploy",
            "ci",
            "build",
            "workflow",
            "workflow_run",
            "check_suite",
            "check_run",
            "application",
            "sync",
            "health",
            "status",
            "operationState",
            "operation_state",
        ):
            nested = body.get(key)
            if not isinstance(nested, dict):
                continue
            nested_reason = self._failure_reason(nested)
            if nested_reason:
                item_name = self._status_item_name(nested)
                text = f"{item_name}: {nested_reason}" if item_name else nested_reason
                return redact_text(text)[:1000]
        return None

    def _direct_failure_reason(self, body: dict, *, include_general_message: bool) -> str | None:
        for key in ("failure_reason", "failure_message", "error", "error_message", "reason"):
            value = self._str_or_none(body.get(key))
            if value:
                return redact_text(value)[:1000]
        if include_general_message:
            for key in ("message", "status_message", "description", "detail", "details"):
                value = self._str_or_none(body.get(key))
                if value:
                    return redact_text(value)[:1000]
        return None

    def _linked_url(self, body: dict, *names: str) -> str | None:
        links = body.get("links")
        if links is None:
            links = body.get("_links")

        if isinstance(links, dict):
            for name in names:
                value = self._url_from_link_entry(links.get(name))
                if value:
                    return value
            return None

        if isinstance(links, list):
            for name in names:
                for entry in links:
                    if not isinstance(entry, dict):
                        continue
                    rel = self._str_or_none(entry.get("rel")) or self._str_or_none(entry.get("name"))
                    if rel != name:
                        continue
                    value = self._url_from_link_entry(entry)
                    if value:
                        return value
        return None

    def _url_from_link_entry(self, entry: object) -> str | None:
        if isinstance(entry, str):
            return self._str_or_none(entry)
        if not isinstance(entry, dict):
            return None
        for key in ("href", "url", "web_url", "html_url", "external_url"):
            value = self._str_or_none(entry.get(key))
            if value:
                return value
        return None

    def _item_url(self, body: dict) -> str | None:
        for key in ("url", "web_url", "html_url", "external_url"):
            value = self._str_or_none(body.get(key))
            if value:
                return value
        return self._linked_url(body, "web", "html", "self", "job", "step", "task")

    def _log_evidence(self, body: dict) -> dict:
        evidence: dict[str, str] = {}
        log_url = (
            self._str_or_none(body.get("log_url"))
            or self._str_or_none(body.get("logs_url"))
            or self._str_or_none(body.get("deployment_log_url"))
            or self._str_or_none(body.get("trace_url"))
            or self._linked_url(body, "log", "logs", "trace", "console")
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
        if isinstance(value, (dict, list, tuple, set)):
            return None
        text = str(value).strip()
        return text or None

    def _enum_or_str(self, value: object) -> str:
        return value.value if hasattr(value, "value") else str(value)
