import asyncio
import json
from io import BytesIO

import httpx
import pytest

from app.clients.ai import AIServiceClient
from app.core.errors import (
    AIServiceBadResponseError,
    AIServiceConnectionError,
    AIServiceTimeoutError,
    AIServiceUpstreamError,
)


def test_post_json_sends_request_and_returns_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/emotion/infer"
        assert request.headers["content-type"] == "application/json"

        request_payload = json.loads(request.content)
        assert request_payload == {"text": "기분이 좋아"}

        return httpx.Response(
            status_code=200,
            json={
                "emotion": "happy",
                "confidence": 0.92,
            },
        )

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            base_url="http://ai-service.test",
            transport=transport,
        ) as http_client:
            client = AIServiceClient(http_client)

            result = await client.post_json(
                "emotion/infer",
                payload={"text": "기분이 좋아"},
            )

        assert result == {
            "emotion": "happy",
            "confidence": 0.92,
        }

    asyncio.run(run_test())


def test_post_file_sends_multipart_request() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/voice/infer"
        assert request.headers["content-type"].startswith(
            "multipart/form-data; boundary="
        )

        request_body = await request.aread()

        assert b'name="file"' in request_body
        assert b'filename="sample.wav"' in request_body
        assert b"audio/wav" in request_body
        assert b"audio-content" in request_body

        return httpx.Response(
            status_code=200,
            json={
                "text": "음성 인식 결과",
            },
        )

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            base_url="http://ai-service.test",
            transport=transport,
        ) as http_client:
            client = AIServiceClient(http_client)

            result = await client.post_file(
                path="voice/infer",
                field_name="file",
                filename="sample.wav",
                content=BytesIO(b"audio-content"),
                content_type="audio/wav",
            )

        assert result == {
            "text": "음성 인식 결과",
        }

    asyncio.run(run_test())


def test_post_json_converts_upstream_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=500,
            json={
                "detail": "Internal AI service error",
            },
        )

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            base_url="http://ai-service.test",
            transport=transport,
        ) as http_client:
            client = AIServiceClient(http_client)

            with pytest.raises(AIServiceUpstreamError) as exc_info:
                await client.post_json(
                    "emotion/infer",
                    payload={"text": "테스트"},
                )

        assert exc_info.value.status_code == 500

    asyncio.run(run_test())


def test_post_json_converts_timeout_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(
            "AI service request timed out",
            request=request,
        )

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            base_url="http://ai-service.test",
            transport=transport,
        ) as http_client:
            client = AIServiceClient(http_client)

            with pytest.raises(AIServiceTimeoutError):
                await client.post_json(
                    "emotion/infer",
                    payload={"text": "테스트"},
                )

    asyncio.run(run_test())


def test_post_json_converts_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(
            "Could not connect to AI service",
            request=request,
        )

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            base_url="http://ai-service.test",
            transport=transport,
        ) as http_client:
            client = AIServiceClient(http_client)

            with pytest.raises(AIServiceConnectionError):
                await client.post_json(
                    "emotion/infer",
                    payload={"text": "테스트"},
                )

    asyncio.run(run_test())


def test_post_json_rejects_non_json_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            text="not json",
            headers={
                "content-type": "text/plain",
            },
        )

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            base_url="http://ai-service.test",
            transport=transport,
        ) as http_client:
            client = AIServiceClient(http_client)

            with pytest.raises(AIServiceBadResponseError):
                await client.post_json(
                    "emotion/infer",
                    payload={"text": "테스트"},
                )

    asyncio.run(run_test())


def test_post_json_rejects_json_array_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            json=[
                {
                    "emotion": "happy",
                },
            ],
        )

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            base_url="http://ai-service.test",
            transport=transport,
        ) as http_client:
            client = AIServiceClient(http_client)

            with pytest.raises(AIServiceBadResponseError):
                await client.post_json(
                    "emotion/infer",
                    payload={"text": "테스트"},
                )

    asyncio.run(run_test())