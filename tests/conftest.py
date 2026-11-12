from io import BytesIO
from typing import Any, BinaryIO, Mapping

import pytest

from app.core.errors import ObjectNotFoundError


VOICEPRINT = {"engine": "pyannote", "vector": [0.25] * 256}
ANALYSIS_DATA = {
    "speakers": [
        {"speaker": "me", "role": "me", "speech_seconds": 12.5},
        {"speaker": "A", "role": "customer", "speech_seconds": 8.0},
    ],
    "utterances": [
        {"start": 0.0, "end": 2.5, "speaker": "me", "role": "me", "text": "안녕하세요"},
        {"start": 2.6, "end": 4.0, "speaker": "A", "role": "customer", "text": "네"},
    ],
}


def ai_ok(data: Any) -> dict[str, Any]:
    return {"success": True, "code": "SUCCESS", "message": "ok", "data": data}


class FakeObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}
        self.content_types: dict[str, str | None] = {}

    async def upload(self, key: str, content: BinaryIO, content_type: str | None) -> None:
        self.objects[key] = content.read()
        self.content_types[key] = content_type

    async def download(self, key: str, destination: BinaryIO) -> None:
        if key not in self.objects:
            raise ObjectNotFoundError
        destination.write(self.objects[key])


class FakeAIClient:
    """Records multipart calls and returns queued responses or raises queued errors."""

    def __init__(self, *responses: Any) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def post_multipart(
            self,
            path: str,
            files: Mapping[str, tuple[str, BinaryIO, str | None]],
            data: Mapping[str, str] | None = None,
            timeout: float | None = None,
    ) -> dict[str, Any]:
        self.calls.append({
            "path": path,
            "files": {
                name: (filename, content.read(), content_type)
                for name, (filename, content, content_type) in files.items()
            },
            "data": dict(data) if data else None,
            "timeout": timeout,
        })
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


@pytest.fixture
def fake_storage() -> FakeObjectStorage:
    return FakeObjectStorage()
