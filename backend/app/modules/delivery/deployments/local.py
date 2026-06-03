"""Local deployment client."""

from app.modules.delivery.deployments.base import DeployDraft
from app.modules.delivery.enums import DeploymentStatus
from app.modules.delivery.models import CodingTask, MergeRequestRecord


class LocalDeployClient:
    """Create local-only deployment records."""

    provider = "local"

    async def create_deployment(
        self,
        *,
        task: CodingTask,
        merge_request: MergeRequestRecord,
        environment: str,
        url: str | None = None,
    ) -> DeployDraft:
        return DeployDraft(
            provider=self.provider,
            status=DeploymentStatus.DEPLOYED,
            url=url,
            evidence={
                "mode": "local_record",
                "merge_request_id": merge_request.id,
                "coding_task_id": task.id,
                "environment": environment,
                "merge_request_url": merge_request.url,
            },
        )
