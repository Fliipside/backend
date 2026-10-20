from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Flipside API"
    api_v1_prefix: str = "/api/v1"
    database_url: str = ""
    redis_url: str = ""
    ai_service_url: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
