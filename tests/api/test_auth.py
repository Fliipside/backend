import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from app.models.user import User
from app.services import auth as auth_service


SIGNUP_PAYLOAD = {
    "email": "User@Example.com",
    "password": "password1234",
    "nickname": "tester",
}


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "auth.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


@pytest.fixture
def client(database_path: Path) -> Iterator[TestClient]:
    settings = Settings(
        postgres_host="",
        postgres_db="",
        postgres_user="",
        postgres_password="",
        redis_url="",
        ai_service_url="",
        jwt_secret_key="test-secret-key-with-enough-length-1234",
    )
    app = create_app(settings)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        poolclass=NullPool,
    )

    with TestClient(app) as test_client:
        app.state.db_sessionmaker = async_sessionmaker(
            engine,
            expire_on_commit=False,
        )
        yield test_client


def signup_and_login(client: TestClient) -> str:
    client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "password1234"},
    )
    return response.json()["data"]["access_token"]


def test_signup_creates_user_with_normalized_email(client: TestClient) -> None:
    response = client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["email"] == "user@example.com"
    assert body["data"]["nickname"] == "tester"
    assert "password" not in str(body["data"])


def test_signup_rejects_duplicate_email(client: TestClient) -> None:
    client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    response = client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_ALREADY_EXISTS"


def test_login_and_get_me(client: TestClient) -> None:
    token = signup_and_login(client)

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["data"]["email"] == "user@example.com"


def test_login_rejects_wrong_password(client: TestClient) -> None:
    client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "wrong-password"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_login_rejects_unknown_email(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "password1234"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_password_work_uses_dedicated_limiter(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[Callable[..., Any]] = []
    original_run_password_operation = auth_service.run_password_operation

    async def recording_run_password_operation(
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        calls.append(func)
        return await original_run_password_operation(func, *args, **kwargs)

    monkeypatch.setattr(
        auth_service,
        "run_password_operation",
        recording_run_password_operation,
    )

    signup_response = client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)
    login_response = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "password1234"},
    )
    unknown_user_response = client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "password1234"},
    )

    assert signup_response.status_code == 201
    assert login_response.status_code == 200
    assert unknown_user_response.status_code == 401
    assert calls.count(auth_service.hash_password) == 1
    assert calls.count(auth_service.verify_password) == 2
    assert auth_service.PASSWORD_HASH_LIMITER.total_tokens == 2


def test_password_operation_passes_dedicated_limiter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received_limiter: list[object] = []

    async def fake_run_sync(
        func: Callable[[], Any],
        *,
        limiter: object,
    ) -> Any:
        received_limiter.append(limiter)
        return func()

    monkeypatch.setattr(auth_service.to_thread, "run_sync", fake_run_sync)

    result = asyncio.run(auth_service.run_password_operation(lambda: "done"))

    assert result == "done"
    assert received_limiter == [auth_service.PASSWORD_HASH_LIMITER]


def test_me_requires_token(client: TestClient) -> None:
    response = client.get("/api/v1/auth/me")

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"
    assert response.headers["WWW-Authenticate"] == "Bearer"


def test_me_rejects_invalid_token(client: TestClient) -> None:
    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not-a-jwt"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_me_rejects_inactive_user(
    client: TestClient,
    database_path: Path,
) -> None:
    token = signup_and_login(client)
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.begin() as connection:
        connection.execute(update(User).values(is_active=False))
    engine.dispose()

    response = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "INACTIVE_USER"
