"""Merge request client factory."""

from app.core.exceptions import BadRequestException
from app.modules.delivery.merge_requests.base import MergeRequestClient
from app.modules.delivery.merge_requests.local import LocalMergeRequestClient


def get_merge_request_client(provider: str) -> MergeRequestClient:
    """Return the merge request client for a configured provider."""

    normalized = (provider or "local").strip().lower()
    if normalized == "local":
        return LocalMergeRequestClient()
    raise BadRequestException(
        f"Merge request provider '{provider}' is not configured. Use provider='local' first."
    )
