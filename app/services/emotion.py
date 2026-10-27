from app.clients.ai import AIServiceClient
from app.schemas.emotion import EmotionRequest


async def infer_emotion(
        request: EmotionRequest,
        ai_client: AIServiceClient,
) -> dict[str, object]:
    return await ai_client.post_json(
        "emotion/infer",
        payload=request.model_dump(),
    )