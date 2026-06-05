"""GitHub pull request client."""

from __future__ import annotations

from urllib.parse import quote

import httpx

from app.core.config import settings
from app.core.exceptions import BadRequestException
from app.modules.delivery.enums import MergeRequestStatus, ReviewStatus
from app.modules.delivery.merge_requests.base import MergeRequestDraft, MergeRequestRemoteReview
from app.modules.delivery.models import CodingTask, ExecutionRun, MergeRequestRecord
from app.modules.delivery.provider_credentials import ProviderCredential


class GitHubPullRequestClient:
    """Create and inspect GitHub pull requests through the REST API."""

    provider = "github"

    def __init__(
        self,
        *,
        credential: ProviderCredential,
        api_base_url: str | None = None,
        repository: str | None = None,
    ) -> None:
        self._credential = credential
        self._api_base_url = (api_base_url if api_base_url is not None else settings.github_api_base_url).strip()
        self._repository = (repository if repository is not None else settings.github_repository).strip()

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
        payload = {
            "head": source_branch,
            "base": target_branch,
            "title": title,
            "body": description,
            "draft": False,
        }
        labels = self._csv_items(settings.github_default_labels)
        reviewers = self._csv_items(settings.github_reviewers)
        assignees = self._csv_items(settings.github_assignees)

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    self._pulls_url(),
                    headers=self._headers(),
                    json=payload,
                )
                response.raise_for_status()
                body = self._dict_body(response.json())
                number = self._str_or_none(body.get("number"))
                if number:
                    await self._apply_issue_metadata(
                        client,
                        pull_number=number,
                        labels=labels,
                        reviewers=reviewers,
                        assignees=assignees,
                    )
        except httpx.HTTPError as exc:
            raise BadRequestException(f"GitHub pull request creation failed: {exc}") from exc

        return MergeRequestDraft(
            provider=self.provider,
            status=MergeRequestStatus.CREATED,
            review_status=ReviewStatus.PENDING,
            external_id=number,
            url=url or self._str_or_none(body.get("html_url")),
            evidence={
                "mode": "github_api",
                "github_repository": self._repository,
                "github_pull_request_id": self._str_or_none(body.get("id")),
                "github_pull_request_number": number,
                "source_branch": source_branch,
                "target_branch": target_branch,
                "commit_sha": run.commit_sha,
                "labels": labels,
                "reviewers": reviewers,
                "assignees": assignees,
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
        number = self._pull_request_number(record)
        if not number:
            raise BadRequestException("GitHub pull request record has no external number")

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                pull_response = await client.get(
                    self._pull_url(number),
                    headers=self._headers(),
                )
                pull_response.raise_for_status()
                review_comments_response = await client.get(
                    self._pull_review_comments_url(number),
                    headers=self._headers(),
                    params={"per_page": 100},
                )
                review_comments_response.raise_for_status()
                issue_comments_response = await client.get(
                    self._issue_comments_url(number),
                    headers=self._headers(),
                    params={"per_page": 100},
                )
                issue_comments_response.raise_for_status()
                reviews_response = await client.get(
                    self._pull_reviews_url(number),
                    headers=self._headers(),
                    params={"per_page": 100},
                )
                reviews_response.raise_for_status()
                check_runs: list = []
                combined_status: dict = {}
                if commit_sha:
                    checks_response = await client.get(
                        self._check_runs_url(commit_sha),
                        headers=self._headers(),
                        params={"per_page": 100},
                    )
                    checks_response.raise_for_status()
                    checks_body = self._dict_body(checks_response.json())
                    check_runs = self._list_body(checks_body.get("check_runs"))
                    statuses_response = await client.get(
                        self._commit_status_url(commit_sha),
                        headers=self._headers(),
                    )
                    statuses_response.raise_for_status()
                    combined_status = self._dict_body(statuses_response.json())
        except httpx.HTTPError as exc:
            raise BadRequestException(f"GitHub remote review sync failed: {exc}") from exc

        pull_payload = self._dict_body(pull_response.json())
        comments = self._comments(
            self._list_body(review_comments_response.json()),
            self._list_body(issue_comments_response.json()),
        )
        reviews = self._list_body(reviews_response.json())
        blocking_issues = self._blocking_issues(
            pull_payload=pull_payload,
            reviews=reviews,
            check_runs=check_runs,
            combined_status=combined_status,
        )
        status, review_status = self._normalized_review_state(
            pull_payload=pull_payload,
            reviews=reviews,
            check_runs=check_runs,
            combined_status=combined_status,
            blocking_issues=blocking_issues,
        )
        summary = self._remote_review_summary(
            pull_payload=pull_payload,
            check_runs=check_runs,
            combined_status=combined_status,
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
                "mode": "github_remote_review_sync",
                "github_repository": self._repository,
                "github_pull_request_number": number,
                "pull_request": {
                    "state": self._str_or_none(pull_payload.get("state")),
                    "draft": bool(pull_payload.get("draft")),
                    "merged": bool(pull_payload.get("merged")),
                    "mergeable": pull_payload.get("mergeable"),
                    "html_url": self._str_or_none(pull_payload.get("html_url")),
                },
                "reviews": self._reviews_evidence(reviews),
                "check_runs": self._check_runs_evidence(check_runs),
                "combined_status": self._combined_status_evidence(combined_status),
                "blocking_issues": blocking_issues,
                "credential": self._credential.metadata(secret_name_key="token_secret_name"),
            },
        )

    async def _apply_issue_metadata(
        self,
        client: httpx.AsyncClient,
        *,
        pull_number: str,
        labels: list[str],
        reviewers: list[str],
        assignees: list[str],
    ) -> None:
        if labels:
            response = await client.post(
                self._issue_labels_url(pull_number),
                headers=self._headers(),
                json={"labels": labels},
            )
            response.raise_for_status()
        if reviewers:
            response = await client.post(
                self._pull_requested_reviewers_url(pull_number),
                headers=self._headers(),
                json={"reviewers": reviewers},
            )
            response.raise_for_status()
        if assignees:
            response = await client.post(
                self._issue_assignees_url(pull_number),
                headers=self._headers(),
                json={"assignees": assignees},
            )
            response.raise_for_status()

    def _require_config(self) -> None:
        missing = []
        if not self._api_base_url:
            missing.append("GITHUB_API_BASE_URL")
        if not self._repository:
            missing.append("GITHUB_REPOSITORY")
        if missing:
            raise BadRequestException(f"GitHub pull request provider is missing configuration: {', '.join(missing)}")

    def _repo_path(self) -> str:
        parts = [quote(part, safe="") for part in self._repository.split("/", 1)]
        return "/".join(parts)

    def _repo_url(self) -> str:
        return f"{self._api_base_url.rstrip('/')}/repos/{self._repo_path()}"

    def _pulls_url(self) -> str:
        return f"{self._repo_url()}/pulls"

    def _pull_url(self, number: str) -> str:
        return f"{self._pulls_url()}/{quote(number, safe='')}"

    def _pull_review_comments_url(self, number: str) -> str:
        return f"{self._pull_url(number)}/comments"

    def _pull_reviews_url(self, number: str) -> str:
        return f"{self._pull_url(number)}/reviews"

    def _pull_requested_reviewers_url(self, number: str) -> str:
        return f"{self._pull_url(number)}/requested_reviewers"

    def _issue_comments_url(self, number: str) -> str:
        return f"{self._repo_url()}/issues/{quote(number, safe='')}/comments"

    def _issue_labels_url(self, number: str) -> str:
        return f"{self._repo_url()}/issues/{quote(number, safe='')}/labels"

    def _issue_assignees_url(self, number: str) -> str:
        return f"{self._repo_url()}/issues/{quote(number, safe='')}/assignees"

    def _check_runs_url(self, commit_sha: str) -> str:
        return f"{self._repo_url()}/commits/{quote(commit_sha, safe='')}/check-runs"

    def _commit_status_url(self, commit_sha: str) -> str:
        return f"{self._repo_url()}/commits/{quote(commit_sha, safe='')}/status"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._credential.value}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _pull_request_number(self, record: MergeRequestRecord) -> str | None:
        evidence = record.evidence_json or {}
        provider_evidence = evidence.get("provider_evidence") if isinstance(evidence, dict) else {}
        if isinstance(provider_evidence, dict):
            number = self._str_or_none(provider_evidence.get("github_pull_request_number"))
            if number:
                return number
        return self._str_or_none(record.external_id)

    def _comments(self, review_comments: list, issue_comments: list) -> list[dict]:
        comments: list[dict] = []
        for comment in [*review_comments, *issue_comments]:
            if not isinstance(comment, dict):
                continue
            body = self._str_or_none(comment.get("body"))
            if not body:
                continue
            comments.append(
                {
                    "id": self._str_or_none(comment.get("id")),
                    "body": body,
                    "author": self._author_name(comment.get("user")),
                    "created_at": self._str_or_none(comment.get("created_at")),
                    "url": self._str_or_none(comment.get("html_url")) or self._str_or_none(comment.get("url")),
                }
            )
        return comments

    def _blocking_issues(
        self,
        *,
        pull_payload: dict,
        reviews: list,
        check_runs: list,
        combined_status: dict,
    ) -> list[str]:
        issues: list[str] = []
        if self._str_or_none(pull_payload.get("state")) == "closed" and not bool(pull_payload.get("merged")):
            issues.append("Pull request is closed.")

        for review in reviews:
            if not isinstance(review, dict):
                continue
            state = str(review.get("state") or "").upper()
            if state == "CHANGES_REQUESTED":
                body = self._str_or_none(review.get("body")) or "A GitHub reviewer requested changes."
                author = self._author_name(review.get("user"))
                prefix = f"{author}: " if author else ""
                issues.append(f"{prefix}{body}"[:500])

        for check_run in check_runs:
            if not isinstance(check_run, dict):
                continue
            conclusion = str(check_run.get("conclusion") or "").lower()
            if conclusion in {"failure", "timed_out", "cancelled", "action_required"}:
                name = self._str_or_none(check_run.get("name")) or "check"
                issues.append(f"GitHub check {name} concluded {conclusion}.")

        state = str(combined_status.get("state") or "").lower()
        if state in {"failure", "error"}:
            issues.append(f"GitHub combined commit status is {state}.")
        return issues

    def _normalized_review_state(
        self,
        *,
        pull_payload: dict,
        reviews: list,
        check_runs: list,
        combined_status: dict,
        blocking_issues: list[str],
    ) -> tuple[str, str]:
        if self._str_or_none(pull_payload.get("state")) == "closed" and not bool(pull_payload.get("merged")):
            return MergeRequestStatus.CLOSED, ReviewStatus.BLOCKING
        if blocking_issues:
            return MergeRequestStatus.REVIEW_BLOCKED, ReviewStatus.BLOCKING
        if bool(pull_payload.get("draft")):
            return MergeRequestStatus.REVIEWING, ReviewStatus.PENDING

        review_states = [
            str(review.get("state") or "").upper()
            for review in reviews
            if isinstance(review, dict) and review.get("state") is not None
        ]
        check_values = [
            str(check_run.get("conclusion") or check_run.get("status") or "").lower()
            for check_run in check_runs
            if isinstance(check_run, dict)
        ]
        status_state = str(combined_status.get("state") or "").lower()

        checks_passed = bool(check_values) and all(
            value in {"success", "neutral", "skipped", "completed"} for value in check_values
        )
        status_passed = status_state == "success"
        has_no_status_signal = not check_values and not status_state
        status_allows_check_pass = not status_state or status_state == "success"
        if ("APPROVED" in review_states or not review_states) and checks_passed and status_allows_check_pass:
            return MergeRequestStatus.REVIEW_PASSED, ReviewStatus.PASSED
        if ("APPROVED" in review_states or not review_states) and status_passed and not check_values:
            return MergeRequestStatus.REVIEW_PASSED, ReviewStatus.PASSED
        if has_no_status_signal and "APPROVED" in review_states:
            return MergeRequestStatus.REVIEWING, ReviewStatus.PENDING
        return MergeRequestStatus.REVIEWING, ReviewStatus.PENDING

    def _remote_review_summary(
        self,
        *,
        pull_payload: dict,
        check_runs: list,
        combined_status: dict,
        blocking_issues: list[str],
    ) -> str:
        state = self._str_or_none(pull_payload.get("state")) or "unknown"
        if blocking_issues:
            return f"GitHub review sync found {len(blocking_issues)} blocking issue(s)."
        status_state = self._str_or_none(combined_status.get("state")) or "unknown"
        return f"GitHub review sync completed: PR {state}, {len(check_runs)} check run(s), status {status_state}."

    def _reviews_evidence(self, reviews: list) -> list[dict]:
        items: list[dict] = []
        for review in reviews:
            if not isinstance(review, dict):
                continue
            items.append(
                {
                    "id": self._str_or_none(review.get("id")),
                    "state": self._str_or_none(review.get("state")),
                    "author": self._author_name(review.get("user")),
                    "submitted_at": self._str_or_none(review.get("submitted_at")),
                    "url": self._str_or_none(review.get("html_url")),
                }
            )
        return items

    def _check_runs_evidence(self, check_runs: list) -> list[dict]:
        items: list[dict] = []
        for check_run in check_runs:
            if not isinstance(check_run, dict):
                continue
            items.append(
                {
                    "id": self._str_or_none(check_run.get("id")),
                    "name": self._str_or_none(check_run.get("name")),
                    "status": self._str_or_none(check_run.get("status")),
                    "conclusion": self._str_or_none(check_run.get("conclusion")),
                    "html_url": self._str_or_none(check_run.get("html_url")),
                    "completed_at": self._str_or_none(check_run.get("completed_at")),
                }
            )
        return items

    def _combined_status_evidence(self, combined_status: dict) -> dict:
        return {
            "state": self._str_or_none(combined_status.get("state")),
            "total_count": combined_status.get("total_count"),
            "statuses": [
                {
                    "context": self._str_or_none(status.get("context")),
                    "state": self._str_or_none(status.get("state")),
                    "target_url": self._str_or_none(status.get("target_url")),
                }
                for status in self._list_body(combined_status.get("statuses"))
                if isinstance(status, dict)
            ],
        }

    def _dict_body(self, value: object) -> dict:
        return value if isinstance(value, dict) else {}

    def _list_body(self, value: object) -> list:
        return value if isinstance(value, list) else []

    def _author_name(self, value: object) -> str | None:
        if not isinstance(value, dict):
            return None
        return self._str_or_none(value.get("login")) or self._str_or_none(value.get("name"))

    def _str_or_none(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _csv_items(self, value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]
