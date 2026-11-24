import asyncio
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import Settings
from app.core.errors import AIServiceUpstreamError, ObjectStorageError
from app.db.base import Base
from app.main import create_app
from app.models.interaction import Interaction
from app.models.user import User
from app.models.voice import VoiceAnalysisJob, Voiceprint
from app.services.voice import VOICE_ANALYSIS_QUEUE
from tests.conftest import (
    ANALYSIS_DATA,
    VOICEPRINT,
    FakeAIClient,
    FakeObjectStorage,
    ai_ok,
    mark_email_verified,
)


@pytest.fixture
def database_path(tmp_path: Path) -> Path:
    path = tmp_path / "voice.db"
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    engine.dispose()
    return path


@pytest.fixture
def redis_server() -> fakeredis.FakeServer:
    return fakeredis.FakeServer()


@pytest.fixture
def sessionmaker(database_path: Path) -> async_sessionmaker:
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{database_path}",
        poolclass=NullPool,
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.fixture
def ai_client() -> FakeAIClient:
    return FakeAIClient()


@pytest.fixture
def client(
    sessionmaker: async_sessionmaker,
    redis_server: fakeredis.FakeServer,
    fake_storage: FakeObjectStorage,
    ai_client: FakeAIClient,
) -> Iterator[TestClient]:
    settings = Settings(
        postgres_host="",
        postgres_db="",
        postgres_user="",
        postgres_password="",
        redis_url="",
        ai_service_url="",
        jwt_secret_key="test-secret-key-with-enough-length-1234",
        voice_recording_max_bytes=100,
        voice_enroll_max_bytes=50,
    )
    app = create_app(settings)

    with TestClient(app) as test_client:
        app.state.db_sessionmaker = sessionmaker
        app.state.redis_client = fakeredis.aioredis.FakeRedis(
            server=redis_server,
            decode_responses=True,
        )
        app.state.object_storage = fake_storage
        app.state.ai_client = ai_client
        yield test_client


def auth_header(client: TestClient, email: str = "user@example.com") -> dict[str, str]:
    mark_email_verified(client, email)
    client.post(
        "/api/v1/auth/signup",
        json={
            "email": email,
            "password": "password1234",
            "nickname": "tester",
            "company": "Flipside",
        },
    )
    response = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password1234"},
    )
    return {"Authorization": f"Bearer {response.json()['data']['access_token']}"}


ANALYSES_PATH = "/api/v1/voice/analyses"


def upload(
    client: TestClient,
    path: str,
    headers: dict[str, str],
    content: bytes = b"audio",
    data: dict[str, str] | None = None,
):
    return client.post(
        path,
        headers=headers,
        files={"file": ("meeting.m4a", content, "audio/mp4")},
        data=data,
    )


def create_customer(client: TestClient, headers: dict[str, str]) -> int:
    response = client.post(
        "/api/v1/customers",
        headers=headers,
        json={"company_name": "노바테크", "name": "김민준"},
    )
    assert response.status_code == 201
    return response.json()["data"]["customer_id"]


def upload_analysis(
    client: TestClient,
    headers: dict[str, str],
    content: bytes = b"audio",
    **form: str,
):
    """Upload a recording for a new customer of the caller, unless customer_id is given."""
    if "customer_id" not in form:
        form["customer_id"] = str(create_customer(client, headers))
    return upload(client, ANALYSES_PATH, headers, content, data=form)


def as_utc(value: datetime) -> datetime:
    # SQLite drops the time zone; the stored value is UTC.
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def run(coro):
    return asyncio.run(coro)


async def fetch_all(sessionmaker: async_sessionmaker, model):
    async with sessionmaker() as session:
        return list((await session.execute(select(model))).scalars())


def test_create_analysis_uploads_file_and_enqueues_job(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    redis_server: fakeredis.FakeServer,
    fake_storage: FakeObjectStorage,
) -> None:
    headers = auth_header(client)
    customer_id = create_customer(client, headers)
    before = datetime.now(timezone.utc)

    response = upload_analysis(client, headers, customer_id=str(customer_id))

    assert response.status_code == 202
    body = response.json()
    assert body["code"] == "ACCEPTED"
    assert body["data"]["status"] == "queued"
    job_id = body["data"]["job_id"]

    [job] = run(fetch_all(sessionmaker, VoiceAnalysisJob))
    assert str(job.id) == job_id

    # Only customer_id was sent, so the rest of the interaction uses defaults.
    [interaction] = run(fetch_all(sessionmaker, Interaction))
    assert body["data"]["interaction_id"] == str(interaction.id)
    assert job.interaction_id == interaction.id
    assert interaction.customer_id == customer_id
    assert interaction.owner_user_id == job.user_id
    assert interaction.kind == "meeting"
    assert interaction.title == "meeting"  # meeting.m4a without the extension
    assert before <= as_utc(interaction.occurred_at) <= datetime.now(timezone.utc)
    assert job.object_key == f"voice-recordings/{job.user_id}/{job_id}.m4a"
    assert fake_storage.objects[job.object_key] == b"audio"
    assert job.file_size == 5

    redis = fakeredis.FakeRedis(server=redis_server, decode_responses=True)
    assert redis.lrange(f"{VOICE_ANALYSIS_QUEUE}:pending", 0, -1) == [job_id]


