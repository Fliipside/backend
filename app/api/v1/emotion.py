from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_ai_client
from app.clients.ai import AIServiceClient
from app.schemas.emotion import EmotionRequest
from app.schemas.response import ApiResponse
from app.services.emotion import infer_emotion


router = APIRouter()


@router.post("/infer", response_model=ApiResponse[dict[str, object]])
async def infer(
    request: EmotionRequest,
    ai_client: Annotated[AIServiceClient, Depends(get_ai_client)],
    ) -> ApiResponse[dict[str, object]]:
    result = await infer_emotion(request, ai_client)
    return ApiResponse[dict[str, object]].ok(data=result)
