"""Auth data access layer."""

from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.modules.auth.models import AuthApiToken, AuthProject, AuthProjectMember, AuthUser


class AuthRepository:
    """Repository for local auth and project access."""

    async def count_users(self, db: AsyncSession) -> int:
        result = await db.execute(select(func.count(AuthUser.id)))
        return int(result.scalar_one() or 0)

    async def create_user(
        self,
        db: AsyncSession,
        username: str,
        display_name: str,
        password_hash: str,
        role: str = "operator",
        email: str | None = None,
        status: str = "active",
    ) -> AuthUser:
        user = AuthUser(
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            status=status,
            password_hash=password_hash,
        )
        db.add(user)
        await db.flush()
        return user

    async def get_user_by_username(self, db: AsyncSession, username: str) -> Optional[AuthUser]:
        result = await db.execute(
            select(AuthUser)
            .options(selectinload(AuthUser.memberships).selectinload(AuthProjectMember.project))
            .where(AuthUser.username == username)
        )
        return result.scalar_one_or_none()

    async def get_user_by_id(self, db: AsyncSession, user_id: int) -> Optional[AuthUser]:
        result = await db.execute(
            select(AuthUser)
            .options(selectinload(AuthUser.memberships).selectinload(AuthProjectMember.project))
            .where(AuthUser.id == user_id)
        )
        return result.scalar_one_or_none()

    async def create_project(
        self,
        db: AsyncSession,
        key: str,
        name: str,
        repository_root: str | None = None,
        default_branch: str = "main",
        status: str = "active",
    ) -> AuthProject:
        project = AuthProject(
            key=key,
            name=name,
            repository_root=repository_root,
            default_branch=default_branch,
            status=status,
        )
        db.add(project)
        await db.flush()
        return project

    async def get_project_by_key(self, db: AsyncSession, key: str) -> Optional[AuthProject]:
        result = await db.execute(select(AuthProject).where(AuthProject.key == key))
        return result.scalar_one_or_none()

    async def get_project(self, db: AsyncSession, project_id: int) -> Optional[AuthProject]:
        result = await db.execute(select(AuthProject).where(AuthProject.id == project_id))
        return result.scalar_one_or_none()

    async def list_projects(
        self,
        db: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuthProject]:
        result = await db.execute(
            select(AuthProject)
            .order_by(AuthProject.created_at.desc(), AuthProject.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_users(
        self,
        db: AsyncSession,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuthUser]:
        result = await db.execute(
            select(AuthUser)
            .options(selectinload(AuthUser.memberships).selectinload(AuthProjectMember.project))
            .order_by(AuthUser.created_at.desc(), AuthUser.id.desc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_projects_for_user(self, db: AsyncSession, user_id: int) -> list[AuthProject]:
        result = await db.execute(
            select(AuthProject)
            .join(AuthProjectMember, AuthProjectMember.project_id == AuthProject.id)
            .where(AuthProjectMember.user_id == user_id)
            .order_by(AuthProject.name.asc(), AuthProject.id.asc())
        )
        return list(result.scalars().all())

    async def create_project_member(
        self,
        db: AsyncSession,
        user_id: int,
        project_id: int,
        role: str = "operator",
    ) -> AuthProjectMember:
        member = AuthProjectMember(user_id=user_id, project_id=project_id, role=role)
        db.add(member)
        await db.flush()
        return member

    async def create_api_token(
        self,
        db: AsyncSession,
        user_id: int,
        name: str,
        token_hash: str,
        scopes: list[str] | None = None,
        expires_at: datetime | None = None,
    ) -> AuthApiToken:
        token = AuthApiToken(
            user_id=user_id,
            name=name,
            token_hash=token_hash,
            scopes_json=scopes or [],
            expires_at=expires_at,
        )
        db.add(token)
        await db.flush()
        return token

    async def get_api_token_by_hash(
        self,
        db: AsyncSession,
        token_hash: str,
    ) -> Optional[AuthApiToken]:
        result = await db.execute(
            select(AuthApiToken)
            .options(
                selectinload(AuthApiToken.user)
                .selectinload(AuthUser.memberships)
                .selectinload(AuthProjectMember.project)
            )
            .where(AuthApiToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()


auth_repository = AuthRepository()
