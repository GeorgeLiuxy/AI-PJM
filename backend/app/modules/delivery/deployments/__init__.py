"""Deployment client boundary."""

from app.modules.delivery.deployments.factory import get_deploy_client

__all__ = ["get_deploy_client"]
