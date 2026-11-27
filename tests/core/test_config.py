import os
from pathlib import Path

import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from app.core.config import load_environment, Settings


VALID_JWT_SECRET_KEY = "test-secret-key-with-enough-length-1234"


def test_load_environment_finds_parent_env_file(
    tmp_path: Path, monkeypatch: MonkeyPatch
) -> None:
    nested_directory = tmp_path / "worktree" / "project"
    nested_directory.mkdir(parents=True)
    (tmp_path / ".env").write_text("FLIPSIDE_TEST_SETTING=loaded\n", encoding="utf-8")
    monkeypatch.chdir(nested_directory)
    monkeypatch.delenv("FLIPSIDE_TEST_SETTING", raising=False)

    load_environment()

    assert os.environ["FLIPSIDE_TEST_SETTING"] == "loaded"


def test_settings_build_database_url() -> None:
    settings = Settings(
        postgres_host="db.example.com",
        postgres_port=5432,
        postgres_db="flipside",
        postgres_user="test_user",
        postgres_password="p@ss:/word",
        jwt_secret_key=VALID_JWT_SECRET_KEY,
    )

    database_url = settings.database_url

    assert database_url is not None
    assert database_url.drivername == "postgresql+asyncpg"
    assert database_url.host == "db.example.com"
    assert database_url.port == 5432
    assert database_url.database == "flipside"
    assert database_url.username == "test_user"
    assert database_url.password == "p@ss:/word"


def test_settings_rejects_short_jwt_secret_key() -> None:
    with pytest.raises(ValidationError, match="at least 32 bytes"):
        Settings(jwt_secret_key="a" * 31)


def test_settings_allows_unconfigured_jwt_secret_key() -> None:
    settings = Settings(jwt_secret_key="")

    assert settings.jwt_secret_key.get_secret_value() == ""


def test_settings_rejects_partial_smtp_configuration() -> None:
    with pytest.raises(ValidationError, match="SMTP_PASSWORD, SMTP_FROM_EMAIL"):
        Settings(
            smtp_host="smtp.example.com",
            smtp_username="sender@example.com",
            smtp_password="",
            smtp_from_email="",
        )


def test_settings_smtp_configured_only_when_host_is_set() -> None:
    unconfigured = Settings(
        smtp_host="",
        smtp_username="",
        smtp_password="",
        smtp_from_email="",
    )
    assert unconfigured.smtp_configured is False

    settings = Settings(
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_username="sender@example.com",
        smtp_password="app-password",
        smtp_from_email="sender@example.com",
    )

    assert settings.smtp_configured is True
    assert settings.smtp_port == 587


def test_settings_ai_memory_timeout_defaults(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.delenv("AI_EXTRACT_TIMEOUT_SECONDS", raising=False)
    monkeypatch.delenv("AI_ASK_TIMEOUT_SECONDS", raising=False)

    settings = Settings()

    assert settings.ai_extract_timeout_seconds == 540.0
    assert settings.ai_ask_timeout_seconds == 300.0


LIVEKIT_SECRET = "test-livekit-secret-with-enough-length-1234"


def test_settings_rejects_partial_livekit_configuration() -> None:
    with pytest.raises(ValidationError, match="LIVEKIT_URL, LIVEKIT_API_SECRET"):
        Settings(
            livekit_url="",
            livekit_api_key="APItestkey",
            livekit_api_secret="",
        )


def test_settings_rejects_short_livekit_api_secret() -> None:
    with pytest.raises(ValidationError, match="LIVEKIT_API_SECRET must be at least"):
        Settings(
            livekit_url="wss://livekit.example.com",
            livekit_api_key="APItestkey",
            livekit_api_secret="a" * 31,
        )


def test_settings_livekit_configured_only_when_all_values_are_set() -> None:
    unconfigured = Settings(
        livekit_url="",
        livekit_api_key="",
        livekit_api_secret="",
    )
    assert unconfigured.livekit_configured is False

    settings = Settings(
        livekit_url="wss://livekit.example.com",
        livekit_api_key="APItestkey",
        livekit_api_secret=LIVEKIT_SECRET,
    )

    assert settings.livekit_configured is True
    assert settings.livekit_token_expire_seconds == 600
