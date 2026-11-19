import asyncio
import re
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.errors import EmailSendError
from app.db.base import Base
from app.main import create_app
from app.models.email_log import EmailLog
from app.models.user import User
from app.services import auth as auth_service
from tests.conftest import FakeEmailSender, mark_email_verified


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
def email_sender() -> FakeEmailSender:
    return FakeEmailSender()


@pytest.fixture
def client(
    database_path: Path,
    email_sender: FakeEmailSender,
) -> Iterator[TestClient]:
    """The default signup address starts out verified. Other addresses do not."""
    settings = Settings(
        postgres_host="",
        postgres_db="",
        postgres_user="",
        postgres_password="",
        redis_url="",
        ai_service_url="",
        jwt_secret_key="test-secret-key-with-enough-length-1234",
        smtp_host="",
        smtp_username="",
        smtp_password="",
        smtp_from_email="",
        email_code_expire_seconds=600,
        email_code_resend_cooldown_seconds=60,
        email_code_max_attempts=5,
        email_verified_expire_seconds=1800,
        email_recipient_daily_limit=3,
        email_daily_send_limit=5,
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
        app.state.redis_client = fakeredis.aioredis.FakeRedis(decode_responses=True)
        app.state.email_sender = email_sender
        mark_email_verified(test_client, SIGNUP_PAYLOAD["email"])
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


VERIFY_REQUEST = "/api/v1/auth/email-verification/request"
VERIFY_CONFIRM = "/api/v1/auth/email-verification/confirm"
RESET_REQUEST = "/api/v1/auth/password-reset/request"
RESET_CONFIRM = "/api/v1/auth/password-reset/confirm"
NEW_EMAIL = "new@example.com"


def sent_code(email_sender: FakeEmailSender) -> str:
    return re.search(r"인증번호: (\d{6})", email_sender.sent[-1]["text"]).group(1)


def wrong_code(code: str) -> str:
    return f"{(int(code) + 1) % 1_000_000:06d}"


def skip_cooldown(client: TestClient) -> None:
    async def clear() -> None:
        redis = client.app.state.redis_client
        keys = await redis.keys("email:cooldown:*")
        if keys:
            await redis.delete(*keys)

    client.portal.call(clear)


def email_logs(database_path: Path) -> list[EmailLog]:
    engine = create_engine(f"sqlite:///{database_path}")
    with engine.connect() as connection:
        rows = list(connection.execute(select(EmailLog)).mappings())
    engine.dispose()
    return rows


def test_signup_requires_verified_email(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/signup",
        json={**SIGNUP_PAYLOAD, "email": NEW_EMAIL},
    )

    assert response.status_code == 403
    assert response.json()["code"] == "EMAIL_NOT_VERIFIED"


def test_email_verification_flow_allows_signup_once(
    client: TestClient,
    email_sender: FakeEmailSender,
    database_path: Path,
) -> None:
    request_response = client.post(VERIFY_REQUEST, json={"email": "New@Example.com"})

    assert request_response.status_code == 200
    assert request_response.json()["data"] == {"expires_in": 600, "resend_after": 60}
    assert email_sender.sent[-1]["to"] == NEW_EMAIL
    logs = email_logs(database_path)
    assert [(log["recipient"], log["purpose"], log["status"]) for log in logs] == [
        (NEW_EMAIL, "signup_verification", "sent")
    ]
    assert logs[0]["sent_at"] is not None

    code = sent_code(email_sender)
    confirm_response = client.post(VERIFY_CONFIRM, json={"email": NEW_EMAIL, "code": code})

    assert confirm_response.status_code == 200
    assert confirm_response.json()["data"] == {"email": NEW_EMAIL, "expires_in": 1800}

    reused = client.post(VERIFY_CONFIRM, json={"email": NEW_EMAIL, "code": code})
    assert reused.status_code == 400

    payload = {**SIGNUP_PAYLOAD, "email": NEW_EMAIL}
    assert client.post("/api/v1/auth/signup", json=payload).status_code == 201
    assert client.post("/api/v1/auth/signup", json=payload).status_code == 409


def test_email_verification_request_rejects_registered_email(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    response = client.post(VERIFY_REQUEST, json={"email": "user@example.com"})

    assert response.status_code == 409
    assert response.json()["code"] == "EMAIL_ALREADY_EXISTS"
    assert email_sender.sent == []


def test_email_verification_request_has_resend_cooldown(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL})

    response = client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL})

    assert response.status_code == 429
    assert response.json()["code"] == "EMAIL_RESEND_COOLDOWN"
    assert 1 <= int(response.headers["Retry-After"]) <= 60
    assert len(email_sender.sent) == 1


def test_email_verification_request_limits_one_recipient_per_day(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    for _ in range(3):
        assert client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL}).status_code == 200
        skip_cooldown(client)

    response = client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL})

    assert response.status_code == 429
    assert response.json()["code"] == "EMAIL_RECIPIENT_LIMIT_EXCEEDED"
    assert len(email_sender.sent) == 3


