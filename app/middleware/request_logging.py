import logging
import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from fastapi import FastAPI, Request, Response

logger = logging.getLogger("uvicorn.error")

def register_request_logging_middleware(app: FastAPI) -> None:
    @app.middleware("http")
    async def log_request(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = str(uuid4())
        request.state.request_id = request_id
        # 프록시 뒤에서는 uvicorn이 신뢰하는 프록시(FORWARDED_ALLOW_IPS)의
        # X-Forwarded-For 값으로 request.client를 바꿔 준다.
        client_ip = request.client.host if request.client else "-"

        started_at = time.perf_counter()

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1000

            logger.exception(
                "request_failed "
                "request_id=%s client_ip=%s method=%s path=%s "
                "status_code=500 duration_ms=%.2f",
                request_id,
                client_ip,
                request.method,
                request.url.path,
                duration_ms,
            )
            raise

        duration_ms = (time.perf_counter() - started_at) * 1000
        response.headers["X-Request-ID"] = request_id

        if response.status_code >= 500:
            log_level = logging.ERROR
        elif response.status_code >= 400:
            log_level = logging.WARNING
        else:
            log_level = logging.INFO

        logger.log(
            log_level,
            "request_completed "
            "request_id=%s client_ip=%s method=%s path=%s "
            "status_code=%d duration_ms=%.2f",
            request_id,
            client_ip,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        return response