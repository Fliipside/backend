"""Voice analysis worker.

Run with: python -m app.workers.voice_analysis

Run exactly one worker process. The ai service runs one inference at a time,
and this worker handles jobs one by one.
"""
import asyncio
import json
import logging
import signal
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

import httpx
from pydantic import ValidationError
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.clients.ai import AIServiceClient
from app.clients.job_queue import RedisJobQueue
from app.clients.storage import ObjectStorage, S3ObjectStorage
from app.core.config import Settings, get_settings
from app.core.errors import (
    AIServiceBadResponseError,
    AIServiceConnectionError,
    AIServiceTimeoutError,
    AIServiceUpstreamError,
    ObjectNotFoundError,
    ObjectStorageError,
)
from app.models.voice import VoiceAnalysisStatus
from app.repositories import voice as voice_repository
from app.schemas.voice import VoiceAnalysisResult
from app.services.voice import (
    AI_ANALYZE_PATH,
    VOICE_ANALYSIS_QUEUE,
    label_speakers_without_me,
    unwrap_ai_data,
)


logger = logging.getLogger(__name__)

DEQUEUE_TIMEOUT_SECONDS = 5.0
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})

ERROR_MESSAGES = {
    "INVALID_AUDIO": "음성 파일을 분석할 수 없습니다.",
    "VOICEPRINT_ENGINE_MISMATCH": "등록된 목소리가 현재 분석 엔진과 맞지 않습니다. 목소리를 다시 등록해 주세요.",
    "STT_RATE_LIMITED": "음성 인식 사용량 한도에 걸려 분석하지 못했습니다.",
    "STT_FAILED": "음성 인식에 실패했습니다.",
    "FEATURE_NOT_READY": "음성 분석 기능이 아직 준비되지 않았습니다.",
    "AI_SERVICE_UNAVAILABLE": "AI 서비스에 연결할 수 없습니다.",
    "AI_SERVICE_TIMEOUT": "분석 시간이 초과되었습니다.",
    "AI_SERVICE_BAD_RESPONSE": "AI 서비스 응답이 올바르지 않습니다.",
    "RECORDING_NOT_FOUND": "녹음 파일을 찾을 수 없습니다.",
    "STORAGE_UNAVAILABLE": "파일 저장소에 연결할 수 없습니다.",
    "WORKER_INTERRUPTED": "분석 도중 작업이 중단되었습니다.",
}
DEFAULT_ERROR_MESSAGE = "음성 분석에 실패했습니다."
NOT_CONFIGURED_MESSAGE = "AI 서비스 설정이 완료되지 않았습니다."


@dataclass(frozen=True)
class JobFailure:
    code: str
    retryable: bool
    retry_after_seconds: float | None = None

    @property
    def message(self) -> str:
        if self.code.endswith("_NOT_CONFIGURED"):
            return NOT_CONFIGURED_MESSAGE
        return ERROR_MESSAGES.get(self.code, DEFAULT_ERROR_MESSAGE)


@dataclass(frozen=True)
class JobOutcome:
    """retry_after_seconds is set when the job should run again later."""

    retry_after_seconds: float | None = None


