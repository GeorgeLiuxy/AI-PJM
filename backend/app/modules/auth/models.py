"""Auth and project access models."""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, DB_BIGINT, DB_JSON, utc_now


class AuthUser(Base):
    """Local user account used before enterprise SSO is introduced."""

    __tablename__ = "auth_users"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="operator")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    memberships: Mapped[list["AuthProjectMember"]] = relationship(
        "AuthProjectMember",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    api_tokens: Mapped[list["AuthApiToken"]] = relationship(
        "AuthApiToken",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_auth_users_username", "username"),
        Index("ix_auth_users_role", "role"),
        Index("ix_auth_users_status", "status"),
    )


class AuthProject(Base):
    """Project boundary for delivery work and permissions."""

    __tablename__ = "auth_projects"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    repository_root: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    default_branch: Mapped[str] = mapped_column(String(200), nullable=False, default="main")
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="active")
    settings_json: Mapped[Optional[dict[str, Any]]] = mapped_column(DB_JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )

    memberships: Mapped[list["AuthProjectMember"]] = relationship(
        "AuthProjectMember",
        back_populates="project",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_auth_projects_key", "key"),
        Index("ix_auth_projects_status", "status"),
    )


class AuthProjectMember(Base):
    """User membership and project-scoped role."""

    __tablename__ = "auth_project_members"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("auth_projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(50), nullable=False, default="operator")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="memberships")
    project: Mapped["AuthProject"] = relationship("AuthProject", back_populates="memberships")

    __table_args__ = (
        UniqueConstraint("user_id", "project_id", name="uq_auth_project_members_user_project"),
        Index("ix_auth_project_members_user_id", "user_id"),
        Index("ix_auth_project_members_project_id", "project_id"),
        Index("ix_auth_project_members_role", "role"),
    )


class AuthApiToken(Base):
    """Hashed API token for browser and CLI access."""

    __tablename__ = "auth_api_tokens"

    id: Mapped[int] = mapped_column(DB_BIGINT, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        DB_BIGINT,
        ForeignKey("auth_users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    scopes_json: Mapped[list[str]] = mapped_column(DB_JSON, nullable=False, default=list)
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)

    user: Mapped["AuthUser"] = relationship("AuthUser", back_populates="api_tokens")

    __table_args__ = (
        Index("ix_auth_api_tokens_user_id", "user_id"),
        Index("ix_auth_api_tokens_token_hash", "token_hash"),
        Index("ix_auth_api_tokens_revoked_at", "revoked_at"),
    )

