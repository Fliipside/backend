import asyncio
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.errors import ObjectStorageError
from app.db.base import Base
from app.main import create_app
from app.models.image import Image
from app.services.image import detect_image_type
from tests.conftest import FakeObjectStorage


JPEG = b"\xff\xd8\xff\xe0" + b"jpeg-body"
PNG = b"\x89PNG\r\n\x1a\n" + b"png-body"
WEBP = b"RIFF\x10\x00\x00\x00WEBP" + b"webp-body"


@pytest.fixture
def sessionmaker(tmp_path: Path) -> async_sessionmaker:
    path = tmp_path / "image.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return async_sessionmaker(
        create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool),
        expire_on_commit=False,
    )


@pytest.fixture
def client(
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
) -> Iterator[TestClient]:
    settings = Settings(
        postgres_host="",
        postgres_db="",
        postgres_user="",
        postgres_password="",
        redis_url="",
        ai_service_url="",
        jwt_secret_key="test-secret-key-with-enough-length-1234",
        image_max_bytes=100,
        image_url_expire_seconds=600,
    )
    app = create_app(settings)

    with TestClient(app) as test_client:
        app.state.db_sessionmaker = sessionmaker
        app.state.object_storage = fake_storage
        yield test_client


def auth_header(client: TestClient, email: str = "user@example.com") -> dict[str, str]:
    client.post(
        "/api/v1/auth/signup",
        json={"email": email, "password": "password1234", "nickname": "tester"},
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password1234"},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


def upload(
    client: TestClient,
    headers: dict[str, str],
    content: bytes = JPEG,
    content_type: str = "image/jpeg",
):
    return client.post(
        "/api/v1/images",
        headers=headers,
        files={"file": ("card.jpg", content, content_type)},
    )


def stored_images(sessionmaker: async_sessionmaker) -> list[Image]:
    async def fetch() -> list[Image]:
        async with sessionmaker() as session:
            return list((await session.execute(select(Image))).scalars())

    return asyncio.run(fetch())


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (JPEG, "image/jpeg"),
        (PNG, "image/png"),
        (WEBP, "image/webp"),
        (b"GIF89a", None),
        (b"RIFF\x10\x00\x00\x00WAVE", None),
        (b"", None),
    ],
)
def test_detect_image_type(header: bytes, expected: str | None) -> None:
    assert detect_image_type(header[:12]) == expected


def test_upload_stores_file_and_returns_signed_url(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
) -> None:
    response = upload(client, auth_header(client))

    assert response.status_code == 201
    body = response.json()
    assert body["code"] == "CREATED"
    data = body["data"]
    assert data["content_type"] == "image/jpeg"
    assert data["file_size"] == len(JPEG)

    [image] = stored_images(sessionmaker)
    assert str(image.id) == data["image_id"]
    assert image.object_key == f"images/{image.user_id}/{image.id}.jpg"
    assert fake_storage.objects[image.object_key] == JPEG
    assert data["url"] == f"https://storage.test/{image.object_key}?expires=600"


def test_upload_uses_detected_type_not_client_content_type(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
) -> None:
    response = upload(client, auth_header(client), content=PNG, content_type="image/jpeg")

    assert response.status_code == 201
    [image] = stored_images(sessionmaker)
    assert image.content_type == "image/png"
    assert image.object_key.endswith(".png")
    assert fake_storage.content_types[image.object_key] == "image/png"


@pytest.mark.parametrize(
    ("content", "status_code", "code"),
    [
        (b"", 400, "EMPTY_FILE"),
        (b"not an image", 400, "INVALID_IMAGE"),
        (JPEG + b"x" * 100, 413, "PAYLOAD_TOO_LARGE"),
    ],
)
def test_upload_rejects_bad_files(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
    content: bytes,
    status_code: int,
    code: str,
) -> None:
    response = upload(client, auth_header(client), content=content)

    assert response.status_code == status_code
    assert response.json()["code"] == code
    assert fake_storage.objects == {}
    assert stored_images(sessionmaker) == []


def test_upload_requires_login(client: TestClient) -> None:
    assert upload(client, {}).status_code == 401


def test_upload_returns_503_when_storage_fails(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*_args, **_kwargs) -> None:
        raise ObjectStorageError

    monkeypatch.setattr(fake_storage, "upload", fail)

    response = upload(client, auth_header(client))

    assert response.status_code == 503
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"
    assert stored_images(sessionmaker) == []


def test_upload_removes_file_when_database_save_fails(
    client: TestClient,
    fake_storage: FakeObjectStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*_args, **_kwargs):
        raise RuntimeError("db down")

    headers = auth_header(client)
    monkeypatch.setattr("app.services.image.image_repository.create_image", fail)

    with pytest.raises(RuntimeError):
        upload(client, headers)

    assert fake_storage.objects == {}


def test_get_returns_own_image(client: TestClient) -> None:
    headers = auth_header(client)
    created = upload(client, headers).json()["data"]

    response = client.get(f"/api/v1/images/{created['image_id']}", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["image_id"] == created["image_id"]
    assert data["url"] == created["url"]


def test_other_user_cannot_get_or_delete_image(
    client: TestClient,
    fake_storage: FakeObjectStorage,
) -> None:
    image_id = upload(client, auth_header(client)).json()["data"]["image_id"]
    other = auth_header(client, "other@example.com")

    for response in (
        client.get(f"/api/v1/images/{image_id}", headers=other),
        client.delete(f"/api/v1/images/{image_id}", headers=other),
    ):
        assert response.status_code == 404
        assert response.json()["code"] == "IMAGE_NOT_FOUND"
    assert len(fake_storage.objects) == 1


def test_get_unknown_image_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/images/{uuid4()}", headers=auth_header(client))

    assert response.status_code == 404


def test_delete_removes_file_and_row(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
) -> None:
    headers = auth_header(client)
    image_id = upload(client, headers).json()["data"]["image_id"]

    response = client.delete(f"/api/v1/images/{image_id}", headers=headers)

    assert response.status_code == 200
    assert response.json()["data"] is None
    assert fake_storage.objects == {}
    assert stored_images(sessionmaker) == []
    assert client.get(f"/api/v1/images/{image_id}", headers=headers).status_code == 404


def test_delete_keeps_row_when_storage_fails(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail(*_args, **_kwargs) -> None:
        raise ObjectStorageError

    headers = auth_header(client)
    image_id = upload(client, headers).json()["data"]["image_id"]
    monkeypatch.setattr(fake_storage, "delete", fail)

    response = client.delete(f"/api/v1/images/{image_id}", headers=headers)

    assert response.status_code == 503
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"
    assert len(stored_images(sessionmaker)) == 1
