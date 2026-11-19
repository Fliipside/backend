from collections.abc import Callable
from functools import partial
from typing import ParamSpec, TypeVar

from anyio import CapacityLimiter, to_thread
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    InactiveUserError,
    InvalidCredentialsError,
    InvalidEmailCodeError,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories import user as user_repository
from app.schemas.auth import (
    EmailCodeConfirmRequest,
    EmailCodeRequest,
    LoginRequest,
    PasswordResetConfirmRequest,
    SignupRequest,
    TokenResponse,
)
from app.services import email_code
from app.services.email_code import EmailJob


P = ParamSpec("P")
R = TypeVar("R")

# Argon2는 메모리 집약적이므로 일반 동기 작업의 스레드 제한과 별도로 제한한다.
PASSWORD_HASH_LIMITER = CapacityLimiter(2)


async def run_password_operation(
    operation: Callable[P, R],
    *args: P.args,
    **kwargs: P.kwargs,
) -> R:
    return await to_thread.run_sync(
        partial(operation, *args, **kwargs),
        limiter=PASSWORD_HASH_LIMITER,
    )


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def request_signup_code(
        session: AsyncSession,
        redis: Redis,
        request: EmailCodeRequest,
        settings: Settings,
) -> EmailJob:
    email = normalize_email(request.email)
    if await user_repository.get_user_by_email(session, email) is not None:
        raise EmailAlreadyExistsError

    code = await email_code.issue_code(redis, email_code.PURPOSE_SIGNUP, email, settings)
    return await email_code.create_email_job(
        session, redis, email_code.PURPOSE_SIGNUP, email, code, settings
    )


async def confirm_signup_code(
        redis: Redis,
        request: EmailCodeConfirmRequest,
        settings: Settings,
) -> str:
    email = normalize_email(request.email)
    await email_code.confirm_code(
        redis, email_code.PURPOSE_SIGNUP, email, request.code, settings
    )
    await email_code.mark_email_verified(redis, email, settings)
    return email


async def request_password_reset_code(
        session: AsyncSession,
        redis: Redis,
        request: EmailCodeRequest,
        settings: Settings,
) -> EmailJob | None:
    """Returns None when no email should go out. The caller answers the same either way."""
    email = normalize_email(request.email)
    code = await email_code.issue_code(
        redis, email_code.PURPOSE_PASSWORD_RESET, email, settings
    )

    user = await user_repository.get_user_by_email(session, email)
    if user is None or not user.is_active:
        await email_code.discard_code(redis, email_code.PURPOSE_PASSWORD_RESET, email)
        return None

    return await email_code.create_email_job(
        session, redis, email_code.PURPOSE_PASSWORD_RESET, email, code, settings
    )


async def reset_password(
        session: AsyncSession,
        redis: Redis,
        request: PasswordResetConfirmRequest,
        settings: Settings,
) -> None:
    email = normalize_email(request.email)
    await email_code.confirm_code(
        redis, email_code.PURPOSE_PASSWORD_RESET, email, request.code, settings
    )

    user = await user_repository.get_user_by_email(session, email)
    if user is None or not user.is_active:
        raise InvalidEmailCodeError

    password_hash = await run_password_operation(hash_password, request.new_password)
    await user_repository.update_password_hash(session, user, password_hash)
    await session.commit()


async def signup(session: AsyncSession, redis: Redis, request: SignupRequest) -> User:
    email = normalize_email(request.email)
    if await user_repository.get_user_by_email(session, email) is not None:
        raise EmailAlreadyExistsError
    if not await email_code.is_email_verified(redis, email):
        raise EmailNotVerifiedError

    password_hash = await run_password_operation(hash_password, request.password)
    try:
        user = await user_repository.create_user(
            session,
            email=email,
            password_hash=password_hash,
            nickname=request.nickname,
            company=request.company,
        )
        await session.commit()
    except IntegrityError as exc:
        # 동시에 같은 이메일로 가입한 경우 unique 제약에서 걸린다.
        await session.rollback()
        raise EmailAlreadyExistsError from exc
    await email_code.clear_email_verified(redis, email)
    return user


async def login(
        session: AsyncSession,
        request: LoginRequest,
        settings: Settings,
) -> TokenResponse:
    user = await user_repository.get_user_by_email(
        session,
        normalize_email(request.email),
    )
    if user is None:
        await run_password_operation(
            verify_password,
            request.password,
            DUMMY_PASSWORD_HASH,
        )
        raise InvalidCredentialsError
    password_matches = await run_password_operation(
        verify_password,
        request.password,
        user.password_hash,
    )
    if not password_matches:
        raise InvalidCredentialsError
    if not user.is_active:
        raise InactiveUserError

    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )
