from collections.abc import Iterator
from pathlib import Path

import fakeredis
import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.db.base import Base
from app.main import create_app
from tests.conftest import mark_email_verified


LIVEKIT_URL = "wss://livekit.example.com"
LIVEKIT_API_KEY = "APItestkey"
LIVEKIT_API_SECRET = "test-livekit-secret-with-enough-length-1234"
TOKEN_URL = "/api/v1/livekit/token"


@pytest.fixture
def sessionmaker(tmp_path: Path) -> async_sessionmaker:
    path = tmp_path / "livekit.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return async_sessionmaker(
        create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool),
        expire_on_commit=False,
    )


def make_client(
    sessionmaker: async_sessionmaker,
    **livekit: str | int,
) -> Iterator[TestClient]:
    values: dict[str, str | int] = {
        "livekit_url": LIVEKIT_URL,
        "livekit_api_key": LIVEKIT_API_KEY,
        "livekit_api_secret": LIVEKIT_API_SECRET,
        "livekit_token_expire_seconds": 600,
        **livekit,
    }
    settings = Settings(
        postgres_host="",
        postgres_db="",
        postgres_user="",
        postgres_password="",
        redis_url="",
        ai_service_url="",
        jwt_secret_key="test-secret-key-with-enough-length-1234",
        **values,
    )
    app = create_app(settings)

    with TestClient(app) as test_client:
        app.state.db_sessionmaker = sessionmaker
        app.state.redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        yield test_client


@pytest.fixture
def client(sessionmaker: async_sessionmaker) -> Iterator[TestClient]:
    yield from make_client(sessionmaker)


@pytest.fixture
def unconfigured_client(sessionmaker: async_sessionmaker) -> Iterator[TestClient]:
    yield from make_client(
        sessionmaker,
        livekit_url="",
        livekit_api_key="",
        livekit_api_secret="",
    )


def auth_header(client: TestClient, email: str = "user@example.com") -> dict[str, str]:
    mark_email_verified(client, email)
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "password1234",
            "nickname": "tester",
            "company": "Flipside",
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password1234"},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def decode(token: str) -> dict:
    return jwt.decode(token, LIVEKIT_API_SECRET, algorithms=["HS256"])


def test_issue_token_returns_room_token_for_current_user(client: TestClient) -> None:
    headers = auth_header(client)

    response = client.post(TOKEN_URL, headers=headers, json={"room_name": "room-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["code"] == "SUCCESS"
    data = body["data"]
    me = client.get("/api/v1/auth/me", headers=headers).json()["data"]
    assert data["url"] == LIVEKIT_URL
    assert data["room_name"] == "room-1"
    assert data["identity"] == me["id"]
    assert data["expires_in"] == 600

    claims = decode(data["token"])
    assert claims["iss"] == LIVEKIT_API_KEY
    assert claims["sub"] == me["id"]
    assert claims["name"] == "tester"
    assert claims["exp"] - claims["nbf"] == 600
    assert claims["video"] == {
        "room": "room-1",
        "roomJoin": True,
        "canPublish": True,
        "canSubscribe": True,
        "canPublishData": True,
    }


def test_issue_token_is_not_signed_with_the_login_secret(client: TestClient) -> None:
    response = client.post(
        TOKEN_URL,
        headers=auth_header(client),
        json={"room_name": "room-1"},
    )

    with pytest.raises(jwt.InvalidSignatureError):
        jwt.decode(
            response.json()["data"]["token"],
            "test-secret-key-with-enough-length-1234",
            algorithms=["HS256"],
        )


def test_issue_token_gives_each_user_their_own_identity(client: TestClient) -> None:
    first = client.post(
        TOKEN_URL,
        headers=auth_header(client, "a@example.com"),
        json={"room_name": "shared"},
    ).json()["data"]
    second = client.post(
        TOKEN_URL,
        headers=auth_header(client, "b@example.com"),
        json={"room_name": "shared"},
    ).json()["data"]

    assert first["identity"] != second["identity"]
    assert decode(first["token"])["video"]["room"] == "shared"
    assert decode(second["token"])["video"]["room"] == "shared"


def test_issue_token_strips_room_name_whitespace(client: TestClient) -> None:
    response = client.post(
        TOKEN_URL,
        headers=auth_header(client),
        json={"room_name": "  room-1 "},
    )

    assert response.status_code == 200
    assert response.json()["data"]["room_name"] == "room-1"


def test_issue_token_requires_login(client: TestClient) -> None:
    response = client.post(TOKEN_URL, json={"room_name": "room-1"})

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_issue_token_rejects_invalid_access_token(client: TestClient) -> None:
    response = client.post(
        TOKEN_URL,
        headers={"Authorization": "Bearer not-a-token"},
        json={"room_name": "room-1"},
    )

    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"room_name": ""},
        {"room_name": "   "},
        {"room_name": "room 1"},
        {"room_name": "방"},
        {"room_name": "room/1"},
        {"room_name": "a" * 129},
        {"room_name": 1},
    ],
)
def test_issue_token_rejects_invalid_room_name(
    client: TestClient,
    payload: dict,
) -> None:
    response = client.post(TOKEN_URL, headers=auth_header(client), json=payload)

    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_REQUEST"


def test_issue_token_returns_503_when_livekit_is_not_configured(
    unconfigured_client: TestClient,
) -> None:
    response = unconfigured_client.post(
        TOKEN_URL,
        headers=auth_header(unconfigured_client),
        json={"room_name": "room-1"},
    )

    assert response.status_code == 503
    body = response.json()
    assert body["code"] == "SERVICE_UNAVAILABLE"
    assert body["message"] == "LiveKit is not configured"
    assert body["data"] is None
