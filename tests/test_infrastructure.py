from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import get_session
from app.main import app


@pytest.fixture
async def client_without_database() -> AsyncIterator[AsyncClient]:
    """The API wired to a database address that refuses connections."""
    engine = create_async_engine("postgresql+asyncpg://nobody:nothing@127.0.0.1:1/none")
    sessions = async_sessionmaker(engine)

    async def session_override() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    app.dependency_overrides[get_session] = session_override
    # raise_app_exceptions=False: return the 500 response like a real server would.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    app.dependency_overrides.clear()
    await engine.dispose()


async def test_health(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_health_reports_unreachable_database(client_without_database: AsyncClient) -> None:
    response = await client_without_database.get("/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "Database unavailable."}


async def test_unexpected_errors_return_json(client_without_database: AsyncClient) -> None:
    response = await client_without_database.get("/books")
    assert response.status_code == 500
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"detail": "Internal server error."}


def test_migrations_roundtrip_and_match_models(database_url: str, alembic_config: Config) -> None:
    """Downgrade and upgrade cleanly, and the models have no changes missing a migration."""
    command.downgrade(alembic_config, "base")
    command.upgrade(alembic_config, "head")
    command.check(alembic_config)


async def test_openapi_documents_error_responses(client: AsyncClient) -> None:
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert set(paths["/books/{serial_number}"]["patch"]["responses"]) == {
        "200",
        "404",
        "409",
        "422",
    }
    assert set(paths["/books/{serial_number}"]["delete"]["responses"]) == {
        "204",
        "404",
        "409",
        "422",
    }
