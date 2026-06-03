"""Project-scoped provider credential resolution."""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestException, NotFoundException
from app.modules.secrets.service import secret_store_service


@dataclass(frozen=True)
class ProviderCredential:
    """Resolved provider credential without leaking its value in repr/evidence."""

    provider: str
    value: str = field(repr=False)
    source: str = "settings"
    project_id: int | None = None
    secret_name: str | None = None

    def metadata(self, *, secret_name_key: str = "secret_name") -> dict:
        metadata: dict = {"credential_source": self.source}
        if self.project_id is not None:
            metadata["credential_project_id"] = self.project_id
        if self.secret_name:
            metadata[secret_name_key] = self.secret_name
        return metadata


async def resolve_provider_credential(
    db: AsyncSession,
    *,
    project_id: int | None,
    provider: str,
    secret_name: str | None,
    settings_value: str | None,
) -> ProviderCredential | None:
    """Resolve a provider credential from project SecretStore, then settings."""

    normalized_provider = provider.strip().lower()
    normalized_secret_name = (secret_name or "").strip()
    if project_id is not None and normalized_secret_name:
        try:
            value = await secret_store_service.resolve_secret_by_name(
                db,
                project_id=project_id,
                name=normalized_secret_name,
            )
        except NotFoundException:
            value = ""
        if value.strip():
            return ProviderCredential(
                provider=normalized_provider,
                value=value.strip(),
                source="secret_store",
                project_id=project_id,
                secret_name=normalized_secret_name,
            )

    fallback_value = (settings_value or "").strip()
    if fallback_value:
        return ProviderCredential(
            provider=normalized_provider,
            value=fallback_value,
            source="settings",
        )

    return None


def require_provider_credential(
    credential: ProviderCredential | None,
    *,
    provider: str,
    secret_name: str | None,
    settings_name: str,
) -> ProviderCredential:
    """Require a credential for an external provider operation."""

    if credential is not None and credential.value.strip():
        return credential
    configured_name = (secret_name or "").strip()
    hint = f"project SecretStore secret '{configured_name}'" if configured_name else "project SecretStore"
    raise BadRequestException(
        f"Provider '{provider}' requires credentials. Configure {hint} or {settings_name}."
    )
