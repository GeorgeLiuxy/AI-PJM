"""Merge request client contracts."""

from dataclasses import dataclass, field
from typing import Protocol

from app.modules.delivery.models import CodingTask, ExecutionRun, MergeRequestRecord


@dataclass(frozen=True)
class MergeRequestDraft:
    """Normalized merge request data returned by a provider client."""

    provider: str
    status: str
    review_status: str
    external_id: str | None = None
    url: str | None = None
    evidence: dict = field(default_factory=dict)


@dataclass(frozen=True)
class MergeRequestRemoteReview:
    """Normalized remote review and CI state returned by a provider client."""

    provider: str
    status: str
    review_status: str
    summary: str
    comments: list[dict] = field(default_factory=list)
    blocking_issues: list[str] = field(default_factory=list)
    evidence: dict = field(default_factory=dict)


class MergeRequestClient(Protocol):
    """Provider boundary for creating and reading merge request state."""

    provider: str

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
        """Create or register a merge request and return normalized metadata."""

    async def fetch_remote_review(
        self,
        *,
        record: MergeRequestRecord,
        commit_sha: str | None = None,
    ) -> MergeRequestRemoteReview:
        """Fetch remote review, comments, and CI status."""
