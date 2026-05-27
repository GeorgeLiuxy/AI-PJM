"""Secret store service."""

from datetime import datetime, timedelta

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
from app.modules.secrets.schemas import SecretRecordResponse


EXPIRING_SOON_DAYS = 14


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
        expires_at: datetime | None = None,
    ) -> SecretRecord:
        normalized_name = self._normalize_name(name)
        normalized_provider = self._normalize_provider(provider)
        metadata = self._metadata_with_expiry(None, expires_at)
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
                metadata=metadata,
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
        expires_at: datetime | None = None,
    ) -> SecretRecord:
        record = await secret_repository.get_secret(db, secret_id)
        if not record:
            raise NotFoundException(f"Secret {secret_id} not found")
        metadata = self._metadata_with_expiry(record.metadata_json, expires_at)
        await secret_repository.update_secret(
            db,
            record,
            ciphertext=encrypt_secret(value),
            value_hash=secret_fingerprint(value),
            value_mask=mask_secret(value),
            key_id=settings.secret_store_key_id,
            description=description if description is not None else record.description,
            updated_by_user_id=actor_user_id,
            metadata_json=metadata,
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

    async def check_secret_health(self, db: AsyncSession, secret_id: int) -> SecretRecordResponse:
        record = await secret_repository.get_secret(db, secret_id)
        if not record:
            raise NotFoundException(f"Secret {secret_id} not found")
        return self.to_response(record, verify_decrypt=True)

    def to_response(self, record: SecretRecord, *, verify_decrypt: bool = False) -> SecretRecordResponse:
        expires_at = self._expires_at(record.metadata_json)
        health_status, health_reason = self._health(record, expires_at, verify_decrypt=verify_decrypt)
        return SecretRecordResponse.model_validate(record).model_copy(
            update={
                "expires_at": expires_at,
                "health_status": health_status,
                "health_reason": health_reason,
                "health_checked_at": utc_now() if verify_decrypt else None,
            }
        )

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

    def _metadata_with_expiry(
        self,
        existing: dict | None,
        expires_at: datetime | None,
    ) -> dict | None:
        metadata = dict(existing or {})
        if expires_at is not None:
            metadata["expires_at"] = expires_at.isoformat()
        return metadata or None

    def _expires_at(self, metadata: dict | None) -> datetime | None:
        raw_value = (metadata or {}).get("expires_at")
        if not isinstance(raw_value, str) or not raw_value.strip():
            return None
        try:
            expires_at = datetime.fromisoformat(raw_value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if expires_at.tzinfo is None:
            return expires_at.replace(tzinfo=utc_now().tzinfo)
        return expires_at

    def _health(
        self,
        record: SecretRecord,
        expires_at: datetime | None,
        *,
        verify_decrypt: bool,
    ) -> tuple[str, str | None]:
        if record.status != "active":
            return "disabled", "Secret is not active."

        now = utc_now()
        if expires_at is not None and expires_at <= now:
            return "expired", "Secret has expired."

        if verify_decrypt:
            try:
                decrypt_secret(record.ciphertext)
            except BadRequestException as exc:
                return "invalid", str(exc)

        if expires_at is not None and expires_at <= now + timedelta(days=EXPIRING_SOON_DAYS):
            return "expiring_soon", f"Secret expires within {EXPIRING_SOON_DAYS} days."

        return "healthy", None


secret_store_service = SecretStoreService()
