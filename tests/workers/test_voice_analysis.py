import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

import fakeredis
import pytest
from redis.exceptions import ConnectionError as RedisConnectionError
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
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
from app.models.customer import Customer
from app.models.interaction import Interaction
from app.models.memory import MemoryIngestJob
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
        with_interaction: bool = True,
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
        interaction_id = None
        if with_interaction:
            customer = Customer(owner_user_id=USER_ID, company_name="노바테크", name="김민준")
            session.add(customer)
            await session.flush()
            interaction_id = uuid4()
            session.add(Interaction(
                id=interaction_id,
                customer_id=customer.id,
                owner_user_id=USER_ID,
                kind="meeting",
                title="미팅",
                occurred_at=datetime.now(UTC),
            ))
        session.add(VoiceAnalysisJob(
            id=job_id,
            user_id=USER_ID,
            interaction_id=interaction_id,
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


async def memory_jobs(sessionmaker: async_sessionmaker) -> list[MemoryIngestJob]:
    async with sessionmaker() as session:
        result = await session.execute(
            select(MemoryIngestJob).order_by(MemoryIngestJob.create_at)
        )
        return list(result.scalars())


async def add_memory_job(
        sessionmaker: async_sessionmaker,
        voice_job_id: UUID,
        status: str = "queued",
) -> UUID:
    async with sessionmaker() as session:
        voice_job = await session.get(VoiceAnalysisJob, voice_job_id)
        memory_job = MemoryIngestJob(
            voice_job_id=voice_job_id,
            interaction_id=voice_job.interaction_id,
            status=status,
        )
        session.add(memory_job)
        await session.commit()
        return memory_job.id


async def queued_ids(queue: RedisJobQueue) -> list[str]:
    return await queue._redis.lrange(queue.pending_key, 0, -1)


class BrokenQueue(RedisJobQueue):
    """Redis is down for every call the voice worker makes on the memory queue."""

    async def enqueue(self, job_id: str) -> None:
        raise RedisConnectionError("redis down")

    async def contains(self, job_id: str) -> bool:
        raise RedisConnectionError("redis down")


def make_worker(
        sessionmaker,
        storage,
        ai_client,
        *,
        memory_queue_class: type[RedisJobQueue] = RedisJobQueue,
        **overrides,
) -> VoiceAnalysisWorker:
    redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return VoiceAnalysisWorker(
        sessionmaker=sessionmaker,
        queue=RedisJobQueue(redis, "test"),
        memory_queue=memory_queue_class(redis, "test-memory"),
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


def test_result_without_me_is_stored_as_ai_returned(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage, with_voiceprint=False)
        data = {
            "speakers": [
                {"speaker": "A", "role": "unknown", "speech_seconds": 3.0},
                {"speaker": "B", "role": "unknown", "speech_seconds": 2.0},
            ],
            "utterances": [
                {"start": 0.0, "end": 1.0, "speaker": "A", "role": "unknown", "text": "안녕하세요"},
                {"start": 1.5, "end": 2.0, "speaker": "B", "role": "unknown", "text": "네"},
            ],
        }

        await make_worker(sessionmaker, storage, FakeAIClient(ai_ok(data))).process(job_id)

        job = await load(sessionmaker, job_id)
        assert job.result == data

    asyncio.run(run_test())


@pytest.mark.parametrize(
    ("error", "expected_delay", "expected_code"),
    [
        (AIServiceUpstreamError(429, "STT_RATE_LIMITED", 42.0), 42.0, "STT_RATE_LIMITED"),
        (AIServiceUpstreamError(429, "STT_RATE_LIMITED"), 10.0, "STT_RATE_LIMITED"),
        (AIServiceUpstreamError(502, "STT_FAILED"), 10.0, "STT_FAILED"),
        (AIServiceUpstreamError(503, None), 10.0, "AI_SERVICE_UNAVAILABLE"),
        (AIServiceUpstreamError(503, None, 30.0), 30.0, "AI_SERVICE_UNAVAILABLE"),
        (AIServiceUpstreamError(503, "VOICE_BUSY", 60.0), 60.0, "VOICE_BUSY"),
        (AIServiceUpstreamError(503, "VOICE_BUSY"), 10.0, "VOICE_BUSY"),
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
        (AIServiceUpstreamError(400, "AUDIO_TOO_LONG"), "AUDIO_TOO_LONG"),
        (AIServiceUpstreamError(503, "STT_NOT_CONFIGURED"), "STT_NOT_CONFIGURED"),
        (AIServiceUpstreamError(503, "DIARIZATION_NOT_CONFIGURED"), "DIARIZATION_NOT_CONFIGURED"),
        (AIServiceUpstreamError(503, "FFMPEG_NOT_CONFIGURED"), "FFMPEG_NOT_CONFIGURED"),
        (AIServiceUpstreamError(400, "INVALID_REQUEST"), "INVALID_REQUEST"),
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


def test_busy_ai_does_not_use_up_attempts(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage, attempts=2)
        error = AIServiceUpstreamError(503, "VOICE_BUSY", 60.0)

        outcome = await make_worker(sessionmaker, storage, FakeAIClient(error)).process(job_id)

        assert outcome.retry_after_seconds == 60.0
        job = await load(sessionmaker, job_id)
        assert job.status == "queued"
        assert job.attempts == 2
        assert job.error_code == "VOICE_BUSY"
        assert job.error_message

    asyncio.run(run_test())


def test_busy_ai_fails_after_max_wait(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        started_at = datetime.now(UTC) - timedelta(hours=2)
        job_id = await seed(sessionmaker, storage, attempts=1, started_at=started_at)
        error = AIServiceUpstreamError(503, "VOICE_BUSY", 60.0)

        outcome = await make_worker(sessionmaker, storage, FakeAIClient(error)).process(job_id)

        assert outcome.retry_after_seconds is None
        job = await load(sessionmaker, job_id)
        assert job.status == "failed"
        assert job.attempts == 1
        assert job.error_code == "VOICE_BUSY"

    asyncio.run(run_test())


def test_audio_too_long_has_dedicated_message(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)
        error = AIServiceUpstreamError(400, "AUDIO_TOO_LONG")

        await make_worker(sessionmaker, storage, FakeAIClient(error)).process(job_id)

        job = await load(sessionmaker, job_id)
        assert job.status == "failed"
        assert job.error_message == "녹음이 60분을 넘어 분석할 수 없습니다."

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


def test_success_creates_memory_ingest_job_and_queues_its_id(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)
        worker = make_worker(sessionmaker, storage, FakeAIClient(ai_ok(ANALYSIS_DATA)))

        await worker.process(job_id)

        voice_job = await load(sessionmaker, job_id)
        assert voice_job.status == "succeeded"
        [memory_job] = await memory_jobs(sessionmaker)
        assert memory_job.voice_job_id == job_id
        assert memory_job.interaction_id == voice_job.interaction_id
        assert memory_job.status == "queued"
        assert memory_job.attempts == 0
        assert memory_job.started_at is None
        assert memory_job.finished_at is None
        # Only the memory_ingest_jobs id goes into Redis.
        assert await queued_ids(worker._memory_queue) == [str(memory_job.id)]
        assert await queued_ids(worker._queue) == []

    asyncio.run(run_test())


@pytest.mark.parametrize(
    "error",
    [
        AIServiceUpstreamError(400, "INVALID_AUDIO"),
        AIServiceUpstreamError(502, "STT_FAILED"),
        AIServiceTimeoutError(),
    ],
)
def test_failed_or_retried_analysis_does_not_queue_memory_ingest(sessionmaker, error) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)
        worker = make_worker(sessionmaker, storage, FakeAIClient(error))

        await worker.process(job_id)

        assert (await load(sessionmaker, job_id)).status != "succeeded"
        assert await memory_jobs(sessionmaker) == []
        assert await queued_ids(worker._memory_queue) == []

    asyncio.run(run_test())


def test_job_without_interaction_is_not_queued_for_memory_ingest(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage, with_interaction=False)
        worker = make_worker(sessionmaker, storage, FakeAIClient(ai_ok(ANALYSIS_DATA)))

        await worker.process(job_id)

        assert (await load(sessionmaker, job_id)).status == "succeeded"
        assert await memory_jobs(sessionmaker) == []
        assert await queued_ids(worker._memory_queue) == []

    asyncio.run(run_test())


def test_redis_error_on_memory_queue_keeps_analysis_succeeded(sessionmaker, caplog) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)
        worker = make_worker(
            sessionmaker,
            storage,
            FakeAIClient(ai_ok(ANALYSIS_DATA)),
            memory_queue_class=BrokenQueue,
        )
        await worker._queue.enqueue(str(job_id))

        assert await worker.run_once(0.1)

        voice_job = await load(sessionmaker, job_id)
        assert voice_job.status == "succeeded"
        assert voice_job.result == ANALYSIS_DATA
        # Acked, not retried: the analysis must not run again.
        assert not await worker._queue.contains(str(job_id))
        [memory_job] = await memory_jobs(sessionmaker)
        assert memory_job.status == "queued"
        assert f"Memory ingest job {memory_job.id} could not be queued" in caplog.text

    asyncio.run(run_test())


def test_reconcile_queues_memory_job_left_out_by_redis_error(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)
        broken = make_worker(
            sessionmaker,
            storage,
            FakeAIClient(ai_ok(ANALYSIS_DATA)),
            memory_queue_class=BrokenQueue,
        )
        await broken.process(job_id)
        [memory_job] = await memory_jobs(sessionmaker)

        # The worker restarts with Redis back.
        worker = make_worker(sessionmaker, storage, FakeAIClient())
        await worker.reconcile()

        assert await queued_ids(worker._memory_queue) == [str(memory_job.id)]

    asyncio.run(run_test())


def test_reconcile_requeues_only_queued_memory_jobs_missing_from_redis(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        voice_ids = [
            await seed(sessionmaker, storage, status="succeeded") for _ in range(5)
        ]
        missing_id = await add_memory_job(sessionmaker, voice_ids[0])
        pending_id = await add_memory_job(sessionmaker, voice_ids[1])
        taken_id = await add_memory_job(sessionmaker, voice_ids[2])
        processing_id = await add_memory_job(sessionmaker, voice_ids[3], "processing")
        done_id = await add_memory_job(sessionmaker, voice_ids[4], "succeeded")
        worker = make_worker(sessionmaker, storage, FakeAIClient())
        memory_queue = worker._memory_queue
        await memory_queue.enqueue(str(pending_id))
        # The memory ingest worker took this one but has not updated the row yet.
        await memory_queue.enqueue(str(taken_id))
        assert await memory_queue.dequeue(0.1) == str(pending_id)
        await memory_queue.ack(str(pending_id))
        await memory_queue.enqueue(str(pending_id))
        assert await memory_queue.dequeue(0.1) == str(taken_id)

        await worker.reconcile()
        await worker.reconcile()

        assert sorted(await queued_ids(memory_queue)) == sorted(
            [str(missing_id), str(pending_id)]
        )
        # The other worker's in-progress id is not pulled back to pending.
        assert await memory_queue._redis.lrange(memory_queue.processing_key, 0, -1) == [
            str(taken_id)
        ]
        assert not await memory_queue.contains(str(processing_id))
        assert not await memory_queue.contains(str(done_id))

    asyncio.run(run_test())


def test_reconcile_still_requeues_voice_jobs_when_memory_queue_fails(sessionmaker, caplog) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        voice_id = await seed(sessionmaker, storage)
        done_id = await seed(sessionmaker, storage, status="succeeded")
        await add_memory_job(sessionmaker, done_id)
        worker = make_worker(
            sessionmaker,
            storage,
            FakeAIClient(),
            memory_queue_class=BrokenQueue,
        )

        await worker.reconcile()

        assert await worker._queue.contains(str(voice_id))
        assert "Memory ingest queue reconcile failed" in caplog.text

    asyncio.run(run_test())


def test_same_voice_job_gets_one_memory_ingest_job(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        # A row already exists, as if this job had been finished once before.
        job_id = await seed(sessionmaker, storage)
        existing_id = await add_memory_job(sessionmaker, job_id)
        worker = make_worker(sessionmaker, storage, FakeAIClient(ai_ok(ANALYSIS_DATA)))

        await worker.process(job_id)

        assert (await load(sessionmaker, job_id)).status == "succeeded"
        assert [job.id for job in await memory_jobs(sessionmaker)] == [existing_id]
        assert await queued_ids(worker._memory_queue) == []

        # The table itself also refuses a second row.
        with pytest.raises(IntegrityError):
            await add_memory_job(sessionmaker, job_id)

    asyncio.run(run_test())


def test_processing_a_succeeded_job_again_adds_nothing(sessionmaker) -> None:
    async def run_test() -> None:
        storage = FakeObjectStorage()
        job_id = await seed(sessionmaker, storage)
        ai_client = FakeAIClient(ai_ok(ANALYSIS_DATA))
        worker = make_worker(sessionmaker, storage, ai_client)

        await worker.process(job_id)
        await worker.process(job_id)

        assert len(ai_client.calls) == 1
        assert len(await memory_jobs(sessionmaker)) == 1
        assert len(await queued_ids(worker._memory_queue)) == 1

    asyncio.run(run_test())