def test_email_verification_request_stops_at_daily_total(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    for index in range(5):
        response = client.post(VERIFY_REQUEST, json={"email": f"user{index}@example.com"})
        assert response.status_code == 200

    response = client.post(VERIFY_REQUEST, json={"email": "user5@example.com"})

    assert response.status_code == 503
    assert response.json()["code"] == "EMAIL_DAILY_LIMIT_EXCEEDED"
    assert len(email_sender.sent) == 5


def test_email_verification_confirm_rejects_wrong_code(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL})
    code = sent_code(email_sender)

    response = client.post(
        VERIFY_CONFIRM,
        json={"email": NEW_EMAIL, "code": wrong_code(code)},
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_EMAIL_CODE"
    assert client.post(VERIFY_CONFIRM, json={"email": NEW_EMAIL, "code": code}).status_code == 200


def test_email_verification_confirm_discards_code_after_too_many_attempts(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL})
    code = sent_code(email_sender)
    wrong = {"email": NEW_EMAIL, "code": wrong_code(code)}

    for _ in range(5):
        assert client.post(VERIFY_CONFIRM, json=wrong).status_code == 400
    exceeded = client.post(VERIFY_CONFIRM, json=wrong)

    assert exceeded.status_code == 429
    assert exceeded.json()["code"] == "EMAIL_CODE_ATTEMPTS_EXCEEDED"
    after = client.post(VERIFY_CONFIRM, json={"email": NEW_EMAIL, "code": code})
    assert after.status_code == 400


def test_email_verification_confirm_rejects_malformed_code(client: TestClient) -> None:
    response = client.post(VERIFY_CONFIRM, json={"email": NEW_EMAIL, "code": "12345a"})

    assert response.status_code == 422


def test_failed_send_is_recorded_in_email_logs(
    client: TestClient,
    email_sender: FakeEmailSender,
    database_path: Path,
) -> None:
    email_sender.error = EmailSendError("535 bad credentials")

    response = client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL})

    assert response.status_code == 200
    logs = email_logs(database_path)
    assert [(log["status"], log["error"]) for log in logs] == [
        ("failed", "535 bad credentials")
    ]
    assert logs[0]["sent_at"] is None


def test_password_reset_flow_changes_password(
    client: TestClient,
    email_sender: FakeEmailSender,
    database_path: Path,
) -> None:
    client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    request_response = client.post(RESET_REQUEST, json={"email": "User@Example.com"})

    assert request_response.status_code == 200
    assert email_sender.sent[-1]["to"] == "user@example.com"
    assert "비밀번호 재설정" in email_sender.sent[-1]["subject"]
    assert email_logs(database_path)[0]["purpose"] == "password_reset"

    code = sent_code(email_sender)
    confirm_response = client.post(
        RESET_CONFIRM,
        json={"email": "user@example.com", "code": code, "new_password": "new-password-5678"},
    )

    assert confirm_response.status_code == 200
    assert confirm_response.json()["data"] is None
    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "password1234"},
    )
    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "new-password-5678"},
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200

    reused = client.post(
        RESET_CONFIRM,
        json={"email": "user@example.com", "code": code, "new_password": "another-password-1"},
    )
    assert reused.status_code == 400


def test_password_reset_request_answers_the_same_for_unknown_email(
    client: TestClient,
    email_sender: FakeEmailSender,
    database_path: Path,
) -> None:
    client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)

    known = client.post(RESET_REQUEST, json={"email": "user@example.com"})
    unknown = client.post(RESET_REQUEST, json={"email": "nobody@example.com"})

    assert unknown.status_code == known.status_code == 200
    assert unknown.json() == known.json()
    assert [mail["to"] for mail in email_sender.sent] == ["user@example.com"]
    assert len(email_logs(database_path)) == 1

    known_again = client.post(RESET_REQUEST, json={"email": "user@example.com"})
    unknown_again = client.post(RESET_REQUEST, json={"email": "nobody@example.com"})
    assert unknown_again.status_code == known_again.status_code == 429
    assert unknown_again.json() == known_again.json()


def test_password_reset_confirm_rejects_wrong_code(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)
    client.post(RESET_REQUEST, json={"email": "user@example.com"})
    code = sent_code(email_sender)

    response = client.post(
        RESET_CONFIRM,
        json={
            "email": "user@example.com",
            "code": wrong_code(code),
            "new_password": "new-password-5678",
        },
    )

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_EMAIL_CODE"
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "user@example.com", "password": "password1234"},
    )
    assert login.status_code == 200


def test_signup_code_cannot_reset_password(
    client: TestClient,
    email_sender: FakeEmailSender,
) -> None:
    client.post("/api/v1/auth/signup", json=SIGNUP_PAYLOAD)
    client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL})
    code = sent_code(email_sender)

    response = client.post(
        RESET_CONFIRM,
        json={"email": NEW_EMAIL, "code": code, "new_password": "new-password-5678"},
    )

    assert response.status_code == 400


def test_email_endpoints_return_503_without_email_sender(client: TestClient) -> None:
    client.app.state.email_sender = None

    response = client.post(VERIFY_REQUEST, json={"email": NEW_EMAIL})

    assert response.status_code == 503
