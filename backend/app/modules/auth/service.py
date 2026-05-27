"""Auth service and authorization helpers."""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestException, NotFoundException, UnauthorizedException
from app.modules.auth.models import AuthUser
from app.modules.auth.repository import auth_repository
from app.modules.auth.security import (
    generate_api_token,
    hash_api_token,
    hash_password,
    verify_password,
)


GLOBAL_ROLES = {"admin", "operator", "reviewer", "viewer"}
PROJECT_ROLES = {"owner", "operator", "reviewer", "viewer"}
USER_STATUSES = {"active", "disabled"}

READ_ROLES = {"admin", "operator", "reviewer", "viewer", "owner"}
OPERATE_ROLES = {"admin", "operator", "owner"}
REVIEW_ROLES = {"admin", "reviewer", "owner"}
ADMIN_ROLES = {"admin", "owner"}


@dataclass(frozen=True)
class AuthProjectAccess:
    """Project visible to the current principal."""

    id: int
    key: str
    name: str
    role: str


@dataclass(frozen=True)
class AuthPrincipal:
    """Authenticated user context passed into API handlers."""

    user_id: int | None
    username: str
    display_name: str
    role: str
    auth_enabled: bool
    projects: tuple[AuthProjectAccess, ...] = ()

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def accessible_project_ids(self) -> list[int] | None:
        if not self.auth_enabled or self.is_admin:
            return None
        return [project.id for project in self.projects]

    @property
    def default_project_id(self) -> int | None:
        return self.projects[0].id if self.projects else None

    def project_role(self, project_id: int | None) -> str | None:
        if not self.auth_enabled:
            return "owner"
        if self.is_admin:
            return "owner"
        if project_id is None:
            return None
        for project in self.projects:
            if project.id == project_id:
                return project.role
        return None


