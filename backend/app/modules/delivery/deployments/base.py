"""Deployment client contracts."""

from dataclasses import dataclass, field
from typing import Protocol

from app.modules.delivery.models import CodingTask, MergeRequestRecord


@dataclass(frozen=True)
class DeployDraft:
    """Normalized test deployment data returned by a provider client."""

    provider: str
    status: str
    url: str | None = None
    evidence: dict = field(default_factory=dict)


class DeployClient(Protocol):
    """Provider boundary for creating a test deployment."""

    provider: str

    async def create_deployment(
        self,
        *,
        task: CodingTask,
        merge_request: MergeRequestRecord,
        environment: str,
        url: str | None = None,
    ) -> DeployDraft:
        """Create or register a deployment and return normalized metadata."""
