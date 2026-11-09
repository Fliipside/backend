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

def test_post_multipart_sends_form_fields_and_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/voice/analyze"
        assert request.extensions["timeout"]["read"] == 1800.0

        request_body = await request.aread()

        assert b'name="file"' in request_body
        assert b'filename="meeting.m4a"' in request_body
        assert b"audio-content" in request_body
        assert b'name="voiceprint"' in request_body
        assert b'{"engine": "pyannote", "vector": [0.1]}' in request_body

        return httpx.Response(status_code=200, json={"success": True, "data": {}})

    async def run_test() -> None:
        transport = httpx.MockTransport(handler)

        async with httpx.AsyncClient(
            base_url="http://ai-service.test",
            transport=transport,
            timeout=30,
        ) as http_client:
            client = AIServiceClient(http_client)

            result = await client.post_multipart(
                "voice/analyze",
                files={"file": ("meeting.m4a", BytesIO(b"audio-content"), "audio/mp4")},
                data={"voiceprint": json.dumps({"engine": "pyannote", "vector": [0.1]})},
                timeout=1800.0,
            )

        assert result == {"success": True, "data": {}}

    asyncio.run(run_test())


def test_upstream_error_keeps_ai_error_code_and_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=429,
            headers={"retry-after": "42"},
            json={
                "success": False,
                "code": "STT_RATE_LIMITED",
                "message": "rate limited",
                "data": None,
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
                await client.post_multipart(
                    "voice/analyze",
                    files={"file": ("a.wav", BytesIO(b"x"), "audio/wav")},
                )

        assert exc_info.value.status_code == 429
        assert exc_info.value.code == "STT_RATE_LIMITED"
        assert exc_info.value.retry_after_seconds == 42.0

    asyncio.run(run_test())
