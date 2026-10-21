from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.router import router as api_router
from app.core.config import Settings, get_settings
from app.core.errors import FeatureNotReadyError
from app.db.session import verify_database_connection


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine = None
    redis_client = None
    ai_client = None
    try:
        if settings.database_url:
            engine = create_async_engine(settings.database_url, pool_pre_ping=True)
            await verify_database_connection(engine)
        if settings.redis_url:
            redis_client = Redis.from_url(settings.redis_url, decode_responses=True)
        if settings.ai_service_url:
            ai_client = httpx.AsyncClient(base_url=settings.ai_service_url, timeout=30.0)

        app.state.db_sessionmaker = (
            async_sessionmaker(engine, expire_on_commit=False) if engine else None
        )
        app.state.redis_client = redis_client
        app.state.ai_client = ai_client
        yield
    finally:
        if ai_client is not None:
            await ai_client.aclose()
        if redis_client is not None:
            await redis_client.aclose()
        if engine is not None:
            await engine.dispose()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.state.settings = settings

    @app.exception_handler(FeatureNotReadyError)
    async def feature_not_ready_handler(
        request: Request, exc: FeatureNotReadyError
    ) -> JSONResponse:
        return JSONResponse(status_code=501, content={"detail": str(exc)})

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
