from fastapi import HTTPException, Request
from redis.asyncio import Redis

from app.clients.ai import AIServiceClient


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
