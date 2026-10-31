from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings
from app.core.errors import AuthenticationError, AuthNotConfiguredError


password_hash = PasswordHash.recommended()

# 존재하지 않는 이메일로 로그인할 때도 해시 검증 시간을 맞추기 위한 값
DUMMY_PASSWORD_HASH = password_hash.hash("dummy-password")


def hash_password(password: str) -> str:
    return password_hash.hash(password)


def verify_password(password: str, hashed_password: str) -> bool:
    return password_hash.verify(password, hashed_password)


def get_jwt_secret_key(settings: Settings) -> str:
    secret_key = settings.jwt_secret_key.get_secret_value()
    if not secret_key:
        raise AuthNotConfiguredError
    return secret_key


def create_access_token(user_id: UUID, settings: Settings) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    return jwt.encode(
        payload,
        get_jwt_secret_key(settings),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str, settings: Settings) -> UUID:
    try:
        payload = jwt.decode(
            token,
            get_jwt_secret_key(settings),
            algorithms=[settings.jwt_algorithm],
            options={"require": ["sub", "exp", "type"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("토큰이 만료되었습니다.") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("유효하지 않은 토큰입니다.") from exc

    if payload["type"] != "access":
        raise AuthenticationError("유효하지 않은 토큰입니다.")

    try:
        return UUID(payload["sub"])
    except ValueError as exc:
        raise AuthenticationError("유효하지 않은 토큰입니다.") from exc
