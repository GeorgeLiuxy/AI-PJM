"""Local deployment client."""

from app.core.exceptions import BadRequestException
from app.modules.delivery.deployments.base import DeployDraft, DeployRemoteStatus
from app.modules.delivery.enums import DeploymentStatus
from app.modules.delivery.models import CodingTask, DeployRecord, MergeRequestRecord


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

    async def fetch_deployment_status(
        self,
        *,
        deploy_record: DeployRecord,
    ) -> DeployRemoteStatus:
        raise BadRequestException("Local deployment provider does not support remote status sync")
