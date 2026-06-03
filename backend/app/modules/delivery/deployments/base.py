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


@dataclass(frozen=True)
class DeployRemoteStatus:
    """Normalized deployment status returned by a provider client."""

    provider: str
    status: str
    url: str | None = None
    summary: str | None = None
    evidence: dict = field(default_factory=dict)


class DeployClient(Protocol):
    """Provider boundary for creating and reading test deployment state."""

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

    async def fetch_deployment_status(
        self,
        *,
        deploy_record,
    ) -> DeployRemoteStatus:
        """Fetch remote deployment status and return normalized metadata."""
