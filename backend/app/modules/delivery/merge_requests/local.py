"""Local merge request client.

The local client records an auditable MR/PR handoff without calling a remote
code review system. It keeps the main delivery chain usable before GitLab or
GitHub credentials are configured.
"""

from app.modules.delivery.enums import MergeRequestStatus, ReviewStatus
from app.modules.delivery.merge_requests.base import MergeRequestDraft
from app.modules.delivery.models import CodingTask, ExecutionRun


class LocalMergeRequestClient:
    """Create local-only merge request records."""

    provider = "local"

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
        return MergeRequestDraft(
            provider=self.provider,
            status=MergeRequestStatus.CREATED,
            review_status=ReviewStatus.PENDING,
            url=url,
            evidence={
                "mode": "local_record",
                "coding_task_id": task.id,
                "execution_run_id": run.id,
                "source_branch": source_branch,
                "target_branch": target_branch,
                "commit_sha": run.commit_sha,
            },
        )
