"""Merge request client contracts."""

from dataclasses import dataclass, field
from typing import Protocol

from app.modules.delivery.models import CodingTask, ExecutionRun


@dataclass(frozen=True)
class MergeRequestDraft:
    """Normalized merge request data returned by a provider client."""

    provider: str
    status: str
    review_status: str
    external_id: str | None = None
    url: str | None = None
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
        source_branch: str,
        target_branch: str,
        url: str | None = None,
    ) -> MergeRequestDraft:
        """Create or register a merge request and return normalized metadata."""
