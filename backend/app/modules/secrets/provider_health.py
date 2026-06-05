"""Remote provider health probes for project secrets."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.modules.delivery.redaction import redact_text


@dataclass(frozen=True)
class ProviderHealthProbeResult:
    """Remote provider health result without secret material."""

    status: str
    reason: str | None
    remote_probe: bool
    endpoint: str | None = None


async def check_remote_provider_health(provider: str, secret_value: str) -> ProviderHealthProbeResult:
    """Check whether a provider credential can reach its remote service safely."""

    normalized = provider.strip().lower()
    if normalized == "openai":
        return await _check_openai(secret_value)
    if normalized == "dify":
        return await _check_dify(secret_value)
    if normalized == "gitlab":
        return await _check_gitlab(secret_value)
    if normalized == "github":
        return await _check_github(secret_value)
    return ProviderHealthProbeResult(
        status="unknown",
        reason=f"Remote probe is not supported for provider '{normalized}'.",
        remote_probe=False,
    )


async def _check_openai(api_key: str) -> ProviderHealthProbeResult:
    base_url = settings.openai_api_base_url.strip().rstrip("/")
    if not base_url:
        return ProviderHealthProbeResult(
            status="unknown",
            reason="OPENAI_API_BASE_URL is not configured.",
            remote_probe=False,
        )
    return await _get_with_token(
        url=f"{base_url}/models",
        headers={"Authorization": f"Bearer {api_key}"},
        endpoint="openai.models",
    )


async def _check_dify(api_key: str) -> ProviderHealthProbeResult:
    health_url = settings.dify_health_check_url.strip()
    if not health_url:
        return ProviderHealthProbeResult(
            status="unknown",
            reason="DIFY_HEALTH_CHECK_URL is not configured; refusing to probe Dify workflows implicitly.",
            remote_probe=False,
        )
    return await _get_with_token(
        url=health_url,
        headers={"Authorization": f"Bearer {api_key}"},
        endpoint="dify.health_check",
    )


async def _check_gitlab(token: str) -> ProviderHealthProbeResult:
    base_url = settings.gitlab_api_base_url.strip().rstrip("/")
    if not base_url:
        return ProviderHealthProbeResult(
            status="unknown",
            reason="GITLAB_API_BASE_URL is not configured.",
            remote_probe=False,
        )
    return await _get_with_token(
        url=f"{base_url}/user",
        headers={"PRIVATE-TOKEN": token},
        endpoint="gitlab.user",
    )


async def _check_github(token: str) -> ProviderHealthProbeResult:
    base_url = settings.github_api_base_url.strip().rstrip("/")
    if not base_url:
        return ProviderHealthProbeResult(
            status="unknown",
            reason="GITHUB_API_BASE_URL is not configured.",
            remote_probe=False,
        )
    return await _get_with_token(
        url=f"{base_url}/user",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        endpoint="github.user",
    )


async def _get_with_token(
    *,
    url: str,
    headers: dict[str, str],
    endpoint: str,
) -> ProviderHealthProbeResult:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return ProviderHealthProbeResult(
            status="unknown",
            reason=f"Remote provider probe failed: {redact_text(str(exc))[:500]}",
            remote_probe=True,
            endpoint=endpoint,
        )

    if 200 <= response.status_code < 400:
        return ProviderHealthProbeResult(
            status="healthy",
            reason=None,
            remote_probe=True,
            endpoint=endpoint,
        )
    if response.status_code in {401, 403}:
        return ProviderHealthProbeResult(
            status="invalid",
            reason=f"Remote provider rejected the credential with HTTP {response.status_code}.",
            remote_probe=True,
            endpoint=endpoint,
        )
    return ProviderHealthProbeResult(
        status="unknown",
        reason=f"Remote provider returned HTTP {response.status_code}.",
        remote_probe=True,
        endpoint=endpoint,
    )
