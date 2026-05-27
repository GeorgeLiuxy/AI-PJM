"""Auth API endpoints."""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.responses import success_response
from app.core.db import get_db
from app.modules.audit.repository import audit_repository
from app.modules.auth.dependencies import get_current_principal, require_capability
from app.modules.auth.repository import auth_repository
from app.modules.auth.schemas import (
    AuthLocalUserCreateRequest,
    AuthLoginRequest,
    AuthLoginResponse,
    AuthProjectCreateRequest,
    AuthProjectResponse,
    AuthUserCreatedResponse,
    AuthUserListItemResponse,
    AuthUserResponse,
)
from app.modules.auth.service import AuthPrincipal, auth_service


router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=dict)
async def login(request: AuthLoginRequest, db: AsyncSession = Depends(get_db)):
    principal, access_token = await auth_service.login(
        db=db,
        username=request.username,
        password=request.password,
    )
    return success_response(
        data=AuthLoginResponse(
            access_token=access_token,
            user=_principal_response(principal),
        ).model_dump(),
        message="Login succeeded",
    )


@router.get("/me", response_model=dict)
async def get_me(principal: AuthPrincipal = Depends(get_current_principal)):
    return success_response(data=_principal_response(principal).model_dump(), message="Success")


@router.get("/projects", response_model=dict)
async def list_projects(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "admin")
    projects = await auth_repository.list_projects(
        db=db,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )
    return success_response(
        data=[
            AuthProjectResponse(
                id=project.id,
                key=project.key,
                name=project.name,
                role="owner",
                status=project.status,
                default_branch=project.default_branch,
                repository_root=project.repository_root,
                created_at=project.created_at,
            ).model_dump()
            for project in projects
        ],
        message="Success",
    )


@router.post("/projects", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_project(
    request: AuthProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "admin")
    project = await auth_repository.create_project(
        db=db,
        key=request.key,
        name=request.name,
        repository_root=request.repository_root,
        default_branch=request.default_branch,
    )
    await audit_repository.create_event(
        db,
        action="auth.project_created",
        entity_type="project",
        entity_id=project.id,
        project_id=project.id,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
        summary=f"Project created: {project.name}",
        metadata={"key": project.key, "default_branch": project.default_branch},
    )
    await db.commit()
    return success_response(
        data=AuthProjectResponse(
            id=project.id,
            key=project.key,
            name=project.name,
            role="owner",
            status=project.status,
            default_branch=project.default_branch,
            repository_root=project.repository_root,
            created_at=project.created_at,
        ).model_dump(),
        message="Project created",
        code=201,
    )


@router.get("/users", response_model=dict)
async def list_users(
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "admin")
    users = await auth_repository.list_users(
        db=db,
        limit=min(max(limit, 1), 200),
        offset=max(offset, 0),
    )
    return success_response(
        data=[_managed_user_response(user).model_dump() for user in users],
        message="Success",
    )


@router.post("/users", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_local_user(
    request: AuthLocalUserCreateRequest,
    db: AsyncSession = Depends(get_db),
    principal: AuthPrincipal = Depends(get_current_principal),
):
    require_capability(principal, "admin", request.project_id)
    user = await auth_service.create_local_user(
        db=db,
        username=request.username,
        password=request.password,
        display_name=request.display_name,
        email=request.email,
        role=request.role,
        project_id=request.project_id,
        project_role=request.project_role,
    )
    await audit_repository.create_event(
        db,
        action="auth.user_created",
        entity_type="user",
        entity_id=user.id,
        project_id=request.project_id,
        actor_user_id=principal.user_id,
        actor_ref=principal.username,
        summary=f"Local user created: {user.username}",
        metadata={
            "role": user.role,
            "project_id": request.project_id,
            "project_role": request.project_role,
        },
    )
    await db.commit()
    return success_response(
        data=AuthUserCreatedResponse(
            id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            auth_enabled=True,
            projects=[],
            created_at=user.created_at,
        ).model_dump(),
        message="User created",
        code=201,
    )


def _principal_response(principal: AuthPrincipal) -> AuthUserResponse:
    return AuthUserResponse(
        id=principal.user_id,
        username=principal.username,
        display_name=principal.display_name,
        role=principal.role,
        auth_enabled=principal.auth_enabled,
        projects=[
            AuthProjectResponse(
                id=project.id,
                key=project.key,
                name=project.name,
                role=project.role,
            )
            for project in principal.projects
        ],
    )


def _managed_user_response(user) -> AuthUserListItemResponse:
    return AuthUserListItemResponse(
        id=user.id,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
        role=user.role,
        status=user.status,
        auth_enabled=True,
        created_at=user.created_at,
        projects=[
            AuthProjectResponse(
                id=membership.project.id,
                key=membership.project.key,
                name=membership.project.name,
                role=membership.role,
                status=membership.project.status,
                default_branch=membership.project.default_branch,
                repository_root=membership.project.repository_root,
                created_at=membership.project.created_at,
            )
            for membership in user.memberships
            if membership.project
        ],
    )