def classify_error(exc: Exception) -> JobFailure:
    if isinstance(exc, AIServiceUpstreamError):
        code = exc.code or "AI_SERVICE_ERROR"
        if exc.status_code == 429:
            return JobFailure(
                exc.code or "STT_RATE_LIMITED",
                retryable=True,
                retry_after_seconds=exc.retry_after_seconds,
            )
        if code.endswith("_NOT_CONFIGURED"):
            return JobFailure(code, retryable=False)
        if exc.status_code in RETRYABLE_STATUS_CODES:
            # Without an ai error code this is usually a proxy or a stopped ai container.
            return JobFailure(exc.code or "AI_SERVICE_UNAVAILABLE", retryable=True)
        return JobFailure(code, retryable=False)
    if isinstance(exc, AIServiceConnectionError):
        return JobFailure("AI_SERVICE_UNAVAILABLE", retryable=True)
    if isinstance(exc, AIServiceTimeoutError):
        # The ai model lock is probably still held; retrying would just queue more work.
        return JobFailure("AI_SERVICE_TIMEOUT", retryable=False)
    if isinstance(exc, (AIServiceBadResponseError, ValidationError)):
        return JobFailure("AI_SERVICE_BAD_RESPONSE", retryable=False)
    if isinstance(exc, ObjectNotFoundError):
        return JobFailure("RECORDING_NOT_FOUND", retryable=False)
    if isinstance(exc, ObjectStorageError):
        return JobFailure("STORAGE_UNAVAILABLE", retryable=True)
    return JobFailure("INTERNAL_ERROR", retryable=False)


def _now() -> datetime:
    return datetime.now(UTC)


