from typing import Any, BinaryIO

import httpx

from app.core.errors import (
    AIServiceBadResponseError,
    AIServiceConnectionError,
    AIServiceTimeoutError,
    AIServiceUpstreamError,
)


class AIServiceClient:
    def __init__(self, http_client: httpx.AsyncClient) -> None:
        self._http_client = http_client

    async def post_json(
            self,
            path: str,
            payload: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._request("POST", path, json=payload)

    async def post_file(
            self,
            path: str,
            field_name: str,
            filename: str,
            content: BinaryIO,
            content_type: str | None,
    ) -> dict[str, Any]:
        files = {
            field_name: (filename, content, content_type),
        }
        return await self._request("POST", path, files=files)

    async def _request(
            self,
            method: str,
            path: str,
            **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = await self._http_client.request(method, path, **kwargs)
            response.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AIServiceTimeoutError from exc
        except httpx.HTTPStatusError as exc:
            raise AIServiceUpstreamError(
                status_code=exc.response.status_code
            ) from exc
        except httpx.RequestError as exc:
            raise AIServiceConnectionError from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise AIServiceBadResponseError from exc

        if not isinstance(payload, dict):
            raise AIServiceBadResponseError

        return payload