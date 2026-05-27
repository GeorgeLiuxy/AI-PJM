"""Auth API schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class AuthProjectResponse(BaseModel):
    """Project visible to the current user."""

    id: int
    key: str
    name: str
    role: str
    status: str = "active"
    default_branch: str = "main"
    repository_root: Optional[str] = None
    created_at: Optional[datetime] = None


class AuthUserResponse(BaseModel):
    """Current user response."""

    id: Optional[int] = None
    username: str
    display_name: str
    role: str
    auth_enabled: bool
    projects: list[AuthProjectResponse] = Field(default_factory=list)


class AuthLoginRequest(BaseModel):
    """Password login request."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=200)


class AuthLoginResponse(BaseModel):
    """Password login response with bearer token."""

    access_token: str
    token_type: str = "bearer"
    user: AuthUserResponse


class AuthProjectCreateRequest(BaseModel):
    """Create a project boundary."""

    key: str = Field(..., min_length=1, max_length=100)
    name: str = Field(..., min_length=1, max_length=200)
    repository_root: Optional[str] = Field(default=None, max_length=1000)
    default_branch: str = Field(default="main", max_length=200)


class AuthLocalUserCreateRequest(BaseModel):
    """Create a local user before external identity is available."""

    username: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=8, max_length=200)
    display_name: str = Field(..., min_length=1, max_length=200)
    email: Optional[str] = Field(default=None, max_length=320)
    role: str = Field(default="operator", max_length=50)
    project_id: Optional[int] = None
    project_role: str = Field(default="operator", max_length=50)


class AuthUserCreatedResponse(AuthUserResponse):
    """Created user response."""

    created_at: datetime


class AuthUserListItemResponse(AuthUserResponse):
    """Managed user response for admin pages."""

    email: Optional[str] = None
    status: str
    created_at: datetime
