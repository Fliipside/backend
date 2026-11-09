import asyncio
import json
from pathlib import Path
from uuid import UUID, uuid4

import fakeredis
import pytest
from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.clients.job_queue import RedisJobQueue
from app.core.config import Settings
from app.core.errors import (
    AIServiceConnectionError,
    AIServiceTimeoutError,
    AIServiceUpstreamError,
)
from app.db.base import Base
from app.models.user import User
from app.models.voice import VoiceAnalysisJob, Voiceprint
from app.workers.voice_analysis import VoiceAnalysisWorker
from tests.conftest import ANALYSIS_DATA, VOICEPRINT, FakeAIClient, FakeObjectStorage, ai_ok


USER_ID = uuid4()


@pytest.fixture
def sessionmaker(tmp_path: Path) -> async_sessionmaker:
    path = tmp_path / "worker.db"
    sync_engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()
    engine = create_async_engine(f"sqlite+aiosqlite:///{path}", poolclass=NullPool)
    return async_sessionmaker(engine, expire_on_commit=False)


def settings(**overrides) -> Settings:
    values = {
        "postgres_host": "",
        "postgres_db": "",
        "postgres_user": "",
        "postgres_password": "",
        "voice_analysis_max_attempts": 3,
        "voice_analysis_retry_base_seconds": 10,
        "ai_analyze_timeout_seconds": 1800,
    }
    values.update(overrides)
    return Settings(**values)


async def seed(
        sessionmaker: async_sessionmaker,
        storage: FakeObjectStorage,
        *,
        with_voiceprint: bool = True,
        **job_fields,
) -> UUID:
    job_id = uuid4()
    key = f"voice-recordings/{USER_ID}/{job_id}.m4a"
    storage.objects[key] = b"recording-bytes"
    async with sessionmaker() as session:
        if await session.get(User, USER_ID) is None:
            session.add(User(id=USER_ID, email="a@b.c", password_hash="x", nickname="n"))
            await session.flush()
        if with_voiceprint and await session.get(Voiceprint, USER_ID) is None:
            session.add(Voiceprint(user_id=USER_ID, **VOICEPRINT))
        session.add(VoiceAnalysisJob(
            id=job_id,
            user_id=USER_ID,
            object_key=key,
            original_filename="meeting.m4a",
            content_type="audio/mp4",
            file_size=15,
            **job_fields,
        ))
        await session.commit()
    return job_id


async def load(sessionmaker: async_sessionmaker, job_id: UUID) -> VoiceAnalysisJob:
    async with sessionmaker() as session:
        return await session.get(VoiceAnalysisJob, job_id)


def make_worker(sessionmaker, storage, ai_client, **overrides) -> VoiceAnalysisWorker:
    return VoiceAnalysisWorker(
        sessionmaker=sessionmaker,
        queue=RedisJobQueue(fakeredis.aioredis.FakeRedis(decode_responses=True), "test"),
        storage=storage,
        ai_client=ai_client,
        settings=settings(**overrides),
    )


def test_success_sends_recording_and_voiceprint_and_stores_result(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)
        ai_client = FakeAIClient(ai_ok(ANALYSIS_DATA))

        outcome = await make_worker(sessionmaker, storage, ai_client).process(job_id)

        assert outcome.retry_after_seconds is None
        call = ai_client.calls[0]
        assert call["path"] == "voice/analyze"
        assert call["timeout"] == 1800
        assert call["files"]["file"] == ("meeting.m4a", b"recording-bytes", "audio/mp4")
        assert json.loads(call["data"]["voiceprint"]) == VOICEPRINT

        job = await load(sessionmaker, job_id)
        assert job.status == "succeeded"
        assert job.attempts == 1
        assert job.result == ANALYSIS_DATA
        assert job.used_voiceprint_engine == "pyannote"
        assert job.finished_at is not None

    asyncio.run(run_test())


def test_without_voiceprint_omits_form_field(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage, with_voiceprint=False)
        ai_client = FakeAIClient(ai_ok(ANALYSIS_DATA))

        await make_worker(sessionmaker, storage, ai_client).process(job_id)

        assert ai_client.calls[0]["data"] is None
        job = await load(sessionmaker, job_id)
        assert job.status == "succeeded"
        assert job.used_voiceprint_engine is None

    asyncio.run(run_test())


def test_result_without_me_is_stored_with_letter_speakers(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage, with_voiceprint=False)
        data = {
            "speakers": [
                {"speaker": "speaker_1", "role": "unknown", "speech_seconds": 3.0},
                {"speaker": "speaker_2", "role": "unknown", "speech_seconds": 2.0},
            ],
            "utterances": [
                {"start": 0.0, "end": 1.0, "speaker": "speaker_1", "role": "unknown", "text": "안녕하세요"},
                {"start": 1.5, "end": 2.0, "speaker": "speaker_2", "role": "unknown", "text": "네"},
            ],
        }

        await make_worker(sessionmaker, storage, FakeAIClient(ai_ok(data))).process(job_id)

        job = await load(sessionmaker, job_id)
        assert [s["speaker"] for s in job.result["speakers"]] == ["A", "B"]
        assert [u["speaker"] for u in job.result["utterances"]] == ["A", "B"]

    asyncio.run(run_test())


