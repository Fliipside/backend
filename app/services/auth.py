from collections.abc import Callable
from functools import partial
from typing import ParamSpec, TypeVar

from anyio import CapacityLimiter, to_thread
from redis.asyncio import Redis
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    AccountNotFoundError,
    EmailAlreadyExistsError,
    EmailNotVerifiedError,
    FindIdLimitError,
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
    FindIdRequest,
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
        session,
        redis,
        email_code.PURPOSE_SIGNUP,
        email,
        email_code.build_code_email(email_code.PURPOSE_SIGNUP, code, settings),
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
        session,
        redis,
        email_code.PURPOSE_PASSWORD_RESET,
        email,
        email_code.build_code_email(email_code.PURPOSE_PASSWORD_RESET, code, settings),
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
            name=request.name,
            phone=request.phone,
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


MASKED_LOCAL_LENGTH = 10
MASK_VISIBLE_LENGTH = 2
FIND_ID_IP_WINDOW_SECONDS = 60 * 60
FIND_ID_PHONE_WINDOW_SECONDS = 24 * 60 * 60


def mask_email(email: str) -> str:
    """Show the first two characters and pad the local part to ten with '*'.

    The length is always the same, so a short address such as a@x.com does not
    reveal how short it is. assff11@gmail.com -> as********@gmail.com
    """
    local, domain = email.rsplit("@", 1)
    visible = local[:MASK_VISIBLE_LENGTH]
    return f"{visible}{'*' * (MASKED_LOCAL_LENGTH - len(visible))}@{domain}"


async def _count_find_id_attempt(
        redis: Redis,
        key: str,
        limit: int,
        window_seconds: int,
) -> None:
    attempts = await redis.incr(key)
    if attempts == 1:
        await redis.expire(key, window_seconds)
    if attempts > limit:
        remaining = await redis.ttl(key)
        raise FindIdLimitError(max(int(remaining), 1))


async def find_id(
        session: AsyncSession,
        redis: Redis,
        request: FindIdRequest,
        client_ip: str,
        settings: Settings,
) -> tuple[list[str], list[EmailJob]]:
    """Mail each matching account its email and return the masked addresses.

    Attempts are counted before the lookup, so a miss costs the same as a hit.
    Inactive users are treated as not found, as in password reset.
    """
    await _count_find_id_attempt(
        redis,
        f"find_id:ip:{client_ip}",
        settings.find_id_ip_hourly_limit,
        FIND_ID_IP_WINDOW_SECONDS,
    )
    await _count_find_id_attempt(
        redis,
        f"find_id:phone:{request.phone}",
        settings.find_id_phone_daily_limit,
        FIND_ID_PHONE_WINDOW_SECONDS,
    )

    users = await user_repository.list_active_users_by_name_and_phone(
        session, request.name, request.phone
    )
    if not users:
        raise AccountNotFoundError

    await email_code.check_daily_total(redis, settings)
    jobs: list[EmailJob] = []
    for user in users:
        if not await email_code.reserve_send(
            redis, email_code.PURPOSE_FIND_ID, user.email, settings
        ):
            continue
        jobs.append(
            await email_code.create_email_job(
                session,
                redis,
                email_code.PURPOSE_FIND_ID,
                user.email,
                email_code.build_find_id_email(user.email),
            )
        )
    return [mask_email(user.email) for user in users], jobs
