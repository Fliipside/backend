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