@pytest.mark.parametrize(
    ("error", "expected_delay", "expected_code"),
    [
        (AIServiceUpstreamError(429, "STT_RATE_LIMITED", 42.0), 42.0, "STT_RATE_LIMITED"),
        (AIServiceUpstreamError(429, "STT_RATE_LIMITED"), 10.0, "STT_RATE_LIMITED"),
        (AIServiceUpstreamError(502, "STT_FAILED"), 10.0, "STT_FAILED"),
        (AIServiceUpstreamError(503, None), 10.0, "AI_SERVICE_UNAVAILABLE"),
        (AIServiceConnectionError(), 10.0, "AI_SERVICE_UNAVAILABLE"),
    ],
)
def test_retryable_errors_requeue_job(sessionmaker, error, expected_delay, expected_code) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)

        outcome = await make_worker(sessionmaker, storage, FakeAIClient(error)).process(job_id)

        assert outcome.retry_after_seconds == expected_delay
        job = await load(sessionmaker, job_id)
        assert job.status == "queued"
        assert job.error_code == expected_code
        assert job.finished_at is None

    asyncio.run(run_test())


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        (AIServiceUpstreamError(400, "INVALID_AUDIO"), "INVALID_AUDIO"),
        (AIServiceUpstreamError(400, "VOICEPRINT_ENGINE_MISMATCH"), "VOICEPRINT_ENGINE_MISMATCH"),
        (AIServiceUpstreamError(503, "STT_NOT_CONFIGURED"), "STT_NOT_CONFIGURED"),
        (AIServiceUpstreamError(503, "DIARIZATION_NOT_CONFIGURED"), "DIARIZATION_NOT_CONFIGURED"),
        (AIServiceUpstreamError(501, "FEATURE_NOT_READY"), "FEATURE_NOT_READY"),
        (AIServiceTimeoutError(), "AI_SERVICE_TIMEOUT"),
        ({"success": True, "data": {"speakers": "bad"}}, "AI_SERVICE_BAD_RESPONSE"),
        ({"success": False, "code": "X", "data": None}, "AI_SERVICE_BAD_RESPONSE"),
    ],
)
def test_non_retryable_errors_fail_job(sessionmaker, error, expected_code) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)

        outcome = await make_worker(sessionmaker, storage, FakeAIClient(error)).process(job_id)

        assert outcome.retry_after_seconds is None
        job = await load(sessionmaker, job_id)
        assert job.status == "failed"
        assert job.error_code == expected_code
        assert job.error_message
        assert job.finished_at is not None

    asyncio.run(run_test())


def test_missing_recording_fails_without_calling_ai(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)
        storage.objects.clear()
        ai_client = FakeAIClient()

        await make_worker(sessionmaker, storage, ai_client).process(job_id)

        assert ai_client.calls == []
        job = await load(sessionmaker, job_id)
        assert job.error_code == "RECORDING_NOT_FOUND"

    asyncio.run(run_test())


def test_last_retryable_attempt_fails_job(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage, attempts=2)
        error = AIServiceUpstreamError(502, "STT_FAILED")

        outcome = await make_worker(sessionmaker, storage, FakeAIClient(error)).process(job_id)

        assert outcome.retry_after_seconds is None
        job = await load(sessionmaker, job_id)
        assert job.status == "failed"
        assert job.attempts == 3
        assert job.error_code == "STT_FAILED"

    asyncio.run(run_test())


def test_interrupted_job_on_last_attempt_fails(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage, attempts=3, status="processing")
        ai_client = FakeAIClient()

        await make_worker(sessionmaker, storage, ai_client).process(job_id)

        assert ai_client.calls == []
        job = await load(sessionmaker, job_id)
        assert job.status == "failed"
        assert job.error_code == "WORKER_INTERRUPTED"

    asyncio.run(run_test())


def test_finished_job_is_skipped(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage, status="succeeded")
        ai_client = FakeAIClient()

        await make_worker(sessionmaker, storage, ai_client).process(job_id)

        assert ai_client.calls == []

    asyncio.run(run_test())


def test_run_once_acks_success_and_delays_retry(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        ok_id = await seed(sessionmaker, storage)
        retry_id = await seed(sessionmaker, storage)
        ai_client = FakeAIClient(
            ai_ok(ANALYSIS_DATA),
            AIServiceUpstreamError(429, "STT_RATE_LIMITED", 3600.0),
        )
        worker = make_worker(sessionmaker, storage, ai_client)
        queue = worker._queue
        await queue.enqueue(str(ok_id))
        await queue.enqueue(str(retry_id))

        assert await worker.run_once(0.1)
        assert not await queue.contains(str(ok_id))

        assert await worker.run_once(0.1)
        assert await queue.contains(str(retry_id))
        assert not await worker.run_once(0.1)

    asyncio.run(run_test())


def test_reconcile_requeues_unfinished_jobs_missing_from_redis(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        queued_id = await seed(sessionmaker, storage)
        processing_id = await seed(sessionmaker, storage, status="processing", attempts=1)
        done_id = await seed(sessionmaker, storage, status="succeeded")
        worker = make_worker(sessionmaker, storage, FakeAIClient())

        await worker.reconcile()

        queue = worker._queue
        assert await queue.contains(str(queued_id))
        assert await queue.contains(str(processing_id))
        assert not await queue.contains(str(done_id))

    asyncio.run(run_test())
