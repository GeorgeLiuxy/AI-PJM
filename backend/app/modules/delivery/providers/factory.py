"""Workflow provider factory."""

from app.core.config import settings
from app.core.exceptions import AIServiceException
from app.modules.delivery.providers.base import WorkflowProvider
from app.modules.delivery.providers.mock import MockWorkflowProvider


def get_workflow_provider(provider_name: str | None = None) -> WorkflowProvider:
    """Resolve the configured workflow provider.

    Only the deterministic mock provider is implemented in this slice. The
    factory is the stable provider boundary for later Dify/OpenAI providers.
    """

    selected = (provider_name or settings.ai_workflow_provider).strip().lower()
    if selected == "mock":
        return MockWorkflowProvider()
    if selected == "dify":
        raise AIServiceException("Dify workflow provider is configured but not implemented yet")
    if selected == "openai":
        raise AIServiceException("OpenAI workflow provider is configured but not implemented yet")
    raise AIServiceException(f"Unknown workflow provider: {selected}")
