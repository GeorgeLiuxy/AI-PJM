"""Secret store service."""

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import utc_now
from app.core.exceptions import BadRequestException, ConflictException, NotFoundException
from app.modules.audit.repository import audit_repository
from app.modules.auth.repository import auth_repository
from app.modules.secrets.crypto import (
    decrypt_secret,
    encrypt_secret,
    mask_secret,
    secret_fingerprint,
)
from app.modules.secrets.models import SecretRecord
from app.modules.secrets.repository import secret_repository


class SecretStoreService:
    """Project-scoped encrypted secret management."""

    async def create_secret(
        self,
        db: AsyncSession,
        *,
        project_id: int,
        name: str,
        provider: str,
        value: str,
        actor_user_id: int | None = None,
        actor_ref: str = "system",
        description: str | None = None,
    ) -> SecretRecord:
        normalized_name = self._normalize_name(name)
        normalized_provider = self._normalize_provider(provider)
        project = await auth_repository.get_project(db, project_id)
        if not project:
            raise NotFoundException(f"Project {project_id} not found")
        try:
            record = await secret_repository.create_secret(
                db,
                project_id=project_id,
                name=normalized_name,
                provider=normalized_provider,
                description=description,
                ciphertext=encrypt_secret(value),
                value_hash=secret_fingerprint(value),
                value_mask=mask_secret(value),
                key_id=settings.secret_store_key_id,
                created_by_user_id=actor_user_id,
            )
            await audit_repository.create_event(
                db,
                action="secret.created",
                entity_type="secret",
                entity_id=record.id,
                project_id=project_id,
                actor_user_id=actor_user_id,
                actor_ref=actor_ref,
                summary=f"Secret created: {record.name}",
                metadata={"provider": record.provider, "key_id": record.key_id},
            )
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ConflictException(f"Secret '{normalized_name}' already exists in this project") from exc
        return record

    async def rotate_secret(
        self,
        db: AsyncSession,
        *,
        secret_id: int,
        value: str,
        actor_user_id: int | None = None,
        actor_ref: str = "system",
        description: str | None = None,
    ) -> SecretRecord:
        record = await secret_repository.get_secret(db, secret_id)
        if not record:
            raise NotFoundException(f"Secret {secret_id} not found")
        await secret_repository.update_secret(
            db,
            record,
            ciphertext=encrypt_secret(value),
            value_hash=secret_fingerprint(value),
            value_mask=mask_secret(value),
            key_id=settings.secret_store_key_id,
            description=description if description is not None else record.description,
            updated_by_user_id=actor_user_id,
        )
        await audit_repository.create_event(
            db,
            action="secret.rotated",
            entity_type="secret",
            entity_id=record.id,
            project_id=record.project_id,
            actor_user_id=actor_user_id,
            actor_ref=actor_ref,
            summary=f"Secret rotated: {record.name}",
            metadata={"provider": record.provider, "key_id": record.key_id},
        )
        await db.commit()
        return record

    async def resolve_secret_by_name(
        self,
        db: AsyncSession,
        *,
        project_id: int,
        name: str,
    ) -> str:
        record = await secret_repository.get_secret_by_name(
            db,
            project_id=project_id,
            name=self._normalize_name(name),
        )
        if not record or record.status != "active":
            raise NotFoundException(f"Secret '{name}' not found")
        value = decrypt_secret(record.ciphertext)
        await secret_repository.update_secret(db, record, last_used_at=utc_now())
        return value

    def _normalize_name(self, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise BadRequestException("Secret name is required")
        return normalized

    def _normalize_provider(self, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise BadRequestException("Secret provider is required")
        return normalized


secret_store_service = SecretStoreService()
