from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user, get_settings_from_app
from app.core.config import Settings
from app.models.user import User
from app.schemas.livekit import LiveKitTokenRequest, LiveKitTokenResponse
from app.schemas.response import ApiResponse
from app.services.livekit import create_room_token

router = APIRouter()


@router.post("/token", response_model=ApiResponse[LiveKitTokenResponse])
async def issue_token(
    payload: LiveKitTokenRequest,
    user: Annotated[User, Depends(get_current_user)],
    settings: Annotated[Settings, Depends(get_settings_from_app)],
) -> ApiResponse[LiveKitTokenResponse]:
    result = create_room_token(payload, user, settings)
    return ApiResponse[LiveKitTokenResponse].ok(
        data=result,
        message="라이브킷 토큰이 발급되었습니다.",
    )
