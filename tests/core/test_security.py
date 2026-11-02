from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
import pytest

from app.core.config import Settings
from app.core.errors import AuthenticationError, AuthNotConfiguredError
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


SECRET_KEY = "test-secret-key-with-enough-length-1234"


def make_settings(**overrides: object) -> Settings:
    return Settings(jwt_secret_key=SECRET_KEY, **overrides)


def test_hash_password_verifies_original_password() -> None:
    hashed = hash_password("correct-password")

    assert hashed != "correct-password"
    assert verify_password("correct-password", hashed)
    assert not verify_password("wrong-password", hashed)


def test_access_token_round_trip() -> None:
    settings = make_settings()
    user_id = uuid4()

    token = create_access_token(user_id, settings)

    assert decode_access_token(token, settings) == user_id


def test_decode_rejects_expired_token() -> None:
    settings = make_settings()
    expired_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    token = jwt.encode(
        {"sub": str(uuid4()), "type": "access", "exp": expired_at},
        SECRET_KEY,
        algorithm="HS256",
    )

    with pytest.raises(AuthenticationError) as exc_info:
        decode_access_token(token, settings)

    assert exc_info.value.message == "토큰이 만료되었습니다."


def test_decode_rejects_token_signed_with_other_key() -> None:
    token = create_access_token(
        uuid4(),
        Settings(jwt_secret_key="other-secret-key-with-enough-length-5678"),
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(token, make_settings())


def test_decode_rejects_non_access_token() -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=1)
    token = jwt.encode(
        {"sub": str(uuid4()), "type": "refresh", "exp": expires_at},
        SECRET_KEY,
        algorithm="HS256",
    )

    with pytest.raises(AuthenticationError):
        decode_access_token(token, make_settings())


def test_create_token_requires_secret_key() -> None:
    with pytest.raises(AuthNotConfiguredError):
        create_access_token(uuid4(), Settings(jwt_secret_key=""))