class AuthService:
    """Local auth service."""

    async def ensure_bootstrap_data(self, db: AsyncSession) -> None:
        """Create the first admin/project when configured and no users exist."""

        if not settings.auth_bootstrap_admin_password:
            return
        if await auth_repository.count_users(db) > 0:
            return

        user = await auth_repository.create_user(
            db=db,
            username=settings.auth_bootstrap_admin_username,
            display_name=settings.auth_bootstrap_admin_display_name,
            password_hash=hash_password(settings.auth_bootstrap_admin_password),
            role="admin",
        )
        project = await auth_repository.create_project(
            db=db,
            key=settings.auth_bootstrap_project_key,
            name=settings.auth_bootstrap_project_name,
        )
        await auth_repository.create_project_member(db, user.id, project.id, role="owner")
        await db.commit()

    async def authenticate(self, db: AsyncSession, username: str, password: str) -> AuthUser:
        user = await auth_repository.get_user_by_username(db, username)
        if not user or user.status != "active" or not verify_password(password, user.password_hash):
            raise UnauthorizedException("Invalid username or password")
        return user

    async def login(self, db: AsyncSession, username: str, password: str) -> tuple[AuthPrincipal, str]:
        user = await self.authenticate(db, username, password)
        raw_token = generate_api_token()
        await auth_repository.create_api_token(
            db=db,
            user_id=user.id,
            name="browser",
            token_hash=hash_api_token(raw_token),
            scopes=["api"],
        )
        await db.commit()

        loaded_user = await auth_repository.get_user_by_id(db, user.id)
        if not loaded_user:
            raise UnauthorizedException("Invalid username or password")
        return self.build_principal(loaded_user, auth_enabled=True), raw_token

    async def create_local_user(
        self,
        db: AsyncSession,
        username: str,
        password: str,
        display_name: str,
        role: str = "operator",
        email: str | None = None,
        project_id: int | None = None,
        project_role: str = "operator",
    ) -> AuthUser:
        role = self._validate_role(role, GLOBAL_ROLES, "role")
        project_role = self._validate_role(project_role, PROJECT_ROLES, "project_role")
        user = await auth_repository.create_user(
            db=db,
            username=username,
            display_name=display_name,
            email=email,
            role=role,
            password_hash=hash_password(password),
        )
        if project_id is not None:
            await auth_repository.create_project_member(db, user.id, project_id, role=project_role)
        await db.commit()
        return user

    async def update_local_user(
        self,
        db: AsyncSession,
        user_id: int,
        *,
        display_name: str | None = None,
        email: str | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> AuthUser:
        user = await auth_repository.get_user_by_id(db, user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")

        values = {}
        if display_name is not None:
            normalized_display_name = display_name.strip()
            if not normalized_display_name:
                raise BadRequestException("Display name is required")
            values["display_name"] = normalized_display_name
        if email is not None:
            values["email"] = email.strip() or None
        if role is not None:
            values["role"] = self._validate_role(role, GLOBAL_ROLES, "role")
        if status is not None:
            values["status"] = self._validate_role(status, USER_STATUSES, "status")
        if not values:
            raise BadRequestException("No user changes provided")

        await auth_repository.update_user(db, user, **values)
        return user

    async def reset_local_user_password(self, db: AsyncSession, user_id: int, password: str) -> AuthUser:
        user = await auth_repository.get_user_by_id(db, user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        await auth_repository.update_user(db, user, password_hash=hash_password(password))
        return user

    async def upsert_project_member(
        self,
        db: AsyncSession,
        *,
        user_id: int,
        project_id: int,
        role: str,
    ) -> AuthUser:
        user = await auth_repository.get_user_by_id(db, user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        project = await auth_repository.get_project(db, project_id)
        if not project:
            raise NotFoundException(f"Project {project_id} not found")
        project_role = self._validate_role(role, PROJECT_ROLES, "project_role")
        await auth_repository.upsert_project_member(db, user_id=user_id, project_id=project_id, role=project_role)
        loaded_user = await auth_repository.get_user_by_id(db, user_id)
        if not loaded_user:
            raise NotFoundException(f"User {user_id} not found")
        return loaded_user

    async def remove_project_member(self, db: AsyncSession, *, user_id: int, project_id: int) -> AuthUser:
        user = await auth_repository.get_user_by_id(db, user_id)
        if not user:
            raise NotFoundException(f"User {user_id} not found")
        member = await auth_repository.get_project_member(db, user_id=user_id, project_id=project_id)
        if not member:
            raise NotFoundException(f"Project membership for user {user_id} and project {project_id} not found")
        await auth_repository.delete_project_member(db, member)
        loaded_user = await auth_repository.get_user_by_id(db, user_id)
        if not loaded_user:
            raise NotFoundException(f"User {user_id} not found")
        return loaded_user

    async def validate_token(self, db: AsyncSession, raw_token: str) -> AuthPrincipal:
        token = await auth_repository.get_api_token_by_hash(db, hash_api_token(raw_token))
        now = datetime.now(timezone.utc)
        if not token or token.revoked_at is not None:
            raise UnauthorizedException("Invalid or expired token")
        if token.expires_at and token.expires_at <= now:
            raise UnauthorizedException("Invalid or expired token")
        if not token.user or token.user.status != "active":
            raise UnauthorizedException("Invalid or expired token")

        token.last_used_at = now
        await db.flush()
        return self.build_principal(token.user, auth_enabled=True)

    def build_principal(self, user: AuthUser, auth_enabled: bool) -> AuthPrincipal:
        projects = tuple(
            AuthProjectAccess(
                id=member.project.id,
                key=member.project.key,
                name=member.project.name,
                role=member.role,
            )
            for member in user.memberships
            if member.project and member.project.status == "active"
        )
        return AuthPrincipal(
            user_id=user.id,
            username=user.username,
            display_name=user.display_name,
            role=user.role,
            auth_enabled=auth_enabled,
            projects=projects,
        )

    def local_principal(self) -> AuthPrincipal:
        return AuthPrincipal(
            user_id=None,
            username="local_operator",
            display_name="Local Operator",
            role="admin",
            auth_enabled=False,
            projects=(),
        )

    def can(self, principal: AuthPrincipal, capability: str, project_id: int | None = None) -> bool:
        if not principal.auth_enabled:
            return True
        if principal.is_admin:
            roles = {"admin"}
        elif project_id is not None:
            project_role = principal.project_role(project_id)
            roles = {project_role} if project_role else set()
        else:
            roles = {principal.role}
        if capability == "read":
            return bool(roles & READ_ROLES)
        if capability == "operate":
            return bool(roles & OPERATE_ROLES)
        if capability == "review":
            return bool(roles & REVIEW_ROLES)
        if capability == "admin":
            return bool(roles & ADMIN_ROLES)
        return False

    def _validate_role(self, value: str, allowed: set[str], field_name: str) -> str:
        if value not in allowed:
            raise BadRequestException(f"Invalid {field_name}: {value}")
        return value


auth_service = AuthService()