def test_get_analysis_returns_result_only_to_owner(
    client: TestClient,
    sessionmaker: async_sessionmaker,
) -> None:
    owner = auth_header(client)
    customer_id = create_customer(client, owner)
    created = upload_analysis(
        client,
        owner,
        customer_id=str(customer_id),
        kind="call",
        title="  2차 견적 통화  ",
        occurred_at="2026-11-20T14:00:00+09:00",
    ).json()["data"]
    job_id = created["job_id"]

    response = client.get(f"/api/v1/voice/analyses/{job_id}", headers=owner)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["interaction_id"] == created["interaction_id"]
    assert data["customer_id"] == customer_id
    assert data["kind"] == "call"
    assert data["title"] == "2차 견적 통화"
    assert as_utc(datetime.fromisoformat(data["occurred_at"])) == datetime(
        2026, 11, 20, 5, 0, tzinfo=timezone.utc
    )
    assert data["status"] == "queued"
    assert data["result"] is None
    assert data["used_voiceprint"] is False

    async def finish() -> None:
        async with sessionmaker() as session:
            job = await session.get(VoiceAnalysisJob, UUID(job_id))
            job.status = "succeeded"
            job.result = ANALYSIS_DATA
            job.used_voiceprint_engine = "pyannote"
            await session.commit()

    run(finish())
    data = client.get(f"/api/v1/voice/analyses/{job_id}", headers=owner).json()["data"]
    assert data["status"] == "succeeded"
    assert data["result"] == ANALYSIS_DATA
    assert data["used_voiceprint"] is True

    other = auth_header(client, "other@example.com")
    response = client.get(f"/api/v1/voice/analyses/{job_id}", headers=other)
    assert response.status_code == 404
    assert response.json()["code"] == "VOICE_ANALYSIS_NOT_FOUND"


