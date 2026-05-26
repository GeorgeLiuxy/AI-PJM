"""Workflow provider factory."""

from app.core.config import settings
from app.core.exceptions import AIServiceException
from app.modules.delivery.providers.base import WorkflowProvider
from app.modules.delivery.providers.dify import DifyWorkflowProvider
from app.modules.delivery.providers.local import LocalWorkflowProvider
from app.modules.delivery.providers.mock import MockWorkflowProvider


def get_workflow_provider(provider_name: str | None = None) -> WorkflowProvider:
    """Resolve the configured workflow provider.

    The factory is the stable provider boundary for later Dify/OpenAI providers.
    """

    selected = (provider_name or settings.ai_workflow_provider).strip().lower()
    if selected == "local":
        return LocalWorkflowProvider()
    if selected == "mock":
        return MockWorkflowProvider()
    if selected == "dify":
        return DifyWorkflowProvider()
    if selected == "openai":
        raise AIServiceException("OpenAI workflow provider is configured but not implemented yet")
    raise AIServiceException(f"Unknown workflow provider: {selected}")
