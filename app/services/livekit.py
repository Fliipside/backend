from datetime import datetime, timedelta, timezone

import jwt

from app.core.config import Settings
from app.core.errors import ServiceNotConfiguredError
from app.models.user import User
from app.schemas.livekit import LiveKitTokenRequest, LiveKitTokenResponse


def create_room_token(
        payload: LiveKitTokenRequest,
        user: User,
        settings: Settings,
) -> LiveKitTokenResponse:
    if not settings.livekit_configured:
        raise ServiceNotConfiguredError("LiveKit")

    identity = str(user.id)
    now = datetime.now(timezone.utc)
    # LiveKit access token: API 키가 발급자(iss), 시크릿으로 HS256 서명한 JWT.
    # 만료 시각은 입장할 수 있는 기한이며, 입장한 뒤의 통화 시간을 제한하지 않는다.
    claims = {
        "iss": settings.livekit_api_key,
        "sub": identity,
        "name": user.nickname,
        "nbf": now,
        "exp": now + timedelta(seconds=settings.livekit_token_expire_seconds),
        "video": {
            "room": payload.room_name,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
            "canPublishData": True,
        },
    }
    token = jwt.encode(
        claims,
        settings.livekit_api_secret.get_secret_value(),
        algorithm="HS256",
    )
    return LiveKitTokenResponse(
        url=settings.livekit_url,
        token=token,
        room_name=payload.room_name,
        identity=identity,
        expires_in=settings.livekit_token_expire_seconds,
    )
