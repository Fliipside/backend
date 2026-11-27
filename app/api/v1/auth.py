from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Request, status
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import (
    get_current_user,
    get_db_sessionmaker,
    get_email_sender,
    get_redis,
    get_settings_from_app,
)
from app.clients.email import EmailSender
from app.core.config import Settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.auth import (
    EmailCodeConfirmRequest,
    EmailCodeRequest,
    EmailCodeSentResponse,
    EmailVerifiedResponse,
    FindIdRequest,
    FindIdResponse,
    LoginRequest,
    PasswordResetConfirmRequest,
    SignupRequest,
    TokenResponse,
    UserResponse,
)
from app.schemas.response import ApiResponse
from app.services import auth as auth_service
from app.services import email_code


router = APIRouter()


def code_sent_response(settings: Settings) -> ApiResponse[EmailCodeSentResponse]:
    return ApiResponse[EmailCodeSentResponse].ok(
        data=EmailCodeSentResponse(
            expires_in=settings.email_code_expire_seconds,
            resend_after=settings.email_code_resend_cooldown_seconds,
        )
    )


@router.post(
    "/email-verification/request",
    response_model=ApiResponse[EmailCodeSentResponse],
)
async def request_email_verification(
    request: EmailCodeRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    sessionmaker: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_db_sessionmaker),
    ],
    redis: Annotated[Redis, Depends(get_redis)],
    sender: Annotated[EmailSender, Depends(get_email_sender)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[EmailCodeSentResponse]:
    job = await auth_service.request_signup_code(session, redis, request, settings)
    background_tasks.add_task(email_code.deliver, sessionmaker, sender, job)
    return code_sent_response(settings)


@router.post(
    "/email-verification/confirm",
    response_model=ApiResponse[EmailVerifiedResponse],
)
async def confirm_email_verification(
    request: EmailCodeConfirmRequest,
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[EmailVerifiedResponse]:
    email = await auth_service.confirm_signup_code(redis, request, settings)
    return ApiResponse[EmailVerifiedResponse].ok(
        data=EmailVerifiedResponse(
            email=email,
            expires_in=settings.email_verified_expire_seconds,
        )
    )


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[UserResponse],
)
async def signup(
    request: SignupRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
) -> ApiResponse[UserResponse]:
    user = await auth_service.signup(session, redis, request)
    return ApiResponse[UserResponse].ok(data=UserResponse.model_validate(user))


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    request: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[TokenResponse]:
    token = await auth_service.login(session, request, settings)
    return ApiResponse[TokenResponse].ok(data=token)


@router.post("/find-id", response_model=ApiResponse[FindIdResponse])
async def find_id(
    request: FindIdRequest,
    http_request: Request,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    sessionmaker: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_db_sessionmaker),
    ],
    redis: Annotated[Redis, Depends(get_redis)],
    sender: Annotated[EmailSender, Depends(get_email_sender)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[FindIdResponse]:
    client_ip = http_request.client.host if http_request.client else "unknown"
    emails, jobs = await auth_service.find_id(
        session, redis, request, client_ip, settings
    )
    for job in jobs:
        background_tasks.add_task(email_code.deliver, sessionmaker, sender, job)
    return ApiResponse[FindIdResponse].ok(data=FindIdResponse(emails=emails))


@router.post(
    "/password-reset/request",
    response_model=ApiResponse[EmailCodeSentResponse],
)
async def request_password_reset(
    request: EmailCodeRequest,
    background_tasks: BackgroundTasks,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    sessionmaker: Annotated[
        async_sessionmaker[AsyncSession],
        Depends(get_db_sessionmaker),
    ],
    redis: Annotated[Redis, Depends(get_redis)],
    sender: Annotated[EmailSender, Depends(get_email_sender)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[EmailCodeSentResponse]:
    job = await auth_service.request_password_reset_code(
        session, redis, request, settings
    )
    if job is not None:
        background_tasks.add_task(email_code.deliver, sessionmaker, sender, job)
    return code_sent_response(settings)


@router.post("/password-reset/confirm", response_model=ApiResponse[None])
async def confirm_password_reset(
    request: PasswordResetConfirmRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[None]:
    await auth_service.reset_password(session, redis, request, settings)
    return ApiResponse[None].ok()


@router.get("/me", response_model=ApiResponse[UserResponse])
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> ApiResponse[UserResponse]:
    return ApiResponse[UserResponse].ok(data=UserResponse.model_validate(user))
