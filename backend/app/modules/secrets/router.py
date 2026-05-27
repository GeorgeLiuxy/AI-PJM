"""Secret store API endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.core.db import get_db
from app.core.exceptions import NotFoundException
from app.modules.auth.dependencies import get_current_principal, require_capability
from app.modules.auth.service import AuthPrincipal
from app.modules.secrets.repository import secret_repository
from app.modules.secrets.schemas import (
    SecretCreateRequest,
    SecretRecordResponse,
    SecretRotateRequest,
)
from app.modules.secrets.service import secret_store_service


router = APIRouter(prefix="/secrets", tags=["secrets"])


@router.get("", response_model=dict)
async def list_secrets(
    project_id: int | None = None,
    provider: str | None = None,
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "admin", project_id)
    records = await secret_repository.list_secrets(
        db,
        project_ids=principal.accessible_project_ids if project_id is None else None,
        project_id=project_id,
        provider=provider,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )
    return success_response(
        data=[SecretRecordResponse.model_validate(record).model_dump() for record in records],
        message="Success",
    )


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_secret(
    request: SecretCreateRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "admin", request.project_id)
    record = await secret_store_service.create_secret(
        db,
        project_id=request.project_id,
        name=request.name,
        provider=request.provider,
        value=request.value,
        description=request.description,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=SecretRecordResponse.model_validate(record).model_dump(),
        message="Secret created",
        code=201,
    )


@router.post("/{secret_id}/rotate", response_model=dict)
async def rotate_secret(
    secret_id: int,
    request: SecretRotateRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    record = await secret_repository.get_secret(db, secret_id)
    if not record:
        raise NotFoundException(f"Secret {secret_id} not found")
    require_capability(principal, "admin", record.project_id)
    rotated = await secret_store_service.rotate_secret(
        db,
        secret_id=secret_id,
        value=request.value,
        description=request.description,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
    )
    return success_response(
        data=SecretRecordResponse.model_validate(rotated).model_dump(),
        message="Secret rotated",
    )
