from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import logging
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.v1.router import router as api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.schemas.response import ApiResponse
from app.db.session import verify_database_connection


logger = logging.getLogger(__name__)

HTTP_ERROR_CODES = {
    400: "INVALID_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    415: "UNSUPPORTED_MEDIA_TYPE",
    422: "INVALID_REQUEST",
    429: "TOO_MANY_REQUESTS",
    503: "SERVICE_UNAVAILABLE",
}


def get_http_error_code(status_code: int) -> str:
    return HTTP_ERROR_CODES.get(status_code, "HTTP_ERROR")


def create_error_content(code: str, message: str) -> dict[str, object]:
    response = ApiResponse[None].fail(
        code=code,
        message=message,
    )
    return response.model_dump(mode="json")


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

    @app.exception_handler(AppError)
    async def app_error_handler(
        _request: Request,
        exc: AppError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_content(
                code=exc.code,
                message=exc.message,
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        _request: Request,
        _exc: RequestValidationError,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=create_error_content(
                code="INVALID_REQUEST",
                message="요청 값이 올바르지 않습니다.",
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        message = (
            exc.detail
            if isinstance(exc.detail, str)
            else "요청을 처리할 수 없습니다."
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=create_error_content(
                code=get_http_error_code(exc.status_code),
                message=message,
            ),
            headers=exc.headers,
        )

    @app.exception_handler(Exception)
    async def unexpected_error_handler(
        _request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.error(
            "Unhandled exception",
            exc_info=(type(exc), exc, exc.__traceback__),
        )
        return JSONResponse(
            status_code=500,
            content=create_error_content(
                code="INTERNAL_SERVER_ERROR",
                message="서버 내부 오류가 발생했습니다.",
            ),
        )

    @app.get("/health", tags=["health"], response_model=ApiResponse[dict[str, str]],)
    def health() -> ApiResponse[dict[str, str]]:
        return ApiResponse[dict[str, str]].ok(
            data={"status": "ok"}
        )

    app.include_router(api_router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
