from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "chagok-chagok-api"
    env: str = "local"
    api_v1_prefix: str = "/api/v1"

    database_url: str = "postgresql+asyncpg://chagok:chagok@localhost:5432/chagok"
    database_url_sync: str = "postgresql+psycopg2://chagok:chagok@localhost:5432/chagok"

    secret_key: str = "change-me"


@lru_cache
def get_settings() -> Settings:
    return Settings()
