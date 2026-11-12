from typing import Any, BinaryIO, Mapping

import httpx

from app.core.errors import (
    AIServiceBadResponseError,
    AIServiceConnectionError,
    AIServiceTimeoutError,
    AIServiceUpstreamError,
)


FileField = tuple[str, BinaryIO, str | None]


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
        return await self.post_multipart(
            path,
            files={field_name: (filename, content, content_type)},
        )

    async def post_multipart(
            self,
            path: str,
            files: Mapping[str, FileField],
            data: Mapping[str, str] | None = None,
            timeout: float | None = None,
    ) -> dict[str, Any]:
        """Send files plus optional form fields. timeout overrides the client default."""
        kwargs: dict[str, Any] = {"files": dict(files)}
        if data:
            kwargs["data"] = dict(data)
        if timeout is not None:
            kwargs["timeout"] = timeout
        return await self._request("POST", path, **kwargs)

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
                status_code=exc.response.status_code,
                code=_error_code(exc.response),
                retry_after_seconds=_retry_after(exc.response),
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


def _error_code(response: httpx.Response) -> str | None:
    try:
        payload = response.json()
    except ValueError:
        return None
    if isinstance(payload, dict) and isinstance(payload.get("code"), str):
        return payload["code"]
    return None


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        seconds = float(value)
    except ValueError:
        return None
    return seconds if seconds >= 0 else None
