"""Merge request client factory."""

from app.core.exceptions import BadRequestException
from app.modules.delivery.merge_requests.base import MergeRequestClient
from app.modules.delivery.merge_requests.github import GitHubPullRequestClient
from app.modules.delivery.merge_requests.gitlab import GitLabMergeRequestClient
from app.modules.delivery.merge_requests.local import LocalMergeRequestClient
from app.modules.delivery.provider_credentials import ProviderCredential


def get_merge_request_client(
    provider: str,
    *,
    credential: ProviderCredential | None = None,
) -> MergeRequestClient:
    """Return the merge request client for a configured provider."""

    normalized = (provider or "local").strip().lower()
    if normalized == "local":
        return LocalMergeRequestClient()
    if normalized == "gitlab":
        if credential is None:
            raise BadRequestException("GitLab merge request provider requires credentials")
        return GitLabMergeRequestClient(credential=credential)
    if normalized == "github":
        if credential is None:
            raise BadRequestException("GitHub pull request provider requires credentials")
        return GitHubPullRequestClient(credential=credential)
    raise BadRequestException(
        f"Merge request provider '{provider}' is not configured. Supported providers: local, gitlab, github."
    )
