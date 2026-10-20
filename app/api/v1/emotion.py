from fastapi import APIRouter

from app.schemas.emotion import EmotionRequest
from app.services.emotion import infer_emotion

router = APIRouter()


@router.post("/infer")
async def infer(request: EmotionRequest) -> None:
    """Provisional text emotion endpoint; inference will be added later."""
    await infer_emotion(request)
