import asyncio
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.deps import get_ai_client
from app.clients.ai import AIServiceClient


def make_request_with_ai_client(
        ai_client: object | None,
) -> Request:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                ai_client=ai_client,
            ),
        ),
    )
    return cast(Request, request)


def test_get_ai_client_returns_configured_client() -> None:
    http_client = httpx.AsyncClient(
        base_url="http://ai-service.test",
    )
    excepted_client = AIServiceClient(http_client)
    request = make_request_with_ai_client(excepted_client)

    try:
        result = get_ai_client(request)

        assert result is excepted_client
    finally:
        asyncio.run(http_client.aclose())


def test_get_ai_client_raises_503_when_not_configured() -> None:
    request = make_request_with_ai_client(None)

    with pytest.raises(HTTPException) as exc_info:
        get_ai_client(request)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "AI service is not configured"