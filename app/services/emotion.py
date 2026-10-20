from app.core.errors import FeatureNotReadyError
from app.schemas.emotion import EmotionRequest


async def infer_emotion(request: EmotionRequest) -> None:
    # Call the separate emotion AI service and adapt its response here.
    raise FeatureNotReadyError("emotion")