class VoiceAnalysisWorker:
    def __init__(
            self,
            *,
            sessionmaker: async_sessionmaker,
            queue: RedisJobQueue,
            storage: ObjectStorage,
            ai_client: AIServiceClient,
            settings: Settings,
    ) -> None:
        self._sessionmaker = sessionmaker
        self._queue = queue
        self._storage = storage
        self._ai_client = ai_client
        self._settings = settings

    async def reconcile(self) -> None:
        """Recover ids from a stopped worker and re-queue unfinished jobs Redis lost."""
        recovered = await self._queue.recover_processing()
        async with self._sessionmaker() as session:
            job_ids = await voice_repository.list_unfinished_job_ids(session)
        requeued = 0
        for job_id in job_ids:
            if not await self._queue.contains(str(job_id)):
                await self._queue.enqueue(str(job_id))
                requeued += 1
        logger.info(
            "Voice analysis queue reconciled: recovered=%d requeued=%d",
            recovered,
            requeued,
        )

    async def run_once(self, timeout_seconds: float = DEQUEUE_TIMEOUT_SECONDS) -> bool:
        """Handle at most one job. Returns False when the queue was empty."""
        await self._queue.promote_due()
        job_id = await self._queue.dequeue(timeout_seconds)
        if job_id is None:
            return False

        try:
            outcome = await self.process(UUID(job_id))
        except Exception:
            # DB errors and the like: try again later and keep this loop alive.
            logger.exception("Voice analysis job %s crashed", job_id)
            await self._queue.retry_later(
                job_id,
                self._settings.voice_analysis_retry_base_seconds,
            )
            return True

        if outcome.retry_after_seconds is None:
            await self._queue.ack(job_id)
        else:
            await self._queue.retry_later(job_id, outcome.retry_after_seconds)
        return True

    async def run(self, stop: asyncio.Event) -> None:
        await self.reconcile()
        while not stop.is_set():
            await self.run_once()

    async def process(self, job_id: UUID) -> JobOutcome:
        settings = self._settings
        async with self._sessionmaker() as session:
            job = await voice_repository.get_voice_analysis_job(session, job_id)
            if job is None or job.status in VoiceAnalysisStatus.TERMINAL:
                return JobOutcome()

            if job.attempts >= settings.voice_analysis_max_attempts:
                # Only reachable when the worker stopped mid-job on the last attempt.
                self._mark_failed(job, JobFailure("WORKER_INTERRUPTED", retryable=False))
                await session.commit()
                return JobOutcome()

            voiceprint = await voice_repository.get_voiceprint(session, job.user_id)
            job.status = VoiceAnalysisStatus.PROCESSING
            job.attempts += 1
            job.started_at = job.started_at or _now()
            job.used_voiceprint_engine = voiceprint.engine if voiceprint else None
            await session.commit()

            attempt = job.attempts
            object_key = job.object_key
            filename = job.original_filename
            content_type = job.content_type
            form = (
                {"voiceprint": json.dumps({
                    "engine": voiceprint.engine,
                    "vector": [float(value) for value in voiceprint.vector],
                })}
                if voiceprint
                else None
            )

        # No DB transaction is held during the long ai call.
        try:
            result = await self._analyze(object_key, filename, content_type, form)
        except Exception as exc:
            failure = classify_error(exc)
            if failure.code == "INTERNAL_ERROR":
                logger.exception("Voice analysis job %s failed unexpectedly", job_id)
            else:
                logger.warning(
                    "Voice analysis job %s attempt %d failed: %s",
                    job_id,
                    attempt,
                    failure.code,
                )
            return await self._record_failure(job_id, failure, attempt)

        async with self._sessionmaker() as session:
            job = await voice_repository.get_voice_analysis_job(session, job_id)
            if job is None:
                return JobOutcome()
            job.status = VoiceAnalysisStatus.SUCCEEDED
            job.result = result.model_dump(mode="json")
            job.error_code = None
            job.error_message = None
            job.finished_at = _now()
            await session.commit()
        logger.info("Voice analysis job %s succeeded", job_id)
        return JobOutcome()

    async def _analyze(
            self,
            object_key: str,
            filename: str,
            content_type: str | None,
            form: dict[str, str] | None,
    ) -> VoiceAnalysisResult:
        with tempfile.TemporaryFile() as recording:
            await self._storage.download(object_key, recording)
            recording.seek(0)
            payload = await self._ai_client.post_multipart(
                AI_ANALYZE_PATH,
                files={"file": (filename, recording, content_type)},
                data=form,
                timeout=self._settings.ai_analyze_timeout_seconds,
            )
        result = VoiceAnalysisResult.model_validate(unwrap_ai_data(payload))
        return label_speakers_without_me(result)

    async def _record_failure(
            self,
            job_id: UUID,
            failure: JobFailure,
            attempt: int,
    ) -> JobOutcome:
        settings = self._settings
        retry = failure.retryable and attempt < settings.voice_analysis_max_attempts
        async with self._sessionmaker() as session:
            job = await voice_repository.get_voice_analysis_job(session, job_id)
            if job is None:
                return JobOutcome()
            if retry:
                job.status = VoiceAnalysisStatus.QUEUED
                job.error_code = failure.code
                job.error_message = failure.message
            else:
                self._mark_failed(job, failure)
            await session.commit()

        if not retry:
            return JobOutcome()
        delay = failure.retry_after_seconds
        if delay is None:
            delay = settings.voice_analysis_retry_base_seconds * 2 ** (attempt - 1)
        return JobOutcome(retry_after_seconds=delay)

    @staticmethod
    def _mark_failed(job, failure: JobFailure) -> None:
        job.status = VoiceAnalysisStatus.FAILED
        job.error_code = failure.code
        job.error_message = failure.message
        job.finished_at = _now()


async def main() -> None:
    settings = get_settings()
    missing = [
        name
        for name, value in {
            "PostgreSQL": settings.database_url,
            "REDIS_URL": settings.redis_url,
            "AI_SERVICE_URL": settings.ai_service_url,
            "S3": settings.s3_configured,
        }.items()
        if not value
    ]
    if missing:
        raise RuntimeError(f"Voice analysis worker requires: {', '.join(missing)}")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    http_client = httpx.AsyncClient(
        base_url=settings.ai_service_url,
        timeout=settings.ai_service_timeout_seconds,
    )
    worker = VoiceAnalysisWorker(
        sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
        queue=RedisJobQueue(redis, VOICE_ANALYSIS_QUEUE),
        storage=S3ObjectStorage.from_settings(settings),
        ai_client=AIServiceClient(http_client),
        settings=settings,
    )

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info("Voice analysis worker started")
    try:
        await worker.run(stop)
    finally:
        await http_client.aclose()
        await redis.aclose()
        await engine.dispose()
        logger.info("Voice analysis worker stopped")


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    asyncio.run(main())
