from fastapi import APIRouter

from app.schemas.emotion import EmotionRequest
from app.schemas.response import ApiResponse
from app.services.emotion import infer_emotion

router = APIRouter()


@router.post("/infer", response_model=ApiResponse[None])
async def infer(request: EmotionRequest) -> ApiResponse[None]:
    await infer_emotion(request)
    return ApiResponse[None].ok()
