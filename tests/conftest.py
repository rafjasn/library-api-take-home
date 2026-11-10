from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from testcontainers.community.postgres import PostgresContainer

from app.db import get_session
from app.main import app

ROOT = Path(__file__).resolve().parent.parent
POSTGRES_IMAGE = "postgres:18-alpine"  # same as docker-compose.yml


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    with PostgresContainer(POSTGRES_IMAGE, driver="asyncpg") as postgres:
        yield postgres.get_connection_url()


@pytest.fixture(scope="session")
def alembic_config(postgres_url: str) -> Config:
    config = Config(ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres_url)
    return config


@pytest.fixture(scope="session")
def database_url(postgres_url: str, alembic_config: Config) -> str:
    """The test database, with the schema created by the real migrations."""
    command.upgrade(alembic_config, "head")
    return postgres_url


@pytest.fixture
async def engine(database_url: str) -> AsyncIterator[AsyncEngine]:
    engine = create_async_engine(database_url)
    yield engine
    async with engine.begin() as connection:
        await connection.execute(text("TRUNCATE books, loans RESTART IDENTITY"))
    await engine.dispose()


@pytest.fixture
async def client(engine: AsyncEngine) -> AsyncIterator[AsyncClient]:
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
