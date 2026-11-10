from functools import lru_cache

from pydantic import PostgresDsn
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration read from environment variables (or a local `.env` file)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: PostgresDsn = PostgresDsn(
        "postgresql+asyncpg://library:library@localhost:5432/library"
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
