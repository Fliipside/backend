from typing import Annotated

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.ai import AIServiceClient
from app.core.config import Settings
from app.core.errors import AuthenticationError, InactiveUserError
from app.core.security import decode_access_token
from app.db.session import get_db_session
from app.models.user import User
from app.repositories.user import get_user_by_id


bearer_scheme = HTTPBearer(auto_error=False)


def get_settings_from_app(request: Request) -> Settings:
    return request.app.state.settings


def get_redis(request: Request) -> Redis:
    client = getattr(request.app.state, "redis_client", None)
    if client is None:
        raise HTTPException(status_code=503, detail="Redis is not configured")
    return client


def get_ai_client(request: Request) -> AIServiceClient:
    client = getattr(request.app.state, "ai_client", None)
    if client is None:
        raise HTTPException(
            status_code=503,
            detail="AI service is not configured",
        )
    return client


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(bearer_scheme),
    ],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise AuthenticationError

    user_id = decode_access_token(credentials.credentials, settings)
    user = await get_user_by_id(session, user_id)
    if user is None:
        raise AuthenticationError("유효하지 않은 토큰입니다.")
    if not user.is_active:
        raise InactiveUserError
    return user
