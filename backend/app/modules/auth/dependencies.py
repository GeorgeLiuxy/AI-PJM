"""FastAPI dependencies for authentication and authorization."""

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.core.exceptions import ForbiddenException, UnauthorizedException
from app.modules.auth.service import AuthPrincipal, auth_service


async def get_current_principal(
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> AuthPrincipal:
    """Resolve the current authenticated principal.

    Auth is optional in local development. When disabled, the platform runs as a
    local admin principal so existing local flows remain usable.
    """

    if not settings.auth_enabled:
        return auth_service.local_principal()

    if not authorization:
        raise UnauthorizedException("Authentication required")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise UnauthorizedException("Authentication required")

    return await auth_service.validate_token(db, token.strip())


def require_capability(
    principal: AuthPrincipal,
    capability: str,
    project_id: int | None = None,
) -> None:
    """Raise 403 unless the principal has the requested capability."""

    if not auth_service.can(principal, capability, project_id):
        raise ForbiddenException("Permission denied")

