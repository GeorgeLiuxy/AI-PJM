"""GitLab merge request client."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.modules.delivery.enums import MergeRequestStatus, ReviewStatus
from app.modules.delivery.merge_requests.base import MergeRequestDraft, MergeRequestRemoteReview
from app.modules.delivery.models import CodingTask, ExecutionRun, MergeRequestRecord
from app.modules.delivery.provider_credentials import ProviderCredential


class GitLabMergeRequestClient:
    """Create merge requests through the GitLab REST API."""

    provider = "gitlab"

    def __init__(
        self,
        *,
        credential: ProviderCredential,
        api_base_url: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self._credential = credential
        self._api_base_url = (api_base_url if api_base_url is not None else settings.gitlab_api_base_url).strip()
        self._project_id = (project_id if project_id is not None else settings.gitlab_project_id).strip()

    async def create_merge_request(
        self,
        *,
        task: CodingTask,
        run: ExecutionRun,
        title: str,
        description: str,
        source_branch: str,
        target_branch: str,
        url: str | None = None,
    ) -> MergeRequestDraft:
        self._require_config()
        request_url = self._merge_requests_url()
        payload = {
            "source_branch": source_branch,
            "target_branch": target_branch,
            "title": title,
            "description": description,
            "remove_source_branch": False,
        }
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    request_url,
                    headers={"PRIVATE-TOKEN": self._credential.value},
                    json=payload,
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise BadRequestException(f"GitLab merge request creation failed: {exc}") from exc

        body = response.json()
        external_id = self._external_id(body)
        return MergeRequestDraft(
            provider=self.provider,
            status=MergeRequestStatus.CREATED,
            review_status=ReviewStatus.PENDING,
            external_id=external_id,
            url=url or self._str_or_none(body.get("web_url")),
            evidence={
                "mode": "gitlab_api",
                "gitlab_project_id": self._project_id,
                "gitlab_merge_request_id": self._str_or_none(body.get("id")),
                "gitlab_merge_request_iid": self._str_or_none(body.get("iid")),
                "source_branch": source_branch,
                "target_branch": target_branch,
                "commit_sha": run.commit_sha,
                "credential": self._credential.metadata(secret_name_key="token_secret_name"),
            },
        )

    async def fetch_remote_review(
        self,
        *,
        record: MergeRequestRecord,
        commit_sha: str | None = None,
    ) -> MergeRequestRemoteReview:
        self._require_config()
        iid = self._merge_request_iid(record)
        if not iid:
            raise BadRequestException("GitLab merge request record has no external iid")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                mr_response = await client.get(
                    self._merge_request_url(iid),
                    headers=self._headers(),
                )
                mr_response.raise_for_status()
                discussions_response = await client.get(
                    self._merge_request_discussions_url(iid),
                    headers=self._headers(),
                    params={"per_page": 100},
                )
                discussions_response.raise_for_status()
                status_payload = []
                if commit_sha:
                    statuses_response = await client.get(
                        self._commit_statuses_url(commit_sha),
                        headers=self._headers(),
                        params={"per_page": 100},
                    )
                    statuses_response.raise_for_status()
                    status_payload = self._list_body(statuses_response.json())
        except httpx.HTTPError as exc:
            raise BadRequestException(f"GitLab remote review sync failed: {exc}") from exc

        mr_payload = self._dict_body(mr_response.json())
        discussions = self._list_body(discussions_response.json())
        comments = self._discussion_comments(discussions)
        blocking_issues = self._blocking_issues(comments, status_payload, mr_payload)
        status, review_status = self._normalized_review_state(
            mr_payload=mr_payload,
            statuses=status_payload,
            blocking_issues=blocking_issues,
        )
        summary = self._remote_review_summary(
            mr_payload=mr_payload,
            statuses=status_payload,
            blocking_issues=blocking_issues,
        )

        return MergeRequestRemoteReview(
            provider=self.provider,
            status=status,
            review_status=review_status,
            summary=summary,
            comments=comments,
            blocking_issues=blocking_issues,
            evidence={
                "mode": "gitlab_remote_review_sync",
                "gitlab_project_id": self._project_id,
                "gitlab_merge_request_iid": iid,
                "merge_request": {
                    "state": self._str_or_none(mr_payload.get("state")),
                    "merge_status": self._str_or_none(mr_payload.get("merge_status")),
                    "detailed_merge_status": self._str_or_none(mr_payload.get("detailed_merge_status")),
                    "work_in_progress": bool(mr_payload.get("work_in_progress") or mr_payload.get("draft")),
                    "web_url": self._str_or_none(mr_payload.get("web_url")),
                },
                "ci_statuses": self._status_evidence(status_payload),
                "blocking_issues": blocking_issues,
                "credential": self._credential.metadata(secret_name_key="token_secret_name"),
            },
        )

    def _require_config(self) -> None:
        missing = []
        if not self._api_base_url:
            missing.append("GITLAB_API_BASE_URL")
        if not self._project_id:
            missing.append("GITLAB_PROJECT_ID")
        if missing:
            raise BadRequestException(f"GitLab merge request provider is missing configuration: {', '.join(missing)}")

    def _merge_requests_url(self) -> str:
        project_ref = quote(self._project_id, safe="")
        return f"{self._api_base_url.rstrip('/')}/projects/{project_ref}/merge_requests"

    def _merge_request_url(self, iid: str) -> str:
        project_ref = quote(self._project_id, safe="")
        return f"{self._api_base_url.rstrip('/')}/projects/{project_ref}/merge_requests/{quote(iid, safe='')}"

    def _merge_request_discussions_url(self, iid: str) -> str:
        return f"{self._merge_request_url(iid)}/discussions"

    def _commit_statuses_url(self, commit_sha: str) -> str:
        project_ref = quote(self._project_id, safe="")
        commit_ref = quote(commit_sha, safe="")
        return f"{self._api_base_url.rstrip('/')}/projects/{project_ref}/repository/commits/{commit_ref}/statuses"

    def _headers(self) -> dict[str, str]:
        return {"PRIVATE-TOKEN": self._credential.value}

    def _external_id(self, body: dict) -> str | None:
        return self._str_or_none(body.get("iid")) or self._str_or_none(body.get("id"))

    def _merge_request_iid(self, record: MergeRequestRecord) -> str | None:
        evidence = record.evidence_json or {}
        provider_evidence = evidence.get("provider_evidence") if isinstance(evidence, dict) else {}
        if isinstance(provider_evidence, dict):
            iid = self._str_or_none(provider_evidence.get("gitlab_merge_request_iid"))
            if iid:
                return iid
        return self._str_or_none(record.external_id)

    def _dict_body(self, value: object) -> dict:
        return value if isinstance(value, dict) else {}

    def _list_body(self, value: object) -> list:
        return value if isinstance(value, list) else []

    def _discussion_comments(self, discussions: list) -> list[dict]:
        comments: list[dict] = []
        for discussion in discussions:
            if not isinstance(discussion, dict):
                continue
            notes = discussion.get("notes")
            if not isinstance(notes, list):
                continue
            for note in notes:
                if not isinstance(note, dict) or bool(note.get("system")):
                    continue
                body = self._str_or_none(note.get("body"))
                if not body:
                    continue
                comments.append(
                    {
                        "id": self._str_or_none(note.get("id")),
                        "discussion_id": self._str_or_none(discussion.get("id")),
                        "body": body,
                        "author": self._author_name(note.get("author")),
                        "created_at": self._str_or_none(note.get("created_at")),
                        "resolvable": bool(note.get("resolvable")),
                        "resolved": bool(note.get("resolved")),
                        "url": self._str_or_none(note.get("url")),
                    }
                )
        return comments

    def _blocking_issues(self, comments: list[dict], statuses: list, mr_payload: dict) -> list[str]:
        issues: list[str] = []
        for comment in comments:
            if comment.get("resolvable") is True and comment.get("resolved") is not True:
                body = str(comment.get("body") or "").strip()
                if body:
                    issues.append(body[:500])

        failed_statuses = [
            status
            for status in statuses
            if isinstance(status, dict) and str(status.get("status") or "").lower() in {"failed", "canceled"}
        ]
        for status in failed_statuses:
            name = self._str_or_none(status.get("name")) or self._str_or_none(status.get("context")) or "ci"
            state = self._str_or_none(status.get("status")) or "failed"
            issues.append(f"CI status {name} is {state}.")

        if self._str_or_none(mr_payload.get("state")) == "closed":
            issues.append("Merge request is closed.")
        return issues

    def _normalized_review_state(
        self,
        *,
        mr_payload: dict,
        statuses: list,
        blocking_issues: list[str],
    ) -> tuple[str, str]:
        state = self._str_or_none(mr_payload.get("state"))
        if state == "closed":
            return MergeRequestStatus.CLOSED, ReviewStatus.BLOCKING
        if blocking_issues:
            return MergeRequestStatus.REVIEW_BLOCKED, ReviewStatus.BLOCKING

        status_values = [
            str(status.get("status") or "").lower()
            for status in statuses
            if isinstance(status, dict) and status.get("status") is not None
        ]
        if status_values and all(value in {"success", "passed"} for value in status_values):
            return MergeRequestStatus.REVIEW_PASSED, ReviewStatus.PASSED
        if not status_values:
            detailed_status = self._str_or_none(mr_payload.get("detailed_merge_status"))
            if detailed_status in {"mergeable", "checking"}:
                return MergeRequestStatus.REVIEWING, ReviewStatus.PENDING
        return MergeRequestStatus.REVIEWING, ReviewStatus.PENDING

    def _remote_review_summary(self, *, mr_payload: dict, statuses: list, blocking_issues: list[str]) -> str:
        state = self._str_or_none(mr_payload.get("state")) or "unknown"
        detailed_status = self._str_or_none(mr_payload.get("detailed_merge_status")) or "unknown"
        if blocking_issues:
            return f"GitLab review sync found {len(blocking_issues)} blocking issue(s)."
        status_values = [
            str(status.get("status") or "").lower()
            for status in statuses
            if isinstance(status, dict) and status.get("status") is not None
        ]
        if status_values:
            return f"GitLab review sync completed: MR {state}, {len(status_values)} CI status item(s)."
        return f"GitLab review sync completed: MR {state}, detailed status {detailed_status}."

    def _status_evidence(self, statuses: list) -> list[dict]:
        items: list[dict] = []
        for status in statuses:
            if not isinstance(status, dict):
                continue
            items.append(
                {
                    "name": self._str_or_none(status.get("name")) or self._str_or_none(status.get("context")),
                    "status": self._str_or_none(status.get("status")),
                    "target_url": self._str_or_none(status.get("target_url")),
                    "created_at": self._str_or_none(status.get("created_at")),
                    "finished_at": self._str_or_none(status.get("finished_at")),
                }
            )
        return items

    def _author_name(self, value: object) -> str | None:
        if not isinstance(value, dict):
            return None
        return self._str_or_none(value.get("username")) or self._str_or_none(value.get("name"))

    def _str_or_none(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
