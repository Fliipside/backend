from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.core.errors import (
    EmailAlreadyExistsError,
    InactiveUserError,
    InvalidCredentialsError,
)
from app.core.security import (
    DUMMY_PASSWORD_HASH,
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.user import User
from app.repositories import user as user_repository
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def signup(session: AsyncSession, request: SignupRequest) -> User:
    email = normalize_email(request.email)
    if await user_repository.get_user_by_email(session, email) is not None:
        raise EmailAlreadyExistsError

    try:
        user = await user_repository.create_user(
            session,
            email=email,
            password_hash=hash_password(request.password),
            nickname=request.nickname,
        )
        await session.commit()
    except IntegrityError as exc:
        # 동시에 같은 이메일로 가입한 경우 unique 제약에서 걸린다.
        await session.rollback()
        raise EmailAlreadyExistsError from exc
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
        verify_password(request.password, DUMMY_PASSWORD_HASH)
        raise InvalidCredentialsError
    if not verify_password(request.password, user.password_hash):
        raise InvalidCredentialsError
    if not user.is_active:
        raise InactiveUserError

    return TokenResponse(
        access_token=create_access_token(user.id, settings),
        expires_in=settings.jwt_access_token_expire_minutes * 60,
    )
