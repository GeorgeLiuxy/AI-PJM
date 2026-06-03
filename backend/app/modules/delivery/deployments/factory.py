"""Deployment client factory."""

from app.core.exceptions import BadRequestException
from app.modules.delivery.deployments.base import DeployClient
from app.modules.delivery.deployments.local import LocalDeployClient
from app.modules.delivery.deployments.webhook import WebhookDeployClient
from app.modules.delivery.provider_credentials import ProviderCredential


def get_deploy_client(
    provider: str,
    *,
    credential: ProviderCredential | None = None,
) -> DeployClient:
    """Return the deployment client for a configured provider."""

    normalized = (provider or "local").strip().lower()
    if normalized == "local":
        return LocalDeployClient()
    if normalized == "webhook":
        if credential is None:
            raise BadRequestException("Webhook deployment provider requires credentials")
        return WebhookDeployClient(credential=credential)
    raise BadRequestException(
        f"Deployment provider '{provider}' is not configured. Supported providers: local, webhook."
    )