def test_get_analysis_without_interaction_returns_nulls(
    client: TestClient,
    sessionmaker: async_sessionmaker,
) -> None:
    """Jobs created before interactions existed have no interaction."""
    headers = auth_header(client)
    job_id = uuid4()

    async def add_old_job() -> None:
        async with sessionmaker() as session:
            user_id = (await session.execute(select(User.id))).scalar_one()
            session.add(VoiceAnalysisJob(
                id=job_id,
                user_id=user_id,
                object_key=f"voice-recordings/{user_id}/{job_id}.m4a",
                original_filename="old.m4a",
                file_size=5,
            ))
            await session.commit()

    run(add_old_job())
    response = client.get(f"{ANALYSES_PATH}/{job_id}", headers=headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "queued"
    for field in ("interaction_id", "customer_id", "kind", "title", "occurred_at"):
        assert data[field] is None


def test_create_analysis_without_customer_id_returns_400(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
) -> None:
    """Requests that send only the file (the old format) are rejected."""
    response = upload(client, ANALYSES_PATH, auth_header(client))

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert fake_storage.objects == {}
    assert run(fetch_all(sessionmaker, VoiceAnalysisJob)) == []
    assert run(fetch_all(sessionmaker, Interaction)) == []


@pytest.mark.parametrize(
    "form",
    [
        {"customer_id": "abc"},
        {"customer_id": "1.5"},
        {"customer_id": "0"},
        {"customer_id": "99999999999"},
        {"kind": "email"},
        {"title": "x" * 201},
        {"occurred_at": "2026-11-20T14:00:00"},  # no time zone
        {"occurred_at": "2026-11-20"},  # no time zone
        {"occurred_at": "어제"},
    ],
)
def test_create_analysis_rejects_invalid_form_values(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
    form: dict[str, str],
) -> None:
    response = upload_analysis(client, auth_header(client), **form)

    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_REQUEST"
    assert fake_storage.objects == {}
    assert run(fetch_all(sessionmaker, VoiceAnalysisJob)) == []
    assert run(fetch_all(sessionmaker, Interaction)) == []


def test_create_analysis_accepts_utc_z_and_blank_optional_values(
    client: TestClient,
    sessionmaker: async_sessionmaker,
) -> None:
    response = upload_analysis(
        client,
        auth_header(client),
        kind="",
        title="   ",
        occurred_at="2026-11-20T05:00:00Z",
    )

    assert response.status_code == 202
    [interaction] = run(fetch_all(sessionmaker, Interaction))
    assert interaction.kind == "meeting"
    assert interaction.title == "meeting"
    assert as_utc(interaction.occurred_at) == datetime(2026, 11, 20, 5, 0, tzinfo=timezone.utc)


def test_create_analysis_with_unknown_or_other_users_customer_returns_404(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
) -> None:
    owner = auth_header(client)
    customer_id = create_customer(client, owner)
    other = auth_header(client, "other@example.com")

    for headers, target in ((other, customer_id), (owner, customer_id + 1)):
        response = upload_analysis(client, headers, customer_id=str(target))
        assert response.status_code == 404
        assert response.json()["code"] == "CUSTOMER_NOT_FOUND"

    assert fake_storage.objects == {}
    assert run(fetch_all(sessionmaker, VoiceAnalysisJob)) == []
    assert run(fetch_all(sessionmaker, Interaction)) == []


def test_create_analysis_storage_failure_creates_no_rows(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    fake_storage: FakeObjectStorage,
) -> None:
    async def fail(*_args, **_kwargs) -> None:
        raise ObjectStorageError

    fake_storage.upload = fail

    response = upload_analysis(client, auth_header(client))

    assert response.status_code == 503
    assert response.json()["code"] == "STORAGE_UNAVAILABLE"
    assert run(fetch_all(sessionmaker, VoiceAnalysisJob)) == []
    assert run(fetch_all(sessionmaker, Interaction)) == []


def test_analysis_requires_authentication(client: TestClient) -> None:
    response = upload(client, ANALYSES_PATH, {}, data={"customer_id": "1"})

    assert response.status_code == 401


def test_create_analysis_rejects_empty_and_large_files(client: TestClient) -> None:
    headers = auth_header(client)

    empty = upload_analysis(client, headers, b"")
    assert empty.status_code == 400
    assert empty.json()["code"] == "EMPTY_FILE"

    large = upload_analysis(client, headers, b"x" * 101)
    assert large.status_code == 413
    assert large.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_create_analysis_without_storage_returns_503(client: TestClient) -> None:
    headers = auth_header(client)
    customer_id = create_customer(client, headers)
    client.app.state.object_storage = None

    response = upload_analysis(client, headers, customer_id=str(customer_id))

    assert response.status_code == 503
    assert response.json()["code"] == "SERVICE_UNAVAILABLE"


def test_enroll_saves_voiceprint(
    client: TestClient,
    sessionmaker: async_sessionmaker,
    ai_client: FakeAIClient,
) -> None:
    ai_client.responses.append(ai_ok(VOICEPRINT))
    headers = auth_header(client)

    response = upload(client, "/api/v1/voice/enroll", headers)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["engine"] == "pyannote"
    assert data["dimensions"] == 256
    assert "vector" not in data
    assert ai_client.calls[0]["path"] == "voice/enroll"
    assert ai_client.calls[0]["timeout"] == 120.0

    [voiceprint] = run(fetch_all(sessionmaker, Voiceprint))
    assert voiceprint.engine == "pyannote"
    assert [float(v) for v in voiceprint.vector] == VOICEPRINT["vector"]

    ai_client.responses.append(ai_ok({"engine": "other", "vector": [0.5] * 256}))
    upload(client, "/api/v1/voice/enroll", headers)
    [voiceprint] = run(fetch_all(sessionmaker, Voiceprint))
    assert voiceprint.engine == "other"


@pytest.mark.parametrize(
    ("ai_response", "status_code", "code"),
    [
        (AIServiceUpstreamError(400, "INVALID_AUDIO"), 400, "INVALID_AUDIO"),
        (AIServiceUpstreamError(501, "FEATURE_NOT_READY"), 501, "FEATURE_NOT_READY"),
        (AIServiceUpstreamError(503, "VOICE_NOT_CONFIGURED"), 502, "AI_SERVICE_ERROR"),
        (ai_ok({"engine": "pyannote", "vector": [0.1] * 10}), 502, "AI_SERVICE_BAD_RESPONSE"),
    ],
)
def test_enroll_maps_ai_errors(
    client: TestClient,
    ai_client: FakeAIClient,
    ai_response,
    status_code: int,
    code: str,
) -> None:
    ai_client.responses.append(ai_response)

    response = upload(client, "/api/v1/voice/enroll", auth_header(client))

    assert response.status_code == status_code
    assert response.json()["code"] == code
