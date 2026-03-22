"""Pytest configuration and fixtures"""

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.main import app
from app.core.db import Base, get_db

# Import all models so SQLAlchemy can discover them
from app.modules.item.models import Item, ItemSuggestion
from app.modules.analysis.models import Analysis
from app.modules.output.models import Output
from app.modules.audit.models import ActionLog


# Test database URL (use a separate test database)
TEST_DATABASE_URL = "postgresql+asyncpg://ai_pjm_user:ai_pjm_password@localhost:5432/ai_pjm_test"


@pytest.fixture(scope="function")
async def db_engine():
    """Create a test database engine for each test function"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)

    # Create tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield engine

    # Drop tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(db_engine):
    """Create a test database session for each test"""
    TestSessionLocal = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    async with TestSessionLocal() as session:
        yield session


@pytest.fixture(scope="function")
async def client(db_session: AsyncSession):
    """Create a test client with database session override"""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(scope="function")
async def async_client():
    """Create a test client without database override"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac
