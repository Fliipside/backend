from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_settings_from_app
from app.core.config import Settings
from app.db.session import get_db_session
from app.models.user import User
from app.schemas.auth import LoginRequest, SignupRequest, TokenResponse, UserResponse
from app.schemas.response import ApiResponse
from app.services import auth as auth_service


router = APIRouter()


@router.post(
    "/signup",
    status_code=status.HTTP_201_CREATED,
    response_model=ApiResponse[UserResponse],
)
async def signup(
    request: SignupRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> ApiResponse[UserResponse]:
    user = await auth_service.signup(session, request)
    return ApiResponse[UserResponse].ok(data=UserResponse.model_validate(user))


@router.post("/login", response_model=ApiResponse[TokenResponse])
async def login(
    request: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[TokenResponse]:
    token = await auth_service.login(session, request, settings)
    return ApiResponse[TokenResponse].ok(data=token)


@router.get("/me", response_model=ApiResponse[UserResponse])
async def me(
    user: Annotated[User, Depends(get_current_user)],
) -> ApiResponse[UserResponse]:
    return ApiResponse[UserResponse].ok(data=UserResponse.model_validate(user))
