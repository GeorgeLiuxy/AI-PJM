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

    from app.modules.audit import models as _audit_models
    from app.modules.auth import models as _auth_models
    from app.modules.delivery import models as _delivery_models
    from app.modules.secrets import models as _secret_models

    _ = (_audit_models, _auth_models, _delivery_models, _secret_models)


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
        if is_sqlite_url(settings.database_url):
            await _ensure_sqlite_schema_compat(conn)


async def _ensure_sqlite_schema_compat(conn) -> None:
    """Apply additive SQLite dev-schema fixes for existing local databases."""

    demand_columns = await _sqlite_columns(conn, "delivery_demand_items")
    if "project_id" not in demand_columns:
        await conn.exec_driver_sql("ALTER TABLE delivery_demand_items ADD COLUMN project_id INTEGER")
    if "created_by_user_id" not in demand_columns:
        await conn.exec_driver_sql("ALTER TABLE delivery_demand_items ADD COLUMN created_by_user_id INTEGER")
    if "manual_approval_status" not in demand_columns:
        await conn.exec_driver_sql("ALTER TABLE delivery_demand_items ADD COLUMN manual_approval_status VARCHAR(50)")
    if "manual_approval_user_id" not in demand_columns:
        await conn.exec_driver_sql("ALTER TABLE delivery_demand_items ADD COLUMN manual_approval_user_id INTEGER")
    if "manual_approval_ref" not in demand_columns:
        await conn.exec_driver_sql("ALTER TABLE delivery_demand_items ADD COLUMN manual_approval_ref VARCHAR(200)")
    if "manual_approval_note" not in demand_columns:
        await conn.exec_driver_sql("ALTER TABLE delivery_demand_items ADD COLUMN manual_approval_note TEXT")
    if "manual_approval_at" not in demand_columns:
        await conn.exec_driver_sql("ALTER TABLE delivery_demand_items ADD COLUMN manual_approval_at DATETIME")
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_demand_items_project_id "
        "ON delivery_demand_items (project_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_demand_items_created_by_user_id "
        "ON delivery_demand_items (created_by_user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_demand_items_manual_approval_user_id "
        "ON delivery_demand_items (manual_approval_user_id)"
    )
    await conn.exec_driver_sql(
        "CREATE INDEX IF NOT EXISTS ix_delivery_demand_items_manual_approval_status "
        "ON delivery_demand_items (manual_approval_status)"
    )

    merge_request_columns = await _sqlite_columns(conn, "delivery_merge_request_records")
    if merge_request_columns:
        if "created_by_user_id" not in merge_request_columns:
            await conn.exec_driver_sql("ALTER TABLE delivery_merge_request_records ADD COLUMN created_by_user_id INTEGER")
        if "created_by_ref" not in merge_request_columns:
            await conn.exec_driver_sql("ALTER TABLE delivery_merge_request_records ADD COLUMN created_by_ref VARCHAR(200)")
        if "reviewed_by_user_id" not in merge_request_columns:
            await conn.exec_driver_sql("ALTER TABLE delivery_merge_request_records ADD COLUMN reviewed_by_user_id INTEGER")
        if "reviewed_by_ref" not in merge_request_columns:
            await conn.exec_driver_sql("ALTER TABLE delivery_merge_request_records ADD COLUMN reviewed_by_ref VARCHAR(200)")
        if "reviewed_at" not in merge_request_columns:
            await conn.exec_driver_sql("ALTER TABLE delivery_merge_request_records ADD COLUMN reviewed_at DATETIME")
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_delivery_merge_request_records_created_by_user_id "
            "ON delivery_merge_request_records (created_by_user_id)"
        )
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_delivery_merge_request_records_reviewed_by_user_id "
            "ON delivery_merge_request_records (reviewed_by_user_id)"
        )

    deploy_columns = await _sqlite_columns(conn, "delivery_deploy_records")
    if deploy_columns:
        if "created_by_user_id" not in deploy_columns:
            await conn.exec_driver_sql("ALTER TABLE delivery_deploy_records ADD COLUMN created_by_user_id INTEGER")
        if "created_by_ref" not in deploy_columns:
            await conn.exec_driver_sql("ALTER TABLE delivery_deploy_records ADD COLUMN created_by_ref VARCHAR(200)")
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_delivery_deploy_records_created_by_user_id "
            "ON delivery_deploy_records (created_by_user_id)"
        )

    verification_columns = await _sqlite_columns(conn, "delivery_verification_records")
    if verification_columns and "verifier_user_id" not in verification_columns:
        await conn.exec_driver_sql("ALTER TABLE delivery_verification_records ADD COLUMN verifier_user_id INTEGER")
        await conn.exec_driver_sql(
            "CREATE INDEX IF NOT EXISTS ix_delivery_verification_records_verifier_user_id "
            "ON delivery_verification_records (verifier_user_id)"
        )


async def _sqlite_columns(conn, table_name: str) -> set[str]:
    result = await conn.exec_driver_sql(f"PRAGMA table_info({table_name})")
    return {row[1] for row in result.fetchall()}


def _alembic_config():
    from alembic.config import Config

    backend_root = Path(__file__).resolve().parents[2]
    config = Config(str(backend_root / "alembic.ini"))
    config.set_main_option("script_location", str(backend_root / "migrations"))
    config.set_main_option("version_locations", str(backend_root / "migrations" / "versions"))
    return config


async def assert_database_current() -> None:
    """Fail fast when a non-SQLite database is not migrated to Alembic head."""

    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    import_all_models()
    config = _alembic_config()
    script = ScriptDirectory.from_config(config)
    expected_heads = set(script.get_heads())

    async with engine.connect() as conn:
        current_heads = await conn.run_sync(
            lambda sync_conn: set(MigrationContext.configure(sync_conn).get_current_heads())
        )

    if current_heads != expected_heads:
        current = ", ".join(sorted(current_heads)) or "<empty>"
        expected = ", ".join(sorted(expected_heads)) or "<empty>"
        raise RuntimeError(
            "Database schema is not migrated to Alembic head. "
            f"Current heads: {current}; expected heads: {expected}. "
            "Run `python scripts/migrate.py upgrade head` from backend/ before starting production."
        )


def utc_now() -> datetime:
    """Get current UTC timestamp"""
    return datetime.now(timezone.utc)
