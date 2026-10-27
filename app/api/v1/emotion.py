from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_ai_client
from app.clients.ai import AIServiceClient
from app.schemas.emotion import EmotionRequest
from app.services.emotion import infer_emotion


router = APIRouter()


@router.post("/infer")
async def infer(
    request: EmotionRequest,
    ai_client: Annotated[AIServiceClient, Depends(get_ai_client)],
    ) -> dict[str, object]:
    return await infer_emotion(request, ai_client)
