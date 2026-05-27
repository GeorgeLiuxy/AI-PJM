"""Secret store data access."""

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.secrets.models import SecretRecord


class SecretRepository:
    """Repository for encrypted secrets."""

    async def create_secret(
        self,
        db: AsyncSession,
        *,
        project_id: int,
        name: str,
        provider: str,
        ciphertext: str,
        value_hash: str,
        value_mask: str,
        key_id: str,
        description: str | None = None,
        created_by_user_id: int | None = None,
        metadata: dict | None = None,
    ) -> SecretRecord:
        record = SecretRecord(
            project_id=project_id,
            name=name,
            provider=provider,
            description=description,
            key_id=key_id,
            ciphertext=ciphertext,
            value_hash=value_hash,
            value_mask=value_mask,
            created_by_user_id=created_by_user_id,
            updated_by_user_id=created_by_user_id,
            metadata_json=metadata,
        )
        db.add(record)
        await db.flush()
        return record

    async def list_secrets(
        self,
        db: AsyncSession,
        *,
        project_ids: list[int] | None = None,
        project_id: int | None = None,
        provider: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SecretRecord]:
        query = select(SecretRecord).order_by(SecretRecord.updated_at.desc(), SecretRecord.id.desc())
        if project_ids is not None:
            if not project_ids:
                return []
            query = query.where(SecretRecord.project_id.in_(project_ids))
        if project_id is not None:
            query = query.where(SecretRecord.project_id == project_id)
        if provider:
            query = query.where(SecretRecord.provider == provider)
        result = await db.execute(query.offset(offset).limit(limit))
        return list(result.scalars().all())

    async def get_secret(self, db: AsyncSession, secret_id: int) -> Optional[SecretRecord]:
        result = await db.execute(select(SecretRecord).where(SecretRecord.id == secret_id))
        return result.scalar_one_or_none()

    async def get_secret_by_name(
        self,
        db: AsyncSession,
        *,
        project_id: int,
        name: str,
    ) -> Optional[SecretRecord]:
        result = await db.execute(
            select(SecretRecord).where(
                SecretRecord.project_id == project_id,
                SecretRecord.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def update_secret(self, db: AsyncSession, record: SecretRecord, **values) -> SecretRecord:
        for key, value in values.items():
            setattr(record, key, value)
        await db.flush()
        return record


secret_repository = SecretRepository()
