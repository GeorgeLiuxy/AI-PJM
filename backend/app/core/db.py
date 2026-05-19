"""Database connection and session management"""

from datetime import datetime, timezone
from pathlib import Path
from typing import AsyncGenerator
from sqlalchemy import BigInteger, Integer, JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


DB_BIGINT = BigInteger().with_variant(Integer, "sqlite")
DB_JSON = JSON().with_variant(JSONB, "postgresql")


def is_sqlite_url(database_url: str) -> bool:
    """Return whether a database URL points at SQLite."""

    return database_url.startswith("sqlite")


def _ensure_sqlite_parent_dir(database_url: str) -> None:
    if not is_sqlite_url(database_url) or ":memory:" in database_url:
        return
    if ":///" not in database_url:
        return
    raw_path = database_url.split(":///", 1)[1].split("?", 1)[0]
    if not raw_path:
        return
    Path(raw_path).expanduser().parent.mkdir(parents=True, exist_ok=True)


_ensure_sqlite_parent_dir(settings.database_url)

# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.database_echo,
    future=True,
)

# Create async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models"""
    pass


def import_all_models() -> None:
    """Import all SQLAlchemy models so metadata is complete."""

    from app.modules.delivery import models as _delivery_models

    _ = (_delivery_models,)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency function that yields database sessions.

    Usage in FastAPI:
        @app.get("/demands")
        async def get_demands(db: AsyncSession = Depends(get_db)):
            ...
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Initialize database - create all tables (for development only)"""
    import_all_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def utc_now() -> datetime:
    """Get current UTC timestamp"""
    return datetime.now(timezone.utc)
