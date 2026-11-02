from functools import lru_cache
from typing import Self

from dotenv import find_dotenv, load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr, field_validator, model_validator
from sqlalchemy import URL


def load_environment() -> None:
    env_file = find_dotenv(usecwd=True)
    if env_file:
        load_dotenv(env_file, override=False)


load_environment()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    app_name: str = "Flipside API"
    api_v1_prefix: str = "/api/v1"
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_db: str = ""
    postgres_user: str = ""
    postgres_password: SecretStr = SecretStr("")
    redis_url: str = ""
    ai_service_url: str = ""
    ai_service_timeout_seconds: float = Field(default=30.0, gt=0)
    jwt_secret_key: SecretStr = SecretStr("")
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = Field(default=60, gt=0)

    @field_validator("jwt_secret_key")
    @classmethod
    def validate_jwt_secret_key(cls, secret_key: SecretStr) -> SecretStr:
        value = secret_key.get_secret_value()
        if value and len(value.encode("utf-8")) < 32:
            raise ValueError("JWT_SECRET_KEY must be at least 32 bytes")
        return secret_key

    @model_validator(mode="after")
    def validate_postgres_settings(self) -> Self:
        values = {
            "POSTGRES_HOST": self.postgres_host,
            "POSTGRES_DB": self.postgres_db,
            "POSTGRES_USER": self.postgres_user,
            "POSTGRES_PASSWORD": self.postgres_password.get_secret_value(),
        }

        if any(values.values()) and not all(values.values()):
            missing = [name for name, value in values.items() if not value]
            raise ValueError(
                f"Incomplete PostgreSQL configuration: {', '.join(missing)}"
            )
        return self

    @property
    def database_url(self) -> URL | None:
        password = self.postgres_password.get_secret_value()

        if not any(
            (
                self.postgres_host,
                self.postgres_db,
                self.postgres_user,
                password,
            )
        ):
            return None

        return URL.create(
            drivername="postgresql+asyncpg",
            username=self.postgres_user,
            password=password,
            host=self.postgres_host,
            port=self.postgres_port,
            database=self.postgres_db,
        )

@lru_cache
def get_settings() -> Settings:
    return Settings()
